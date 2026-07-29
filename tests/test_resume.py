"""
Tests the /tasks/{id}/resume endpoint's routing and context-building logic.

Neither Playwright nor Ollama are available in this environment, so these
tests replace threading.Thread with a fake that captures what *would* have
been launched in the background instead of actually running it -- this
verifies the endpoint builds the right resume_context (or routes organizer
tasks correctly) without needing a real browser or local model.

Browser tasks (open a site, search, click around, summarize) are disabled
entirely -- see BROWSER_TASKS_DISABLED_MESSAGE in app/api/routes.py -- so
both /api/tasks and /api/tasks/{id}/resume now reject anything the
dispatcher doesn't classify as "organizer" with a 400, rather than actually
starting run_agent_task_in_thread.
"""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes as routes_module
from app.api.routes import router
from app.database import init_db, create_task, add_action


class _FakeThread:
    """Captures the target/args a background thread would have run instead
    of actually starting one."""
    last_call = None

    def __init__(self, target=None, args=(), daemon=None):
        _FakeThread.last_call = {"target": target, "args": args}

    def start(self):
        pass


def _client(monkeypatch):
    monkeypatch.setattr(routes_module.threading, "Thread", _FakeThread)
    app = FastAPI()
    app.include_router(router)
    init_db()
    return TestClient(app)


def _new_task_id() -> str:
    return f"task_test_resume_{uuid.uuid4().hex[:8]}"


def test_resume_returns_404_for_unknown_task(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/api/tasks/task_does_not_exist_at_all/resume")
    assert resp.status_code == 404


def test_resume_rejects_browser_task(monkeypatch):
    """Browser tasks are disabled entirely (see BROWSER_TASKS_DISABLED_MESSAGE
    in routes.py) -- resuming an old one shouldn't actually start
    run_agent_task_in_thread, it should reject with a clear 400 same as a
    fresh attempt to create one would."""
    client = _client(monkeypatch)
    source_id = _new_task_id()
    create_task(source_id, "search for flights to Goa")
    add_action(source_id, step=1, action_type="navigate",
               description="Navigated to duckduckgo", url="https://duckduckgo.com/?q=flights")
    add_action(source_id, step=2, action_type="click",
               description="Clicked result", url="https://example-airline.com/flights")

    _FakeThread.last_call = None  # class attribute persists across tests -- reset before asserting on it
    resp = client.post(f"/api/tasks/{source_id}/resume")
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"]
    assert _FakeThread.last_call is None


def test_resume_routes_organizer_task_without_resume_context(monkeypatch):
    client = _client(monkeypatch)
    source_id = _new_task_id()
    create_task(source_id, "rename the doc1 files in Downloads")

    resp = client.post(f"/api/tasks/{source_id}/resume")
    assert resp.status_code == 201

    call = _FakeThread.last_call
    assert call["target"] is routes_module.run_organizer_task
    new_task_id, prompt = call["args"]
    assert prompt == "rename the doc1 files in Downloads"


def test_start_task_rejects_browser_prompt(monkeypatch):
    """POST /api/tasks is the other entry point that used to hand a prompt
    to run_agent_task_in_thread -- same disabled-browser-task rejection
    should apply here too, before a task row is even created."""
    client = _client(monkeypatch)
    _FakeThread.last_call = None

    resp = client.post("/api/tasks", json={"prompt": "Find the cheapest laptop under 60000 rupees on Amazon."})
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"]
    assert _FakeThread.last_call is None


def test_start_task_accepts_organizer_prompt(monkeypatch):
    client = _client(monkeypatch)

    resp = client.post("/api/tasks", json={"prompt": "rename the doc1 files in Downloads"})
    assert resp.status_code == 201

    call = _FakeThread.last_call
    assert call["target"] is routes_module.run_organizer_task


def test_start_task_rejects_empty_prompt(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/api/tasks", json={"prompt": "   "})
    assert resp.status_code == 400
