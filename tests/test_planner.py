"""
Tests what's actually testable without a running Ollama server: JSON extraction
from a model's raw text response, and that a failed/unreachable call degrades
to a safe fallback action instead of crashing the task loop. Whether a real
local model produces good *decisions* can only be judged by actually running
it (see README's Ollama setup) -- that's not something a unit test can verify.
"""
import json

import pytest

from app.planner.planner import (
    ALLOWED_ACTION_NAMES,
    AIPlanner,
    DECISION_JSON_SCHEMA,
    REQUIRED_ACTION_FIELDS,
    clean_json_string,
    repair_json_string,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


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


def test_create_completion_tries_json_schema_first_and_marks_it_supported():
    """A loose json_object response_format only guarantees *some* valid JSON,
    not the right keys -- json_schema constrains generation at the grammar
    level to actually contain "thought"/"action". This is what should be
    tried first, on a server that accepts it."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _FakeResponse('{"thought": "hi", "action": {"name": "wait", "seconds": 1}}')

    planner.client.chat.completions.create = fake_create

    response = planner._create_completion("primary-model", [{"role": "user", "content": "hi"}])

    assert len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert planner._json_schema_supported is True
    assert response.choices[0].message.content.startswith("{")


def test_create_completion_falls_back_to_json_object_when_schema_rejected():
    """If the server rejects the schema-typed request outright (e.g. an
    older Ollama version), retry once in the looser json_object mode rather
    than failing the whole call -- and remember not to try schema mode again
    for the rest of this planner's lifetime."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if kwargs["response_format"]["type"] == "json_schema":
            raise RuntimeError("400 Bad Request: unknown parameter 'json_schema'")
        return _FakeResponse('{"thought": "hi", "action": {"name": "wait", "seconds": 1}}')

    planner.client.chat.completions.create = fake_create

    response = planner._create_completion("primary-model", [{"role": "user", "content": "hi"}])

    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"]["type"] == "json_object"
    assert planner._json_schema_supported is False
    assert response.choices[0].message.content.startswith("{")


def test_create_completion_skips_schema_probe_once_marked_unsupported():
    """Once a call has established the server doesn't support schema mode,
    later calls shouldn't pay for a doomed schema attempt on every single
    step -- go straight to json_object."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    planner._json_schema_supported = False
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _FakeResponse('{"thought": "hi", "action": {"name": "wait", "seconds": 1}}')

    planner.client.chat.completions.create = fake_create

    planner._create_completion("primary-model", [{"role": "user", "content": "hi"}])

    assert len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_object"


def test_decision_json_schema_constrains_action_name_to_allowed_enum():
    # Guards against the schema and ALLOWED_ACTION_NAMES silently drifting
    # apart -- the enum in the schema sent to Ollama has to actually be this
    # list, not a hand-copied duplicate of it.
    assert DECISION_JSON_SCHEMA["properties"]["action"]["properties"]["name"]["enum"] == ALLOWED_ACTION_NAMES


def test_call_model_rejects_hallucinated_action_name(monkeypatch):
    """Seen in practice: with only {"type": "json_object"} (no enum
    constraint), a struggling model can put an entire rambling sentence in
    action.name instead of one of the real action names -- syntactically
    valid JSON, so it used to sail straight through to executor.py's
    'Unknown action proposed' dead end. _call_model should catch that itself
    so plan_next_step's corrective retry kicks in instead."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    def fake_create_completion(model_name, messages):
        return _FakeResponse(json.dumps({
            "thought": "rambling",
            "action": {"name": "navigating across browsers and devices -- a brief overview of..."},
        }))

    monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs: fake_create_completion(m, msgs))

    with pytest.raises(ValueError, match="unrecognized action.name"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_accepts_every_allowed_action_name(monkeypatch):
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    for name in ALLOWED_ACTION_NAMES:
        # Any action with entries in REQUIRED_ACTION_FIELDS needs those
        # fields populated too, or _call_model correctly rejects it (that's
        # exactly what the dedicated required-field tests below check) --
        # this test is only about action.name itself being accepted.
        action = {"name": name}
        for field in REQUIRED_ACTION_FIELDS.get(name, []):
            action[field] = "placeholder"
        # "extract" isn't in REQUIRED_ACTION_FIELDS (its required-ness is
        # dict-shaped, not a blank-string check -- see the dedicated
        # empty-data tests below), but it's still rejected without data.
        if name == "extract":
            action["data"] = {"placeholder": "value"}

        def fake_create_completion(model_name, messages, action=action):
            return _FakeResponse(json.dumps({"thought": "ok", "action": action}))

        monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs, fc=fake_create_completion: fc(m, msgs))
        decision = planner._call_model("primary-model", [{"role": "user", "content": "hi"}])
        assert decision["action"]["name"] == name


