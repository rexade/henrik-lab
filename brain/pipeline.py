import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import aiofiles
import httpx
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup

from outline_client import OutlineClient

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTLINE_URL   = os.getenv("OUTLINE_URL", "http://outline:3000")
OUTLINE_TOKEN = os.getenv("OUTLINE_TOKEN", "")

ai      = AsyncAnthropic(api_key=ANTHROPIC_KEY)
outline = OutlineClient(OUTLINE_URL, OUTLINE_TOKEN)

# ~40k tokens per chunk (1 token ≈ 4 chars)
CHUNK_SIZE    = 150_000
CHUNK_OVERLAP = 3_000


# ── Extraction ────────────────────────────────────────────────────────────────

def _youtube_video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


async def extract_youtube(url: str) -> str:
    import asyncio
    import os
    import tempfile
    import yt_dlp

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "outtmpl": os.path.join(tmpdir, "%(id)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        info = await asyncio.get_event_loop().run_in_executor(None, _download)

        title       = info.get("title", "")
        description = info.get("description", "")

        # Parse any downloaded .vtt subtitle file
        sub_text = ""
        for fname in os.listdir(tmpdir):
            if fname.endswith(".vtt"):
                raw = open(os.path.join(tmpdir, fname)).read()
                lines = []
                for line in raw.splitlines():
                    if "-->" in line or not line.strip() or line.startswith("WEBVTT"):
                        continue
                    clean = re.sub(r"<[^>]+>", "", line).strip()
                    if clean and not re.match(r"^\d+$", clean):
                        lines.append(clean)
                # Deduplicate consecutive identical lines (VTT overlap artifact)
                deduped = [lines[0]] if lines else []
                for l in lines[1:]:
                    if l != deduped[-1]:
                        deduped.append(l)
                sub_text = " ".join(deduped)
                break

        content = sub_text or description
        if not content.strip():
            raise ValueError("Could not extract transcript or description from this video")

        header = f"YouTube video: {title}\nURL: {url}\n\n"
        return header + content


async def extract_url(url: str) -> str:
    if re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts)", url):
        return await extract_youtube(url)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()


def extract_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()


async def extract_image(path: str) -> str:
    data = Path(path).read_bytes()
    b64  = base64.standard_b64encode(data).decode()
    ext  = path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
    msg = await ai.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text",  "text": "Extract all text and content from this image. Preserve structure."},
        ]}],
    )
    return msg.content[0].text


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    parts, start = [], 0
    while start < len(text):
        parts.append(text[start: start + CHUNK_SIZE])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return parts


# ── AI calls ──────────────────────────────────────────────────────────────────

async def summarize_chunk(text: str, n: int, total: int, source: str) -> str:
    msg = await ai.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content":
            f"You are extracting knowledge from chunk {n}/{total} of '{source}' so someone never has to watch/read it.\n\n"
            f"Extract every technique, rule, step, and insight that is actually TAUGHT — written as if explaining it to someone directly.\n"
            f"Write WHAT was taught, not THAT it was taught. Never write 'the instructor demonstrates X' — instead write what X is and how it works.\n"
            f"Skip filler, intros, sponsor segments, and anything obvious.\n\n{text}"
        }],
    )
    return msg.content[0].text


