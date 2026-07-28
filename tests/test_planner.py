"""
Tests what's actually testable without a running Ollama server: JSON extraction
from a model's raw text response, and that a failed/unreachable call degrades
to a safe fallback action instead of crashing the task loop. Whether a real
local model produces good *decisions* can only be judged by actually running
it (see README's Ollama setup) -- that's not something a unit test can verify.
"""
import json

import pytest

from app.planner.planner import AIPlanner, clean_json_string, repair_json_string


def test_clean_json_string_handles_plain_json():
    raw = '{"thought": "hi", "action": {"name": "wait", "seconds": 1}}'
    assert clean_json_string(raw) == raw


def test_clean_json_string_strips_markdown_fence():
    raw = '```json\n{"thought": "hi", "action": {"name": "wait", "seconds": 1}}\n```'
    cleaned = clean_json_string(raw)
    assert cleaned.startswith("{")
    assert cleaned.endswith("}")
    assert "```" not in cleaned


def test_clean_json_string_strips_surrounding_prose():
    raw = 'Sure, here is the next action:\n{"thought": "hi", "action": {"name": "wait", "seconds": 1}}\nLet me know if that works!'
    cleaned = clean_json_string(raw)
    assert cleaned == '{"thought": "hi", "action": {"name": "wait", "seconds": 1}}'


