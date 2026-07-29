"""
LLM-driven step planner -- restored after a brief detour through a fully
rule-based workflow engine (see app/workflows/ and app/engine/, still in the
repo but no longer the primary path). That approach could only run tasks that
matched a pre-built template; this restores genuine "any task" handling by
asking a model to decide the next action at each step, the way the original
version of this project did.

The difference from the original: this talks to a LOCAL model served by Ollama
(http://localhost:11434/v1 by default) via its OpenAI-compatible API, instead
of a cloud provider (Gemini/Groq/Mistral). No API key, no per-call cost,
nothing leaves your machine -- same idea as AgenticSeek's local-provider setup.
Ollama needs to actually be running with a model pulled; see the setup
instructions that go with this change.
"""
import json
import re
import logging
import httpx
from openai import OpenAI
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_FALLBACK_MODELS

logger = logging.getLogger(__name__)

# How many of the most recent action-history entries to include in the
# prompt. Full history grows every step (browser start, each navigate/click/
# search/extract...), and an unbounded prompt is a big part of why a small
# local model's output quality falls off a cliff a few steps into a task --
# the tail of a long task is also where "recent" matters most for deciding
# what to do next, so trimming to the tail loses little.
MAX_HISTORY_STEPS = 10

# How long a single history entry's description can be before truncation.
# web_search results in particular can dump several lines of title/url/
# snippet per result into one "description", which compounds fast across
# multiple search steps.
MAX_HISTORY_ENTRY_CHARS = 300

SYSTEM_PROMPT = """
You are an autonomous browser agent. Your goal is to achieve the user's objective by executing actions on a web browser step-by-step.
At each step, you will be given:
1. The user's main objective.
2. The current URL and page title.
3. A list of interactive elements found on the current page, each tagged with an ID (e.g. [button-1], [input-3]).
4. A chronological history of actions you have executed so far.

Based on this information, you must decide the next logical action.

Allowed Actions:
1. {"name": "web_search", "query": "search terms"} - Search the web directly and get back a list of results (title, url, snippet). Prefer this over navigating to a search engine's website when you need to find information or a URL to visit -- it's faster and more reliable than clicking through a search engine's page.
2. {"name": "navigate", "url": "https://example.com"} - Navigate directly to a specific website (e.g. a URL you got from a web_search result, or one you already know).
3. {"name": "click", "element_id": "button-1"} - Click a visible button, link, or input. Use the tag ID provided in brackets.
4. {"name": "type", "element_id": "input-2", "text": "my search text", "press_enter": true} - Fill text into an input field. Set `press_enter` to true if you want to submit right away.
5. {"name": "scroll", "direction": "down"} - Scroll "down" or "up" on the current page to reveal more content.
6. {"name": "wait", "seconds": 3} - Pause execution for a few seconds. Useful if a page is loading or processing dynamic requests.
7. {"name": "extract", "data": {"key": "value", ...}} - Record structured data you've found on the page (e.g. prices, facts, summaries). Call this whenever you see information relevant to the objective.
8. {"name": "complete", "summary": "Detailed summary of findings..."} - Call this when you have successfully completed the user's objective and have extracted the required information. Include the findings directly in the summary.

Formatting Rules:
- You MUST output your response as a valid JSON object. Do not include any other conversational text outside the JSON.
- The JSON object must contain exactly two keys:
  1. "thought": A brief, clear explanation of your reasoning (what you see, what your goal is, and why you are taking the next action).
  2. "action": The action object from the allowed actions above.

Example Response:
{
  "thought": "I need to search for flight tickets, so I will type the destination into the search bar.",
  "action": {
    "name": "type",
    "element_id": "input-1",
    "text": "London",
    "press_enter": true
  }
}
"""


