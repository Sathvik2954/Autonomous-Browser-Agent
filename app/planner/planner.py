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
            http_client=httpx.Client(trust_env=False),
        )

    def _call_model(self, model_name: str, messages: list) -> dict:
        """Calls one model and returns a parsed {"thought", "action"} dict.
        Raises on any failure (connection, malformed JSON that survives
        repair, missing keys) -- the caller decides what to do next."""
        response = self.client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
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

        return decision

    def plan_next_step(self, objective: str, current_url: str, page_title: str, page_map: str, history: list) -> dict:
        """Determines the next action to perform. Tries `self.model` first,
        then falls through `self.fallback_models` in order if a model fails
        to respond or keeps returning unusable output -- e.g. a Gemma model
        pulled locally as a second opinion when the primary model is
        struggling. Only after every model in the chain has failed does this
        return a safe 'wait' action instead of crashing the task loop."""
        history_lines = []
        for step in history:
            history_lines.append(f"Step {step['step']}: Action: {step['action_type']} | Details: {step['description']}")
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
            logger.info(f"Planning next step with local model '{model_name}' at {self.base_url}.")
            try:
                return self._call_model(model_name, messages)
            except Exception as e:
                last_error = e
                logger.error(f"Error calling local model '{model_name}' at {self.base_url}: {e}")

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