def test_planner_falls_back_gracefully_when_ollama_is_unreachable():
    """No Ollama server needed for this one -- point at a closed port and confirm
    the planner returns a safe 'wait' action instead of raising, so a task
    doesn't crash the whole loop just because the local model isn't running."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="does-not-matter")
    decision = planner.plan_next_step(
        objective="test objective",
        current_url="https://example.com",
        page_title="Example",
        page_map="[button-1] (BUTTON) text: \"Click me\"",
        history=[],
    )
    assert "thought" in decision
    assert decision["action"]["name"] == "wait"


def test_planner_uses_ollama_defaults_when_not_overridden():
    from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL
    planner = AIPlanner()
    assert planner.base_url == OLLAMA_BASE_URL
    assert planner.model == OLLAMA_MODEL


def test_repair_json_string_escapes_raw_newline_inside_string_value():
    # This is the failure mode most likely behind "Expecting ',' delimiter" --
    # a raw newline character inside a string value that json.loads rejects.
    broken = '{\n  "thought": "line one\nline two",\n  "action": {"name": "wait", "seconds": 1}\n}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)
    repaired = repair_json_string(broken)
    decision = json.loads(repaired)
    assert decision["thought"] == "line one\nline two"
    assert decision["action"]["name"] == "wait"


def test_repair_json_string_strips_trailing_comma():
    broken = '{"thought": "hi", "action": {"name": "wait", "seconds": 1,},}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)
    decision = json.loads(repair_json_string(broken))
    assert decision["action"]["seconds"] == 1


def test_repair_json_string_leaves_valid_json_unchanged_in_effect():
    valid = '{"thought": "hi", "action": {"name": "wait", "seconds": 1}}'
    assert json.loads(repair_json_string(valid)) == json.loads(valid)


def test_planner_uses_configured_fallback_models_when_not_overridden():
    # Compares against the live config value (like
    # test_planner_uses_ollama_defaults_when_not_overridden does for
    # model/base_url) rather than hardcoding [], since OLLAMA_FALLBACK_MODELS
    # is meant to be set via .env and this suite runs against the real one.
    from app.config import OLLAMA_FALLBACK_MODELS
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="does-not-matter")
    assert planner.fallback_models == OLLAMA_FALLBACK_MODELS


def test_planner_retries_same_model_once_before_moving_to_fallback(monkeypatch):
    """A model gets one corrective retry (with the error shown back to it)
    before the planner writes it off and moves to the next model in the
    chain -- this is what lets a model that returned valid-but-wrong-shape
    JSON (the dominant real-world failure) self-correct instead of always
    burning a call on a fallback model that may not help either."""
    planner = AIPlanner(
        base_url="http://127.0.0.1:1/v1",
        model="primary-model",
        fallback_models=["fallback-model"],
    )

    calls = []

    def fake_call_model(self, model_name, messages):
        calls.append(model_name)
        if model_name == "primary-model":
            raise RuntimeError("primary model is down")
        return {"thought": "answered by fallback", "action": {"name": "wait", "seconds": 1}}

    monkeypatch.setattr(AIPlanner, "_call_model", fake_call_model)

    decision = planner.plan_next_step(
        objective="test objective",
        current_url="https://example.com",
        page_title="Example",
        page_map="[button-1] (BUTTON) text: \"Click me\"",
        history=[],
    )

    # primary-model gets its original attempt + one corrective retry before
    # the planner falls through to fallback-model.
    assert calls == ["primary-model", "primary-model", "fallback-model"]
    assert decision["thought"] == "answered by fallback"


def test_planner_recovers_on_corrective_retry_without_touching_fallback(monkeypatch):
    """If the model gets it right on the corrective retry, the planner should
    stop there -- no need to burn a call on a fallback model it never needed."""
    planner = AIPlanner(
        base_url="http://127.0.0.1:1/v1",
        model="primary-model",
        fallback_models=["fallback-model"],
    )

    calls = []

    def fake_call_model(self, model_name, messages):
        calls.append(model_name)
        # Fails on the first attempt (2 messages: system + user), succeeds
        # once the corrective retry message has been appended (4 messages).
        if len(messages) <= 2:
            raise ValueError("Response JSON is missing 'thought' or 'action' key.")
        return {"thought": "corrected", "action": {"name": "wait", "seconds": 1}}

    monkeypatch.setattr(AIPlanner, "_call_model", fake_call_model)

    decision = planner.plan_next_step(
        objective="test objective",
        current_url="https://example.com",
        page_title="Example",
        page_map="[button-1] (BUTTON) text: \"Click me\"",
        history=[],
    )

    assert calls == ["primary-model", "primary-model"]
    assert decision["thought"] == "corrected"


def test_planner_trims_history_to_recent_steps(monkeypatch):
    """Full action history grows every step -- an unbounded prompt is a real
    contributor to a small local model's output degrading over the course of
    a task, so plan_next_step should only send the most recent N steps plus
    a note that older ones were omitted."""
    from app.planner.planner import MAX_HISTORY_STEPS

    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    captured = {}

    def fake_call_model(self, model_name, messages):
        captured["prompt"] = messages[-1]["content"]
        return {"thought": "ok", "action": {"name": "wait", "seconds": 1}}

    monkeypatch.setattr(AIPlanner, "_call_model", fake_call_model)

    history = [
        {"step": i, "action_type": "click", "description": f"Clicked thing {i}"}
        for i in range(MAX_HISTORY_STEPS + 5)
    ]
    planner.plan_next_step(
        objective="test objective",
        current_url="https://example.com",
        page_title="Example",
        page_map="[button-1] (BUTTON) text: \"Click me\"",
        history=history,
    )

    prompt = captured["prompt"]
    assert "5 earlier step(s) omitted for brevity" in prompt
    assert "Clicked thing 4" not in prompt  # trimmed away
    assert f"Clicked thing {MAX_HISTORY_STEPS + 4}" in prompt  # most recent kept


def test_planner_reports_every_model_tried_when_all_fail(monkeypatch):
    planner = AIPlanner(
        base_url="http://127.0.0.1:1/v1",
        model="primary-model",
        fallback_models=["fallback-model"],
    )

    def fake_call_model(self, model_name, messages):
        raise RuntimeError(f"{model_name} is down")

    monkeypatch.setattr(AIPlanner, "_call_model", fake_call_model)

    decision = planner.plan_next_step(
        objective="test objective",
        current_url="https://example.com",
        page_title="Example",
        page_map="[button-1] (BUTTON) text: \"Click me\"",
        history=[],
    )

    assert decision["action"]["name"] == "wait"
    assert "primary-model" in decision["thought"]
    assert "fallback-model" in decision["thought"]