def clean_json_string(response_text: str) -> str:
    """Extracts the first JSON block from a response string. Local models are
    more prone than hosted ones to wrapping JSON in ```json fences or adding
    stray commentary despite the system prompt's instructions, so this has to
    be more forgiving than 'just json.loads() it'."""
    response_text = response_text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if match:
        return match.group(1)

    start = response_text.find('{')
    end = response_text.rfind('}')
    if start != -1 and end != -1:
        return response_text[start:end + 1]

    return response_text


# Every action name the executor actually knows how to handle (see the
# if/elif chain in app/executor/executor.py). Kept as one list so the
# schema's enum and the prompt's allowed-actions description can't drift
# apart from what the executor really supports.
ALLOWED_ACTION_NAMES = [
    "web_search", "navigate", "click", "type", "scroll", "wait", "extract", "complete",
]

# Fields each action type needs to actually be executable -- constraining
# action.name to the enum above stops a model from inventing a whole new
# action, but doesn't stop it picking a real one and leaving out the field
# that makes it work (seen in practice: {"name": "navigate"} with no "url"
# at all, which executor.py happily tried anyway and got
# "Cannot navigate to invalid URL" three times in a row until the task gave
# up). Only the fields that are genuinely required to do anything meaningful
# are listed -- e.g. scroll/wait/extract/complete all have sensible defaults
# for every field in executor.py, so they're intentionally not listed here.
REQUIRED_ACTION_FIELDS = {
    "web_search": ["query"],
    "navigate": ["url"],
    "click": ["element_id"],
    "type": ["element_id", "text"],
}

# A loose response_format={"type": "json_object"} only constrains the model
# to emit *some* valid JSON -- it says nothing about which keys to use, so a
# small model is free to (and in practice often does) return syntactically
# valid JSON with entirely made-up keys instead of "thought"/"action". This
# schema is used with response_format={"type": "json_schema", ...} instead,
# which -- where the server supports it -- constrains generation at the
# grammar level to actually contain these keys, not just hope the model
# follows the prompt's instructions.
#
# action.name is constrained to the exact enum of actions the executor
# understands -- without this, a schema that only requires "name" to be
# *a* string still lets the model write an entire sentence into it (seen in
# practice: "navigating across browsers and devices navigation methods -- a
# brief overview of..." instead of "navigate"), which executor.py correctly
# rejects as an unknown action and does nothing with. The rest of "action"
# is deliberately left loose beyond that, since its shape varies by which
# action was picked (see the allowed-actions list in SYSTEM_PROMPT).
DECISION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": ALLOWED_ACTION_NAMES}},
            "required": ["name"],
        },
    },
    "required": ["thought", "action"],
}


def repair_json_string(text: str) -> str:
    """Best-effort fix for the two malformed-JSON patterns small local models
    produce most often:

    1. A raw newline/tab inside a string value (e.g. a multi-line "thought")
       instead of an escaped \\n -- the JSON spec requires control characters
       inside strings to be escaped, and a 3B model frequently forgets. This
       walks the text tracking whether we're inside a string literal
       (honoring backslash escapes) and only escapes control characters when
       inside one, so structural whitespace between tokens is left alone.
    2. A trailing comma before a closing } or ].

    This is a heuristic, not a real JSON parser -- it won't fix every
    malformed response (e.g. an unescaped stray quote inside a string is
    ambiguous and can't be reliably repaired), but it covers the common
    cases cheaply with no extra model round-trip."""
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == '\\':
                out.append(ch)
                escaped = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '\t':
                out.append('\\t')
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    repaired = ''.join(out)
    return re.sub(r',\s*([}\]])', r'\1', repaired)


