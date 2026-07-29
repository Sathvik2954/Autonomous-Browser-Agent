import os
import uuid
import logging
import sys
import asyncio
import threading
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.database import (
    create_task,
    get_task,
    get_all_tasks,
    update_task_status,
    get_actions,
    get_logs,
    get_extracted_data
)
from app.executor.executor import run_agent_task
from app.dispatcher import classify_task
from app.organizer.task_runner import run_organizer_task
from app.reports.report import generate_markdown_report, export_data_csv, export_data_json
from app.config import SCREENSHOTS_DIR, SESSIONS_DIR, REPORTS_DIR

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

class TaskRequest(BaseModel):
    prompt: str
    provider: str = None
    headless: bool = None

class TaskResponse(BaseModel):
    task_id: str
    prompt: str
    status: str

def run_agent_task_in_thread(task_id: str, prompt: str, provider: str = None, headless: bool = None, resume_context: dict = None):
    """Target function for background thread. Sets up Proactor loop on Windows."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_agent_task(task_id, prompt, provider=provider, headless=headless, resume_context=resume_context))
    except Exception as e:
        # run_agent_task already has its own broad try/except that marks the
        # task failed on basically any error -- this is a last-resort net for
        # something going wrong outside that (e.g. in its own finally block,
        # or event-loop setup above). Without this, an exception here is a
        # background thread dying silently: nothing prints anywhere the user
        # would see, and the task's DB row is stuck on "running" forever,
        # since update_task_status("failed", ...) never gets called.
        logger.error(f"Unhandled error running task {task_id}: {e}", exc_info=True)
        try:
            update_task_status(task_id, "failed", error=f"Unhandled error: {e}")
        except Exception:
            pass
    finally:
        loop.close()

@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def start_task(request: TaskRequest):
    """Starts a new task in the background, routed to either the browser
    agent or the document organizer based on what the prompt is asking for."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    task_id = f"task_{uuid.uuid4().hex[:8]}"

    create_task(task_id, request.prompt)

    task_kind = classify_task(request.prompt)

    if task_kind == "organizer":
        # Organizer work is synchronous local file I/O -- run it directly in
        # the background thread, no event loop needed.
        thread = threading.Thread(
            target=run_organizer_task,
            args=(task_id, request.prompt),
            daemon=True
        )
    else:
        thread = threading.Thread(
            target=run_agent_task_in_thread,
            args=(task_id, request.prompt, request.provider, request.headless),
            daemon=True
        )

    thread.start()

    return TaskResponse(task_id=task_id, prompt=request.prompt, status="running")

@router.get("/tasks")
async def list_tasks():
    """Returns a list of all historical tasks."""
    return get_all_tasks()

@router.get("/tasks/{task_id}")
async def get_task_details(task_id: str):
    """Retrieves full details, timeline actions, logs, and data for a task."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    actions = get_actions(task_id)
    logs = get_logs(task_id)
    extracted_data = get_extracted_data(task_id)
    
    # Check if a video recording is available
    video_exists = False
    video_path = SESSIONS_DIR / task_id / "recording.webm"
    if video_path.exists():
        video_exists = True
        
    # Get latest screenshot URL path if available
    latest_screenshot = None
    if actions:
        # Find latest action with a screenshot
        for a in reversed(actions):
            if a.get("screenshot_path") and os.path.exists(a["screenshot_path"]):
                # Convert absolute path to dynamic API screenshot url
                latest_screenshot = f"/api/tasks/{task_id}/screenshot?step={a['step']}"
                break
                
    return {
        "task": task,
        "actions": actions,
        "logs": logs,
        "extracted_data": extracted_data,
        "video_exists": video_exists,
        "latest_screenshot": latest_screenshot,
    }

@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Signals a running task to stop execution."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task["status"] == "running":
        update_task_status(task_id, "stopped", result_summary="Stopped by user.")
        return {"message": "Stop signal sent successfully."}
    else:
        return {"message": f"Task is not running (current status: {task['status']})"}

@router.post("/tasks/{task_id}/resume", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def resume_task(task_id: str):
    """Starts a new task that continues a previous (stopped/failed/completed)
    one -- same objective, but a browser task picks up from the last known
    URL instead of restarting at google.com, and the planner is given the
    prior run's action history for context. Organizer tasks are simply
    re-run: rescanning a folder is idempotent, since already-renamed files
    no longer look generically-named and are skipped automatically."""
    original = get_task(task_id)
    if not original:
        raise HTTPException(status_code=404, detail="Task not found")

    prior_actions = get_actions(task_id)
    new_task_id = f"task_{uuid.uuid4().hex[:8]}"
    create_task(new_task_id, original["prompt"])

    if classify_task(original["prompt"]) == "organizer":
        thread = threading.Thread(
            target=run_organizer_task,
            args=(new_task_id, original["prompt"]),
            daemon=True
        )
    else:
        last_url = None
        for a in reversed(prior_actions):
            if a.get("url"):
                last_url = a["url"]
                break

        resume_context = {
            "source_task_id": task_id,
            "last_url": last_url,
            "prior_actions": prior_actions,
        }
        thread = threading.Thread(
            target=run_agent_task_in_thread,
            args=(new_task_id, original["prompt"], None, None, resume_context),
            daemon=True
        )

    thread.start()

    return TaskResponse(task_id=new_task_id, prompt=original["prompt"], status="running")

@router.get("/tasks/{task_id}/screenshot")
async def get_screenshot(task_id: str, step: int = None):
    """Streams a screenshot for a given task and execution step."""
    actions = get_actions(task_id)
    if not actions:
        raise HTTPException(status_code=404, detail="No actions found for this task")
        
    target_action = None
    if step is not None:
        target_action = next((a for a in actions if a["step"] == step), None)
    else:
        # Get latest action that has a screenshot
        for a in reversed(actions):
            if a.get("screenshot_path"):
                target_action = a
                break
                
    if not target_action or not target_action.get("screenshot_path"):
        raise HTTPException(status_code=404, detail="Screenshot not found for this step")
        
    path = Path(target_action["screenshot_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file does not exist")
        
    return FileResponse(str(path), media_type="image/png")

@router.get("/tasks/{task_id}/video")
async def get_video(task_id: str):
    """Streams the screen recording webm file if present."""
    video_path = SESSIONS_DIR / task_id / "recording.webm"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video recording not found")
    return FileResponse(str(video_path), media_type="video/webm")

@router.get("/tasks/{task_id}/report")
async def get_report(task_id: str):
    """Generates and returns the markdown report content."""
    report_path_str = generate_markdown_report(task_id)
    if not report_path_str:
        raise HTTPException(status_code=404, detail="Failed to generate report")
        
    path = Path(report_path_str)
    if not path.exists():
         raise HTTPException(status_code=404, detail="Report file not found")
         
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        
    return {"content": content, "filename": path.name}

@router.get("/tasks/{task_id}/export/{format}")
async def export_data(task_id: str, format: str):
    """Exports and downloads task extracted data in CSV or JSON format."""
    format = format.lower()
    if format == "csv":
        file_path_str = export_data_csv(task_id)
        media = "text/csv"
    elif format == "json":
        file_path_str = export_data_json(task_id)
        media = "application/json"
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Use 'csv' or 'json'")
        
    if not file_path_str:
        raise HTTPException(status_code=404, detail="No extracted data found to export")
        
    path = Path(file_path_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file could not be generated")
        
    return FileResponse(str(path), media_type=media, filename=path.name)
