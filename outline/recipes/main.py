import os
import sqlite3
from contextlib import contextmanager
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = os.getenv("DB_PATH", "recipes.db")

UNITS = ["krm", "tsk", "msk", "dl", "l", "ml", "g", "kg", "st"]
CATEGORIES = ["Frukost", "Lunch", "Middag", "Dessert", "Bakning", "Snack", "Dryck", "Övrigt"]


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                servings INTEGER DEFAULT 4,
                category TEXT DEFAULT 'Övrigt',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                amount TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                step_number INTEGER NOT NULL,
                description TEXT NOT NULL
            );
        """)


init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: str = ""):
    with get_db() as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM recipes WHERE title LIKE ? OR category LIKE ? ORDER BY created_at DESC",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM recipes ORDER BY created_at DESC").fetchall()
    return templates.TemplateResponse("index.html", {"request": request, "recipes": rows, "q": q})


@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
async def view_recipe(request: Request, recipe_id: int):
    with get_db() as conn:
        recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not recipe:
            raise HTTPException(status_code=404, detail="Receptet hittades inte")
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE recipe_id = ? ORDER BY id", (recipe_id,)
        ).fetchall()
        steps = conn.execute(
            "SELECT * FROM steps WHERE recipe_id = ? ORDER BY step_number", (recipe_id,)
        ).fetchall()
    return templates.TemplateResponse("recipe.html", {
        "request": request, "recipe": recipe,
        "ingredients": ingredients, "steps": steps
    })


@app.get("/add", response_class=HTMLResponse)
async def add_form(request: Request):
    return templates.TemplateResponse("form.html", {
        "request": request, "recipe": None,
        "units": UNITS, "categories": CATEGORIES
    })


@app.post("/add")
async def add_recipe(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    servings: int = Form(4),
    category: str = Form("Övrigt"),
    ing_amount: list[str] = Form(default=[]),
    ing_unit: list[str] = Form(default=[]),
    ing_name: list[str] = Form(default=[]),
    step_desc: list[str] = Form(default=[]),
):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (title, description, servings, category) VALUES (?, ?, ?, ?)",
            (title.strip(), description.strip(), servings, category)
        )
        recipe_id = cur.lastrowid
        for i, name in enumerate(ing_name):
            name = name.strip()
            if name:
                amount = ing_amount[i] if i < len(ing_amount) else ""
                unit = ing_unit[i] if i < len(ing_unit) else ""
                conn.execute(
                    "INSERT INTO ingredients (recipe_id, amount, unit, name) VALUES (?, ?, ?, ?)",
                    (recipe_id, amount.strip(), unit.strip(), name)
                )
        for step_num, desc in enumerate(step_desc, start=1):
            desc = desc.strip()
            if desc:
                conn.execute(
                    "INSERT INTO steps (recipe_id, step_number, description) VALUES (?, ?, ?)",
                    (recipe_id, step_num, desc)
                )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.get("/edit/{recipe_id}", response_class=HTMLResponse)
async def edit_form(request: Request, recipe_id: int):
    with get_db() as conn:
        recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not recipe:
            raise HTTPException(status_code=404, detail="Receptet hittades inte")
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE recipe_id = ? ORDER BY id", (recipe_id,)
        ).fetchall()
        steps = conn.execute(
            "SELECT * FROM steps WHERE recipe_id = ? ORDER BY step_number", (recipe_id,)
        ).fetchall()
    return templates.TemplateResponse("form.html", {
        "request": request, "recipe": recipe,
        "ingredients": ingredients, "steps": steps,
        "units": UNITS, "categories": CATEGORIES
    })


@app.post("/edit/{recipe_id}")
async def edit_recipe(
    recipe_id: int,
    title: str = Form(...),
    description: str = Form(""),
    servings: int = Form(4),
    category: str = Form("Övrigt"),
    ing_amount: list[str] = Form(default=[]),
    ing_unit: list[str] = Form(default=[]),
    ing_name: list[str] = Form(default=[]),
    step_desc: list[str] = Form(default=[]),
):
    with get_db() as conn:
        conn.execute(
            "UPDATE recipes SET title=?, description=?, servings=?, category=? WHERE id=?",
            (title.strip(), description.strip(), servings, category, recipe_id)
        )
        conn.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        conn.execute("DELETE FROM steps WHERE recipe_id = ?", (recipe_id,))
        for i, name in enumerate(ing_name):
            name = name.strip()
            if name:
                amount = ing_amount[i] if i < len(ing_amount) else ""
                unit = ing_unit[i] if i < len(ing_unit) else ""
                conn.execute(
                    "INSERT INTO ingredients (recipe_id, amount, unit, name) VALUES (?, ?, ?, ?)",
                    (recipe_id, amount.strip(), unit.strip(), name)
                )
        for step_num, desc in enumerate(step_desc, start=1):
            desc = desc.strip()
            if desc:
                conn.execute(
                    "INSERT INTO steps (recipe_id, step_number, description) VALUES (?, ?, ?)",
                    (recipe_id, step_num, desc)
                )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


@app.post("/delete/{recipe_id}")
async def delete_recipe(recipe_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    return RedirectResponse("/", status_code=303)