def test_call_model_rejects_navigate_action_with_missing_url(monkeypatch):
    """Seen in practice: a valid action.name ("navigate") with no "url" field
    at all -- structurally fine JSON, but executor.py had nothing to
    navigate to and tried browser.navigate("") three times in a row before
    giving up. This should be caught here, before it ever reaches the
    browser, and trigger the corrective retry instead."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    def fake_create_completion(model_name, messages):
        return _FakeResponse(json.dumps({"thought": "go somewhere", "action": {"name": "navigate"}}))

    monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs: fake_create_completion(m, msgs))

    with pytest.raises(ValueError, match="missing required field"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_rejects_navigate_action_with_blank_url(monkeypatch):
    """An empty-string "url" is exactly as unusable as a missing one -- both
    should be treated the same, not just a literally-absent key."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    def fake_create_completion(model_name, messages):
        return _FakeResponse(json.dumps({"thought": "go somewhere", "action": {"name": "navigate", "url": "   "}}))

    monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs: fake_create_completion(m, msgs))

    with pytest.raises(ValueError, match="missing required field"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_accepts_navigate_action_with_url_present():
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    planner._create_completion = lambda m, msgs: _FakeResponse(
        json.dumps({"thought": "go somewhere", "action": {"name": "navigate", "url": "https://example.com"}})
    )
    decision = planner._call_model("primary-model", [{"role": "user", "content": "hi"}])
    assert decision["action"]["url"] == "https://example.com"


@pytest.mark.parametrize("action_name,fields", list(REQUIRED_ACTION_FIELDS.items()))
def test_call_model_rejects_every_required_action_field_when_missing(action_name, fields):
    """Table-driven version of the navigate/url case above, covering every
    entry in REQUIRED_ACTION_FIELDS (web_search/query, click/element_id,
    type/element_id+text) so a future addition to that dict is automatically
    covered here too."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    planner._create_completion = lambda m, msgs: _FakeResponse(
        json.dumps({"thought": "doing it", "action": {"name": action_name}})
    )
    with pytest.raises(ValueError, match="missing required field"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_rejects_extract_action_with_no_data_key(monkeypatch):
    """Seen in practice: a model landing on Google's homepage with nothing
    useful to click/type into defaults to {"name": "extract"} with no "data"
    at all -- structurally valid JSON, action.name is a real action, but it
    records nothing and (before this check existed) executor.py treated it
    as an unconditional success, letting the model repeat this forever."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    def fake_create_completion(model_name, messages):
        return _FakeResponse(json.dumps({"thought": "Action", "action": {"name": "extract"}}))

    monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs: fake_create_completion(m, msgs))

    with pytest.raises(ValueError, match="'data' is empty"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_rejects_extract_action_with_empty_data_dict(monkeypatch):
    """An explicit {"data": {}} is exactly as unusable as omitting "data"
    entirely -- both should be rejected the same way."""
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")

    def fake_create_completion(model_name, messages):
        return _FakeResponse(json.dumps({"thought": "Action", "action": {"name": "extract", "data": {}}}))

    monkeypatch.setattr(AIPlanner, "_create_completion", lambda self, m, msgs: fake_create_completion(m, msgs))

    with pytest.raises(ValueError, match="'data' is empty"):
        planner._call_model("primary-model", [{"role": "user", "content": "hi"}])


def test_call_model_accepts_extract_action_with_real_data():
    planner = AIPlanner(base_url="http://127.0.0.1:1/v1", model="primary-model")
    planner._create_completion = lambda m, msgs: _FakeResponse(
        json.dumps({"thought": "found it", "action": {"name": "extract", "data": {"price": "$499"}}})
    )
    decision = planner._call_model("primary-model", [{"role": "user", "content": "hi"}])
    assert decision["action"]["data"] == {"price": "$499"}


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
