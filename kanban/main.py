import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "kanban.db"

COLUMNS = ["backlog", "next", "doing", "done"]
COLUMN_LABELS = {
    "backlog": "Backlog",
    "next": "Next",
    "doing": "Doing",
    "done": "Done",
}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            column      TEXT NOT NULL DEFAULT 'backlog',
            position    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class CardCreate(BaseModel):
    title: str
    description: str = ""
    column: str = "backlog"


class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None


class ReorderRequest(BaseModel):
    column: str
    order: list[str]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM cards ORDER BY position ASC, created_at ASC"
    ).fetchall()
    conn.close()
    board = {col: [] for col in COLUMNS}
    for row in rows:
        col = row["column"] if row["column"] in COLUMNS else "backlog"
        board[col].append(dict(row))
    return templates.TemplateResponse("index.html", {
        "request": request,
        "board": board,
        "columns": COLUMNS,
        "column_labels": COLUMN_LABELS,
    })


@app.post("/api/cards")
async def create_card(data: CardCreate):
    col = data.column if data.column in COLUMNS else "backlog"
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM cards WHERE column = ?", (col,)
    ).fetchone()
    max_pos = row[0]
    card_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO cards (id, title, description, column, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (card_id, data.title.strip(), data.description.strip(), col, max_pos + 1, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return JSONResponse({
        "id": card_id,
        "title": data.title.strip(),
        "description": data.description.strip(),
        "column": col,
    })


@app.get("/api/cards/{card_id}")
async def get_card(card_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(dict(row))


@app.patch("/api/cards/{card_id}")
async def update_card(card_id: str, data: CardUpdate):
    conn = get_db()
    row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        conn.close()
        return JSONResponse({"error": "not found"}, status_code=404)
    if data.title is not None:
        conn.execute("UPDATE cards SET title = ? WHERE id = ?", (data.title.strip(), card_id))
    if data.description is not None:
        conn.execute("UPDATE cards SET description = ? WHERE id = ?", (data.description.strip(), card_id))
    if data.column is not None and data.column in COLUMNS:
        max_pos = conn.execute("SELECT COALESCE(MAX(position), -1) FROM cards WHERE column = ?", (data.column,)).fetchone()[0]
        conn.execute("UPDATE cards SET column = ?, position = ? WHERE id = ?", (data.column, max_pos + 1, card_id))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


@app.post("/api/reorder")
async def reorder(data: ReorderRequest):
    col = data.column if data.column in COLUMNS else "backlog"
    conn = get_db()
    for i, card_id in enumerate(data.order):
        conn.execute(
            "UPDATE cards SET column = ?, position = ? WHERE id = ?",
            (col, i, card_id),
        )
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: str):
    conn = get_db()
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})
