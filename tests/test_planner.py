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
