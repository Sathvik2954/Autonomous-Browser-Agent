"""
Tests run_agent_task's action-handling logic with a fake BrowserController and
a scripted fake AIPlanner -- no real Playwright/Ollama needed. Focused on the
defensive fixes made after real, observed failures:

- A navigate action with no/empty "url" (a valid action name, but missing the
  field that makes it work) should never reach browser.navigate() at all, and
  should count as a failure like any other bad action.
- Every action type needs to consistently hit the same termination check when
  it fails repeatedly -- a couple of branches used to `continue` straight past
  it, so a model that kept failing the same way would run all the way to
  max_steps instead of stopping after max_errors like every other failure
  mode does.
- scroll/wait used to have no try/except at all, unlike every other action --
  an exception there (or a non-numeric "seconds") used to kill the whole task
  instead of just failing that one step.

Uses the real database (like tests/test_resume.py) with a unique task_id per
test, since executor.py's DB calls aren't mocked -- only the browser and
planner are.
"""
import uuid

import pytest

import app.executor.executor as executor_module
from app.database import init_db, create_task, get_task, get_logs


def _new_task_id() -> str:
    return f"task_test_executor_{uuid.uuid4().hex[:8]}"


class _FakeBrowserController:
    """Records every call instead of driving a real browser. navigate()
    raises if ever given an empty/blank URL -- mirroring Playwright's real
    "Cannot navigate to invalid URL" -- so a regression that removed
    executor.py's own guard would still be caught by this fake rejecting the
    call, not just by the guard silently working."""

    instances = []

    def __init__(self, task_id, record_video=True, headless=None):
        self.task_id = task_id
        self.navigate_calls = []
        self.scroll_calls = []
        self.wait_calls = []
        self.scroll_should_fail = False
        _FakeBrowserController.instances.append(self)

    async def start(self):
        return object()

    async def stop(self):
        return None

    async def navigate(self, url):
        self.navigate_calls.append(url)
        if not url or not url.strip():
            raise Exception("Cannot navigate to invalid URL")

    async def get_url(self):
        return "https://example.com"

    async def get_title(self):
        return "Example"

    async def take_screenshot(self, name=None):
        return ""

    async def click(self, selector):
        pass

    async def type_text(self, selector, text, press_enter=False):
        pass

    async def scroll(self, direction="down", amount=500):
        self.scroll_calls.append(direction)
        if self.scroll_should_fail:
            raise Exception("scroll evaluate() failed")

    async def wait(self, seconds):
        self.wait_calls.append(seconds)


