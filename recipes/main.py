import base64
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
import httpx
from anthropic import Anthropic
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DATA_DIR = Path("/app/data")
IMAGES_DIR = DATA_DIR / "images"
RECIPES_FILE = DATA_DIR / "recipes.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

if not RECIPES_FILE.exists():
    RECIPES_FILE.write_text("[]")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory=str(IMAGES_DIR)), name="uploads")
templates = Jinja2Templates(directory="templates")

CATEGORIES = ["Frukost", "Lunch", "Middag", "Dessert", "Bakning", "Snacks", "Drycker", "Övrigt"]
UNITS = ["krm", "tsk", "msk", "dl", "l", "ml", "g", "kg", "st", "nypa", "skiva", "klyfta"]

anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

INGEST_PROMPT = """Du är en recept-assistent. Extrahera receptet och svara ENDAST med giltig JSON, inget annat text:
{
  "title": "receptets namn",
  "description": "kort beskrivning på svenska, max 2 meningar",
  "servings": "antal portioner som sträng t.ex. 4",
  "cook_time": "tid som sträng t.ex. 30 min",
  "category": "en av: Frukost, Lunch, Middag, Dessert, Bakning, Snacks, Drycker, Övrigt",
  "ingredients": [{"amount": "mängd", "unit": "enhet", "name": "ingrediensnamn"}],
  "steps": ["steg 1", "steg 2"]
}
Regler:
- Svara alltid på svenska
- amount ska vara en sträng (t.ex. "400" eller "2-3")
- unit ska vara en av: krm, tsk, msk, dl, l, ml, g, kg, st, nypa, skiva, klyfta (eller tom sträng om ingen enhet)
- Parafrasera stegen med egna ord
- Om något saknas, lämna tomt sträng"""


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "ads"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()[:12000]


def parse_claude_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group()
    return json.loads(text)


def load_recipes() -> list:
    return json.loads(RECIPES_FILE.read_text())


def save_recipes(recipes: list):
    RECIPES_FILE.write_text(json.dumps(recipes, ensure_ascii=False, indent=2))


def get_recipe(recipe_id: str) -> Optional[dict]:
    return next((r for r in load_recipes() if r["id"] == recipe_id), None)


def ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: str = "", category: str = ""):
    recipes = load_recipes()
    if q:
        ql = q.lower()
        recipes = [r for r in recipes if ql in r["title"].lower() or ql in r.get("description", "").lower()]
    if category:
        recipes = [r for r in recipes if r.get("category") == category]
    recipes.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "recipes": recipes,
        "q": q,
        "category": category,
        "categories": CATEGORIES,
    })


@app.get("/new", response_class=HTMLResponse)
async def new_recipe_form(request: Request):
    return templates.TemplateResponse("form.html", {
        "request": request,
        "recipe": None,
        "categories": CATEGORIES,
        "units": UNITS,
    })


@app.post("/new")
async def create_recipe(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    servings: str = Form(""),
    cook_time: str = Form(""),
    category: str = Form(""),
    ingredient_amounts: List[str] = Form(default=[]),
    ingredient_units: List[str] = Form(default=[]),
    ingredient_names: List[str] = Form(default=[]),
    steps: List[str] = Form(default=[]),
    image: Optional[UploadFile] = File(None),
):
    recipe_id = str(uuid.uuid4())
    image_filename = None

    if image and image.filename:
        ext = Path(image.filename).suffix.lower()
        image_filename = f"{recipe_id}{ext}"
        async with aiofiles.open(IMAGES_DIR / image_filename, "wb") as f:
            await f.write(await image.read())

    amounts = ensure_list(ingredient_amounts)
    units_list = ensure_list(ingredient_units)
    names = ensure_list(ingredient_names)
    ingredients = [
        {"amount": a, "unit": u, "name": n.strip()}
        for a, u, n in zip(amounts, units_list, names)
        if n.strip()
    ]

    steps_clean = [s.strip() for s in ensure_list(steps) if s.strip()]

    recipe = {
        "id": recipe_id,
        "title": title.strip(),
        "description": description.strip(),
        "servings": servings.strip(),
        "cook_time": cook_time.strip(),
        "category": category,
        "ingredients": ingredients,
        "steps": steps_clean,
        "image": image_filename,
        "created_at": datetime.now().isoformat(),
    }

    recipes = load_recipes()
    recipes.append(recipe)
    save_recipes(recipes)

    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
async def view_recipe(request: Request, recipe_id: str):
    recipe = get_recipe(recipe_id)
    if not recipe:
        return HTMLResponse("Recept hittades inte", status_code=404)
    return templates.TemplateResponse("recipe.html", {"request": request, "recipe": recipe})


