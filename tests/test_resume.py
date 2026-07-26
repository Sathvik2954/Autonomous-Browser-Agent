"""
Tests the /tasks/{id}/resume endpoint's routing and context-building logic.

Neither Playwright nor Ollama are available in this environment, so these
tests replace threading.Thread with a fake that captures what *would* have
been launched in the background instead of actually running it -- this
verifies the endpoint builds the right resume_context (or routes organizer
tasks correctly) without needing a real browser or local model.
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


def test_resume_routes_browser_task_with_last_url_and_history(monkeypatch):
    client = _client(monkeypatch)
    source_id = _new_task_id()
    create_task(source_id, "search for flights to Goa")
    add_action(source_id, step=1, action_type="navigate",
               description="Navigated to duckduckgo", url="https://duckduckgo.com/?q=flights")
    add_action(source_id, step=2, action_type="click",
               description="Clicked result", url="https://example-airline.com/flights")

    resp = client.post(f"/api/tasks/{source_id}/resume")
    assert resp.status_code == 201
    data = resp.json()
    assert data["task_id"] != source_id
    assert data["prompt"] == "search for flights to Goa"

    call = _FakeThread.last_call
    assert call["target"] is routes_module.run_agent_task_in_thread
    new_task_id, prompt, provider, headless, resume_context = call["args"]
    assert new_task_id == data["task_id"]
    assert prompt == "search for flights to Goa"
    assert resume_context["source_task_id"] == source_id
    # picks the most recent action that had a URL, not the first
    assert resume_context["last_url"] == "https://example-airline.com/flights"
    assert len(resume_context["prior_actions"]) == 2


def test_resume_falls_back_to_no_last_url_when_history_has_none(monkeypatch):
    client = _client(monkeypatch)
    source_id = _new_task_id()
    create_task(source_id, "search for flights to Goa")
    # a task that never got past its first log entry -- no actions recorded

    resp = client.post(f"/api/tasks/{source_id}/resume")
    assert resp.status_code == 201

    call = _FakeThread.last_call
    _, _, _, _, resume_context = call["args"]
    assert resume_context["last_url"] is None
    assert resume_context["prior_actions"] == []


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