class _FakePlanner:
    """Returns a scripted sequence of decisions, then "complete" once the
    script runs out -- so a test doesn't need to predict exactly how many
    steps it takes to hit max_errors, it just needs enough bad decisions
    queued up."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def plan_next_step(self, **kwargs):
        self.calls += 1
        if self._decisions:
            return self._decisions.pop(0)
        return {"thought": "done", "action": {"name": "complete", "summary": "done"}}


@pytest.fixture(autouse=True)
def _patch_executor_dependencies(monkeypatch):
    """Shared across every test in this file: no real browser, no real
    element extraction (a fake page has no real DOM to query)."""
    monkeypatch.setattr(executor_module, "BrowserController", _FakeBrowserController)

    async def fake_extract_interactive_elements(page):
        return []

    monkeypatch.setattr(executor_module, "extract_interactive_elements", fake_extract_interactive_elements)
    monkeypatch.setattr(executor_module, "generate_page_map", lambda elements: "No interactive elements found on the page.")


def _install_planner(monkeypatch, decisions):
    planner = _FakePlanner(decisions)
    monkeypatch.setattr(executor_module, "AIPlanner", lambda: planner)
    return planner


@pytest.mark.asyncio
async def test_navigate_with_missing_url_never_reaches_browser(monkeypatch):
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "go somewhere")

    _install_planner(monkeypatch, [
        {"thought": "no url", "action": {"name": "navigate"}},
        {"thought": "no url again", "action": {"name": "navigate", "url": ""}},
        {"thought": "still no url", "action": {"name": "navigate", "url": "   "}},
    ])

    before = len(_FakeBrowserController.instances)
    await executor_module.run_agent_task(task_id, "go somewhere")
    fake_browser = _FakeBrowserController.instances[before]

    task = get_task(task_id)
    assert task["status"] == "failed"
    assert "3 consecutive failures" in task["error"]

    # The only real navigate() call should be the hardcoded startup
    # navigation to google.com -- never an empty/blank url from the model.
    assert fake_browser.navigate_calls == ["https://www.google.com"]


@pytest.mark.asyncio
async def test_element_not_found_actually_terminates_after_max_errors(monkeypatch):
    """Regression test for the bug where this branch used `continue` and
    skipped the centralized termination check entirely -- a model that kept
    citing a nonexistent element_id would never stop early."""
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "click something")

    planner = _install_planner(monkeypatch, [
        {"thought": "click", "action": {"name": "click", "element_id": "button-99"}},
        {"thought": "click", "action": {"name": "click", "element_id": "button-99"}},
        {"thought": "click", "action": {"name": "click", "element_id": "button-99"}},
        {"thought": "click", "action": {"name": "click", "element_id": "button-99"}},
        {"thought": "click", "action": {"name": "click", "element_id": "button-99"}},
    ])

    await executor_module.run_agent_task(task_id, "click something")

    task = get_task(task_id)
    assert task["status"] == "failed"
    assert "3 consecutive failures" in task["error"]
    # Terminated after 3 failures, not after all 5 scripted decisions were
    # exhausted (which would mean it ran to max_steps instead).
    assert planner.calls <= 4


@pytest.mark.asyncio
async def test_scroll_exception_fails_the_step_not_the_whole_task(monkeypatch):
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "scroll around")

    _install_planner(monkeypatch, [
        {"thought": "scroll", "action": {"name": "scroll", "direction": "down"}},
    ])

    # run_agent_task should complete normally (not raise) even though the
    # fake browser's scroll() is about to fail -- this is exactly what the
    # missing try/except used to get wrong.
    original_init = _FakeBrowserController.__init__

    def init_with_failing_scroll(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.scroll_should_fail = True

    monkeypatch.setattr(_FakeBrowserController, "__init__", init_with_failing_scroll)

    await executor_module.run_agent_task(task_id, "scroll around")

    task = get_task(task_id)
    # One failed scroll isn't 3 consecutive failures -- the task should still
    # be running out the rest of its scripted plan (which just repeats
    # "complete" once the queue is empty), not crashed or stuck.
    assert task["status"] in ("completed", "failed")
    logs = get_logs(task_id)
    assert any("Scroll failed" in log["message"] for log in logs)


@pytest.mark.asyncio
async def test_repeated_empty_extract_terminates_early_instead_of_running_to_max_steps(monkeypatch):
    """Regression test for the real bug seen in practice: a model landing on
    Google's homepage with nothing useful to click/type into defaults to
    {"name": "extract"} with no "data", over and over. executor.py used to
    treat every extract call as an unconditional success (reset error_count,
    continue) regardless of whether it actually recorded anything, so this
    ran all the way to max_steps (20) instead of stopping early with a
    meaningful diagnostic."""
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "find a cheap laptop")

    planner = _install_planner(monkeypatch, [
        {"thought": "Action", "action": {"name": "extract", "data": {}}}
        for _ in range(10)
    ])

    await executor_module.run_agent_task(task_id, "find a cheap laptop")

    task = get_task(task_id)
    assert task["status"] == "failed"
    assert "no real progress" in task["error"]
    # Terminated after 5 consecutive no-op extracts, not after all 10
    # scripted decisions were exhausted.
    assert planner.calls <= 6


@pytest.mark.asyncio
async def test_extract_with_real_data_does_not_count_as_stagnant(monkeypatch):
    """A model that alternates between a real extract and something else
    should never trip the no-progress termination -- only an *empty* extract
    is a no-op."""
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "find a cheap laptop")

    _install_planner(monkeypatch, [
        {"thought": "found it", "action": {"name": "extract", "data": {"price": "$499"}}}
        for _ in range(6)
    ])

    await executor_module.run_agent_task(task_id, "find a cheap laptop")

    task = get_task(task_id)
    # Should run out its scripted plan and hit the fake planner's "complete"
    # fallback, not the stagnation termination.
    assert task["status"] == "completed"


@pytest.mark.asyncio
async def test_wait_with_non_numeric_seconds_does_not_crash_task(monkeypatch):
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "wait a bit")

    _install_planner(monkeypatch, [
        {"thought": "wait", "action": {"name": "wait", "seconds": "a few"}},
    ])

    await executor_module.run_agent_task(task_id, "wait a bit")

    task = get_task(task_id)
    # Completes via the fake planner's "complete" fallback after the one bad
    # wait -- proves the float("a few") ValueError was caught, not left to
    # propagate and kill the task via the outer try/except.
    assert task["status"] == "completed"
    logs = get_logs(task_id)
    assert any("invalid 'seconds' value" in log["message"] for log in logs)