@app.get("/edit/{recipe_id}", response_class=HTMLResponse)
async def edit_recipe_form(request: Request, recipe_id: str):
    recipe = get_recipe(recipe_id)
    if not recipe:
        return HTMLResponse("Recept hittades inte", status_code=404)
    return templates.TemplateResponse("form.html", {
        "request": request,
        "recipe": recipe,
        "categories": CATEGORIES,
        "units": UNITS,
    })


@app.post("/edit/{recipe_id}")
async def update_recipe(
    request: Request,
    recipe_id: str,
    title: str = Form(...),
    description: str = Form(""),
    servings: str = Form(""),
    cook_time: str = Form(""),
    category: str = Form(""),
    ingredient_amounts: List[str] = Form(default=[]),
    ingredient_units: List[str] = Form(default=[]),
    ingredient_names: List[str] = Form(default=[]),
    steps: List[str] = Form(default=[]),
    image: Optional[UploadFile] = File(None),
):
    recipes = load_recipes()
    idx = next((i for i, r in enumerate(recipes) if r["id"] == recipe_id), None)
    if idx is None:
        return HTMLResponse("Recept hittades inte", status_code=404)

    recipe = recipes[idx]
    image_filename = recipe.get("image")

    if image and image.filename:
        if image_filename:
            old = IMAGES_DIR / image_filename
            if old.exists():
                old.unlink()
        ext = Path(image.filename).suffix.lower()
        image_filename = f"{recipe_id}{ext}"
        async with aiofiles.open(IMAGES_DIR / image_filename, "wb") as f:
            await f.write(await image.read())

    amounts = ensure_list(ingredient_amounts)
    units_list = ensure_list(ingredient_units)
    names = ensure_list(ingredient_names)
    ingredients = [
        {"amount": a, "unit": u, "name": n.strip()}
        for a, u, n in zip(amounts, units_list, names)
        if n.strip()
    ]

    steps_clean = [s.strip() for s in ensure_list(steps) if s.strip()]

    recipe.update({
        "title": title.strip(),
        "description": description.strip(),
        "servings": servings.strip(),
        "cook_time": cook_time.strip(),
        "category": category,
        "ingredients": ingredients,
        "steps": steps_clean,
        "image": image_filename,
    })
    recipes[idx] = recipe
    save_recipes(recipes)

    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.get("/import", response_class=HTMLResponse)
async def import_form(request: Request):
    return templates.TemplateResponse("import.html", {"request": request, "error": None})


@app.post("/ingest")
async def ingest_recipe(
    request: Request,
    source_url: str = Form(""),
    image: Optional[UploadFile] = File(None),
):
    try:
        if image and image.filename:
            image_bytes = await image.read()
            image_b64 = base64.standard_b64encode(image_bytes).decode()
            media_type = image.content_type or "image/jpeg"
            message = anthropic_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": INGEST_PROMPT},
                    ],
                }],
            )
        elif source_url.strip():
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(source_url.strip())
            text = extract_text_from_html(resp.text)
            message = anthropic_client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": f"{INGEST_PROMPT}\n\nKälla: {source_url}\n\nText:\n{text}",
                }],
            )
        else:
            return templates.TemplateResponse("import.html", {"request": request, "error": "Ange en URL eller ladda upp en bild."})

        data = parse_claude_json(message.content[0].text)

        recipe_id = str(uuid.uuid4())
        recipe = {
            "id": recipe_id,
            "title": data.get("title", "").strip(),
            "description": data.get("description", "").strip(),
            "servings": str(data.get("servings", "")).strip(),
            "cook_time": str(data.get("cook_time", "")).strip(),
            "category": data.get("category", ""),
            "ingredients": [
                {"amount": str(i.get("amount", "")), "unit": i.get("unit", ""), "name": i.get("name", "").strip()}
                for i in data.get("ingredients", []) if i.get("name", "").strip()
            ],
            "steps": [s.strip() for s in data.get("steps", []) if str(s).strip()],
            "image": None,
            "created_at": datetime.now().isoformat(),
        }

        recipes = load_recipes()
        recipes.append(recipe)
        save_recipes(recipes)

        return RedirectResponse(f"/edit/{recipe_id}", status_code=303)

    except Exception as e:
        return templates.TemplateResponse("import.html", {"request": request, "error": f"Något gick fel: {e}"})


@app.get("/delete/{recipe_id}", response_class=HTMLResponse)
async def confirm_delete(request: Request, recipe_id: str):
    recipe = get_recipe(recipe_id)
    if not recipe:
        return HTMLResponse("Recept hittades inte", status_code=404)
    return templates.TemplateResponse("confirm_delete.html", {"request": request, "recipe": recipe})


@app.post("/delete/{recipe_id}")
async def delete_recipe(recipe_id: str):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r["id"] == recipe_id), None)
    if recipe:
        if recipe.get("image"):
            img = IMAGES_DIR / recipe["image"]
            if img.exists():
                img.unlink()
        save_recipes([r for r in recipes if r["id"] != recipe_id])
    return RedirectResponse("/", status_code=303)
