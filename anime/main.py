import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
FOLLOWS_FILE = DATA_DIR / "follows.json"

if not FOLLOWS_FILE.exists():
    FOLLOWS_FILE.write_text("{}")

ANILIST_API = "https://graphql.anilist.co"

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def load_follows() -> dict:
    return json.loads(FOLLOWS_FILE.read_text())


def save_follows(data: dict):
    FOLLOWS_FILE.write_text(json.dumps(data, indent=2))


def get_title(media: dict) -> str:
    t = media.get("title", {})
    return t.get("english") or t.get("romaji") or "Unknown"



async def anilist(query: str, variables: dict) -> dict | None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ANILIST_API,
            json={"query": query, "variables": variables},
            timeout=10,
        )
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        return resp.json()


SEARCH_QUERY = """
query ($search: String) {
  Page(perPage: 6) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english }
      coverImage { medium large }
      status
      seasonYear
      season
      startDate { year month day }
      nextAiringEpisode { episode airingAt }
    }
  }
}
"""

MEDIA_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english }
    coverImage { medium large }
    status
    episodes
    seasonYear
    season
    startDate { year month day }
    nextAiringEpisode { episode airingAt timeUntilAiring }
  }
}
"""


async def fetch_media(anilist_id: int) -> dict | None:
    result = await anilist(MEDIA_QUERY, {"id": anilist_id})
    if result is None:
        return None
    return result.get("data", {}).get("Media") or {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    follows = load_follows()

    def sort_key(e):
        nep = e.get("next_episode")
        return nep["airingAt"] if nep else float("inf")

    items = sorted(follows.values(), key=sort_key)
    return templates.TemplateResponse("index.html", {"request": request, "follows": items})


@app.get("/search")
async def search(q: str):
    if len(q.strip()) < 2:
        return JSONResponse([])
    result = await anilist(SEARCH_QUERY, {"search": q.strip()})
    if result is None:
        return JSONResponse({"error": "Rate limited by AniList, try again shortly"}, status_code=429)
    media_list = result.get("data", {}).get("Page", {}).get("media", [])
    return JSONResponse(media_list)


@app.post("/follow/{anilist_id}")
async def follow(anilist_id: int):
    follows = load_follows()
    if str(anilist_id) in follows:
        return JSONResponse({"ok": True})

    media = await fetch_media(anilist_id)
    if not media:
        raise HTTPException(status_code=404, detail="Anime not found")

    follows[str(anilist_id)] = {
        "anilist_id": anilist_id,
        "title": get_title(media),
        "title_romaji": media.get("title", {}).get("romaji"),
        "cover": media.get("coverImage", {}).get("large") or media.get("coverImage", {}).get("medium"),
        "season": media.get("season"),
        "season_year": media.get("seasonYear"),
        "status": media.get("status"),
        "episodes": media.get("episodes"),
        "start_date": media.get("startDate"),
        "next_episode": media.get("nextAiringEpisode"),
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
        "followed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_follows(follows)
    return JSONResponse({"ok": True})


@app.delete("/follow/{anilist_id}")
async def unfollow(anilist_id: int):
    follows = load_follows()
    follows.pop(str(anilist_id), None)
    save_follows(follows)
    return JSONResponse({"ok": True})


@app.post("/refresh")
async def refresh_all():
    follows = load_follows()
    for aid, entry in follows.items():
        media = await fetch_media(int(aid))
        if media:
            entry["next_episode"] = media.get("nextAiringEpisode")
            entry["status"] = media.get("status")
            entry["start_date"] = media.get("startDate")
            entry["last_refreshed"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(0.6)
    save_follows(follows)
    return JSONResponse({"ok": True})
