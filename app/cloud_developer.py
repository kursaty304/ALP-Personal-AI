
import os
import json
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/developer", tags=["ALP Cloud Developer"])

DB_PATH = os.environ.get("ALP_DEVELOPER_DB", "/tmp/alp_developer.db")
ADMIN_TOKEN = os.environ.get("ALP_ADMIN_TOKEN", "")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return con

def authorize(token):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Admin-Zugang noch nicht konfiguriert")
    if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(401, "Nicht autorisiert")

class TaskInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=4000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")

@router.get("/status")
def developer_status():
    return {
        "service": "ALP Cloud Developer",
        "version": "1.0",
        "mode": "approval_required",
        "code_execution_enabled": False,
        "deployment_enabled": False,
        "real_trading_enabled": False,
        "admin_configured": bool(ADMIN_TOKEN)
    }

@router.post("/tasks")
def create_task(task: TaskInput, authorization: str = Header(default="")):
    authorize(authorization.removeprefix("Bearer ").strip())
    con = db()
    cur = con.execute(
        "INSERT INTO tasks(title,description,priority,status,created_at) VALUES(?,?,?,?,?)",
        (task.title, task.description, task.priority, "pending",
         datetime.now(timezone.utc).isoformat())
    )
    con.commit()
    task_id = cur.lastrowid
    con.close()
    return {"id": task_id, "status": "pending", "approval_required": True}

@router.get("/tasks")
def list_tasks(authorization: str = Header(default="")):
    authorize(authorization.removeprefix("Bearer ").strip())
    con = db()
    rows = con.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    con.close()
    return {"tasks": [dict(row) for row in rows]}

@router.post("/tasks/{task_id}/approve")
def approve_task(task_id: int, authorization: str = Header(default="")):
    authorize(authorization.removeprefix("Bearer ").strip())
    con = db()
    cur = con.execute(
        "UPDATE tasks SET status='approved' WHERE id=? AND status='pending'",
        (task_id,)
    )
    con.commit()
    con.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Offener Auftrag nicht gefunden")
    return {"id": task_id, "status": "approved",
            "message": "Freigegeben. Noch keine Codeausführung."}