class AIPlanner:
    def __init__(self, base_url: str = None, model: str = None, fallback_models: list = None):
        self.base_url = base_url or OLLAMA_BASE_URL
        self.model = model or OLLAMA_MODEL
        # Extra models tried, in order, through this same Ollama server if
        # `self.model` fails to respond or returns unparseable output --
        # e.g. a Gemma model as a second opinion when the primary model is
        # struggling. Off by default (see OLLAMA_FALLBACK_MODELS in config.py);
        # each has to already be pulled locally, same as the primary model.
        self.fallback_models = fallback_models if fallback_models is not None else OLLAMA_FALLBACK_MODELS
        # Ollama's OpenAI-compatible endpoint ignores the API key entirely,
        # but the client library requires *something* non-empty to be passed.
        #
        # trust_env=False is deliberate: this always talks to a local/user-
        # configured endpoint, never a third party, so system proxy env vars
        # (HTTP_PROXY/ALL_PROXY -- common behind a corporate VPN) should never
        # apply here. Without this, some environments fail to even construct
        # the client (httpx eagerly inspects proxy env vars and can raise an
        # ImportError over a missing optional SOCKS dependency) before ever
        # attempting to reach Ollama.
        self.client = OpenAI(
            base_url=self.base_url,
            api_key="ollama",
            http_client=httpx.Client(trust_env=False, timeout=30.0),
        )
        # Whether this Ollama server accepts JSON-Schema-constrained output
        # (response_format={"type": "json_schema", ...}). Unknown (None)
        # until the first call; if the server rejects that request shape,
        # this is set to False and every call for the rest of this planner's
        # lifetime uses the looser json_object mode instead of re-probing
        # (and re-failing) on every single step.
        self._json_schema_supported = None

    def _response_format(self, use_schema: bool) -> dict:
        if use_schema:
            return {
                "type": "json_schema",
                "json_schema": {"name": "browser_agent_decision", "schema": DECISION_JSON_SCHEMA},
            }
        return {"type": "json_object"}

    def _create_completion(self, model_name: str, messages: list):
        """Calls the chat completion endpoint. Only this method, not JSON
        parsing/validation below, decides whether schema-constrained output
        is usable -- a schema-format request gets rejected immediately by
        the server (an API-level error) before generation even starts, which
        is a different failure than the model generating badly-shaped JSON
        despite the schema being accepted. Conflating the two would wrongly
        write off schema support over a content problem, not a format one."""
        use_schema = self._json_schema_supported is not False
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format=self._response_format(use_schema),
                temperature=0.2,
            )
            if use_schema and self._json_schema_supported is None:
                self._json_schema_supported = True
            return response
        except Exception as e:
            if not use_schema:
                raise
            logger.warning(
                f"'{model_name}' rejected JSON-schema-constrained output ({e}); "
                "falling back to looser json_object mode for the rest of this task."
            )
            self._json_schema_supported = False
            return self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format=self._response_format(False),
                temperature=0.2,
            )

    def _call_model(self, model_name: str, messages: list) -> dict:
        """Calls one model and returns a parsed {"thought", "action"} dict.
        Raises on any failure (connection, malformed JSON that survives
        repair, missing keys) -- the caller decides what to do next."""
        response = self._create_completion(model_name, messages)
        response_text = response.choices[0].message.content

        cleaned_json = clean_json_string(response_text)
        try:
            decision = json.loads(cleaned_json)
        except json.JSONDecodeError:
            # Small local models occasionally emit syntactically invalid
            # JSON -- most often a raw newline inside the "thought" string,
            # or a trailing comma. Try a heuristic repair before giving up.
            try:
                decision = json.loads(repair_json_string(cleaned_json))
            except json.JSONDecodeError:
                logger.error(f"Raw response from '{model_name}' that failed to parse: {response_text!r}")
                raise

        if "thought" not in decision or "action" not in decision:
            raise ValueError(f"Response JSON from '{model_name}' is missing 'thought' or 'action' key.")

        # The json_schema enum only gets enforced when the server actually
        # honors schema-constrained output (see _create_completion) -- the
        # json_object fallback mode has no such constraint, so a model can
        # still put anything at all in action.name there (seen in practice:
        # a full sentence instead of "navigate"). Check it here too so that
        # case also triggers the corrective retry below instead of silently
        # reaching executor.py's "Unknown action proposed" dead end.
        action_obj = decision.get("action") or {}
        action_name = action_obj.get("name")
        if action_name not in ALLOWED_ACTION_NAMES:
            raise ValueError(
                f"Response JSON from '{model_name}' has an unrecognized action.name: {action_name!r}. "
                f"Must be one of: {ALLOWED_ACTION_NAMES}."
            )

        # A valid action *name* doesn't mean the action is actually usable --
        # see REQUIRED_ACTION_FIELDS above. Treat an empty/whitespace value
        # the same as a missing key: {"url": ""} is exactly as unusable as no
        # "url" at all, and is what actually showed up in practice.
        missing = [
            field for field in REQUIRED_ACTION_FIELDS.get(action_name, [])
            if not str(action_obj.get(field, "")).strip()
        ]
        if missing:
            raise ValueError(
                f"Response JSON from '{model_name}' has action.name={action_name!r} but is missing "
                f"required field(s): {missing}."
            )

        return decision

    def plan_next_step(self, objective: str, current_url: str, page_title: str, page_map: str, history: list) -> dict:
        """Determines the next action to perform. Tries `self.model` first,
        then falls through `self.fallback_models` in order if a model fails
        to respond or keeps returning unusable output -- e.g. a Gemma model
        pulled locally as a second opinion when the primary model is
        struggling. Only after every model in the chain has failed does this
        return a safe 'wait' action instead of crashing the task loop."""
        recent_history = history[-MAX_HISTORY_STEPS:]
        omitted = len(history) - len(recent_history)

        history_lines = []
        if omitted > 0:
            history_lines.append(f"[{omitted} earlier step(s) omitted for brevity]")
        for step in recent_history:
            description = step['description'] or ""
            if len(description) > MAX_HISTORY_ENTRY_CHARS:
                description = description[:MAX_HISTORY_ENTRY_CHARS] + "... [truncated]"
            history_lines.append(f"Step {step['step']}: Action: {step['action_type']} | Details: {description}")
        history_text = "\n".join(history_lines) if history_lines else "None yet."

        prompt = f"""
USER OBJECTIVE: {objective}

CURRENT PAGE DETAILS:
URL: {current_url}
Title: {page_title}

INTERACTIVE ELEMENTS ON THIS PAGE:
{page_map}

ACTION HISTORY:
{history_text}

Provide the next thought and action in JSON format.
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        models_to_try = [self.model] + self.fallback_models
        last_error = None

        for model_name in models_to_try:
            current_messages = messages
            # Two attempts per model: the original prompt, then -- if that
            # came back as valid-but-wrong-shape JSON (the dominant failure
            # mode in practice: a small model returning syntactically valid
            # JSON with the wrong keys entirely) -- one corrective retry that
            # shows the model exactly what was wrong before giving up on it
            # and moving to the next model in the chain.
            for attempt in range(2):
                retry_note = " (retry after invalid response)" if attempt else ""
                logger.info(f"Planning next step with local model '{model_name}' at {self.base_url}{retry_note}.")
                try:
                    return self._call_model(model_name, current_messages)
                except Exception as e:
                    last_error = e
                    logger.error(f"Error calling local model '{model_name}' at {self.base_url}: {e}")
                    if attempt == 0:
                        current_messages = messages + [{
                            "role": "user",
                            "content": (
                                f"Your last response was invalid: {e}. Reply again with ONLY a single "
                                "valid JSON object containing exactly two keys, \"thought\" and \"action\", "
                                "matching the schema and example shown in the system prompt. No other text."
                            ),
                        }]

        tried = "', '".join(models_to_try)
        return {
            "thought": (
                f"An error occurred while calling the local model: {last_error}. "
                f"Is Ollama running (`ollama serve`) with '{tried}' pulled? I will wait and retry."
            ),
            "action": {
                "name": "wait",
                "seconds": 5,
            },
        }
