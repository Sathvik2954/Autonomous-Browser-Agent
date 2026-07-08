import sqlite3
import json
from datetime import datetime
from app.config import DB_PATH

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        error TEXT,
        result_summary TEXT
    )
    """)
    
    # Actions table (timeline)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        step INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        description TEXT NOT NULL,
        screenshot_path TEXT,
        url TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )
    """)
    
    # Extracted Data table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extracted_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        data_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )
    """)
    
    # Detailed logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        message TEXT NOT NULL,
        level TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()

# CRUD Helpers for Tasks
def create_task(task_id: str, prompt: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (id, prompt, status, started_at) VALUES (?, ?, ?, ?)",
        (task_id, prompt, "running", datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def update_task_status(task_id: str, status: str, error: str = None, result_summary: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    completed_at = datetime.now().isoformat() if status in ("completed", "failed", "stopped") else None
    
    if completed_at:
        cursor.execute(
            "UPDATE tasks SET status = ?, error = ?, result_summary = ?, completed_at = ? WHERE id = ?",
            (status, error, result_summary, completed_at, task_id)
        )
    else:
        cursor.execute(
            "UPDATE tasks SET status = ?, error = ?, result_summary = ? WHERE id = ?",
            (status, error, result_summary, task_id)
        )
    conn.commit()
    conn.close()

def get_task(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    conn.close()
    return dict(task) if task else None

def get_all_tasks():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY started_at DESC")
    tasks = cursor.fetchall()
    conn.close()
    return [dict(t) for t in tasks]

# CRUD Helpers for Actions
def add_action(task_id: str, step: int, action_type: str, description: str, screenshot_path: str = None, url: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO actions (task_id, step, action_type, description, screenshot_path, url, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, step, action_type, description, screenshot_path, url, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_actions(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM actions WHERE task_id = ? ORDER BY step ASC", (task_id,))
    actions = cursor.fetchall()
    conn.close()
    return [dict(a) for a in actions]

# CRUD Helpers for Extracted Data
def add_extracted_data(task_id: str, data: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO extracted_data (task_id, data_json, created_at) VALUES (?, ?, ?)",
        (task_id, json.dumps(data), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_extracted_data(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM extracted_data WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
    data = cursor.fetchall()
    conn.close()
    
    parsed_results = []
    for d in data:
        try:
            parsed_results.append(json.loads(d['data_json']))
        except Exception:
            pass
    return parsed_results

# CRUD Helpers for Logs
def add_log(task_id: str, message: str, level: str = "info"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (task_id, message, level, timestamp) VALUES (?, ?, ?, ?)",
        (task_id, message, level, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_logs(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs WHERE task_id = ? ORDER BY timestamp ASC", (task_id,))
    logs = cursor.fetchall()
    conn.close()
    return [dict(l) for l in logs]