DISTILL_PROMPT = """\
You are a knowledge distillation expert. Your job is to replace the need to watch or read the source entirely.
The reader will use this note instead of watching the video or reading the article.
Capture what was actually taught — techniques, rules, steps, insights — written directly, as knowledge.

Respond with ONLY valid JSON:
{
  "title": "clear descriptive title",
  "topic": "broad domain (e.g. Programming, History, Science, Finance, Gaming, Health, Cooking, Productivity, Other)",
  "subtopic": "specific area within that domain",
  "tier": "A or B or C",
  "tier_reason": "A=high value & reliable source, B=useful but uncertain, C=low value or pure opinion",
  "tags": ["tag1", "tag2", "tag3"],
  "tldr": "1-2 sentences. The single core insight or takeaway.",
  "key_points": ["point 1", "point 2", "point 3"],
  "clean_markdown": "see format rules below"
}

FORMAT FOR clean_markdown:

## TL;DR
1-2 sentences. The core lesson — what the reader walks away knowing.

## Key Points
- 5–10 bullets. Each = one concrete technique, rule, or insight written directly.
- Write as knowledge, not as reference: "Squint to merge shapes into 3 values" not "the video covers value simplification".
- If there are many techniques, group by theme with a bold label.
- Include the non-obvious. Skip anything anyone already knows.

## Details
*Omit if Key Points already cover everything.*
Use only for a concept or mechanism that needs more than a bullet to make sense. Max 5 sentences.

## Sources
- {source}

RULES:
- Every word earns its place. No padding.
- Aim for 200–450 words. Hard cap 600.
- Write in second person where natural ("squint to see", "mix in a drop of", "hold the brush at 45°").
- NEVER write about the video/article itself. No "this video", "the instructor", "the author argues", "this tutorial covers".
- NEVER describe the audience, format, or production style of the source.
- If the source is a long video with many techniques, include all meaningful ones — a long note is fine here, better than losing knowledge.

Source: {source}

CONTENT:
{content}"""


async def distill(content: str, source: str) -> dict:
    prompt = (DISTILL_PROMPT
              .replace("{source}", source)
              .replace("{content}", content[:120_000]))
    msg = await ai.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group() if m else text)


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_pipeline(
    text: str = "",
    url:  str = "",
    file_path:  Optional[str] = None,
    file_name:  Optional[str] = None,
    on_step: Callable[[str], None] = lambda s: None,
) -> dict:

    # 1. Extract
    on_step("Extracting content")
    source = url or file_name or "pasted text"

    # If the text field contains a bare URL, treat it as a URL input
    if not url and re.match(r"https?://\S+$", text.strip()):
        url = text.strip()
        text = ""

    if file_path and file_name:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext == "pdf":
            raw = extract_pdf(file_path)
        elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
            raw = await extract_image(file_path)
        else:
            async with aiofiles.open(file_path, "r", errors="replace") as f:
                raw = await f.read()
    elif url.strip():
        raw = await extract_url(url.strip())
    else:
        raw = text.strip()

    if not raw:
        raise ValueError("Could not extract any content")

    # 2. Chunk large documents
    chunks = chunk(raw)
    if len(chunks) > 1:
        on_step(f"Large document — {len(chunks)} sections to process")
        summaries = []
        for i, c in enumerate(chunks, 1):
            on_step(f"Summarizing section {i} of {len(chunks)}")
            summaries.append(await summarize_chunk(c, i, len(chunks), source))
        on_step("Synthesizing all sections")
        distill_input = "\n\n---\n\n".join(summaries)
    else:
        distill_input = raw

    # 3. Distill
    on_step("Distilling with AI")
    data = await distill(distill_input, source)

    # 4. Build final markdown
    footer = (
        f"\n\n---\n"
        f"*Quality: **Tier {data.get('tier','?')}** — {data.get('tier_reason','')}*  \n"
        f"*Tags: {', '.join(f'`{t}`' for t in data.get('tags', []))}*  \n"
        f"*Imported: {datetime.now().strftime('%Y-%m-%d')} · Source: {source}*"
    )
    clean_md = data.get("clean_markdown", "") + footer

    # 5. Write to Outline
    on_step("Writing to Outline")
    inbox_id, library_id = await outline.ensure_collections()

    inbox_doc = await outline.create_document(
        collection_id=inbox_id,
        title=f"[Inbox] {data['title']}",
        text=f"*Raw import from: {source}*\n\n{raw[:8000]}{'…[truncated]' if len(raw) > 8000 else ''}",
    )
    library_doc = await outline.create_document(
        collection_id=library_id,
        title=data["title"],
        text=clean_md,
        topic=data.get("topic", "Other"),
    )

    on_step("Done")
    return {
        "title":       data["title"],
        "tier":        data.get("tier", "?"),
        "topic":       data.get("topic", ""),
        "subtopic":    data.get("subtopic", ""),
        "tags":        data.get("tags", []),
        "tldr":        data.get("tldr", ""),
        "key_points":  data.get("key_points", []),
        "outline_url": f"https://notes.rexthedog.space{library_doc['url']}",
        "inbox_url":   f"https://notes.rexthedog.space{inbox_doc['url']}",
    }
