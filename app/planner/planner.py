import json
import re
import logging
from google import genai
from google.genai import types
from openai import OpenAI
from app.config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    MISTRAL_API_KEY,
    DEFAULT_LLM_PROVIDER as CONFIG_PROVIDER,
    GEMINI_MODEL,
    GROQ_MODEL,
    MISTRAL_MODEL
)

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
1. {"name": "navigate", "url": "https://example.com"} - Navigate to a website.
2. {"name": "click", "element_id": "button-1"} - Click a visible button, link, or input. Use the tag ID provided in brackets.
3. {"name": "type", "element_id": "input-2", "text": "my search text", "press_enter": true} - Fill text into an input field. Set `press_enter` to true if you want to submit right away.
4. {"name": "scroll", "direction": "down"} - Scroll "down" or "up" on the current page to reveal more content.
5. {"name": "wait", "seconds": 3} - Pause execution for a few seconds. Useful if a page is loading or processing dynamic requests.
6. {"name": "complete", "summary": "Detailed summary of findings..."} - Call this when you have successfully completed the user's objective and have extracted the required information. Include the findings directly in the summary.

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
    """Extracts the first JSON block from a response string."""
    response_text = response_text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if match:
        return match.group(1)
        
    start = response_text.find('{')
    end = response_text.rfind('}')
    if start != -1 and end != -1:
        return response_text[start:end+1]
        
    return response_text

class AIPlanner:
    def __init__(self, provider: str = None):
        self.provider = (provider or CONFIG_PROVIDER).lower()
        self.client = None
        self.model_name = ""
        self._init_clients()

    def _init_clients(self):
        if self.provider == "gemini":
            if not GEMINI_API_KEY:
                logger.warning("GEMINI_API_KEY is not set. Gemini client may fail to initialize.")
            # Use the new Client library
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model_name = GEMINI_MODEL
        elif self.provider == "groq":
            if not GROQ_API_KEY:
                logger.warning("GROQ_API_KEY is not set. Groq client may fail to initialize.")
            self.client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=GROQ_API_KEY
            )
            self.model_name = GROQ_MODEL
        elif self.provider == "mistral":
            if not MISTRAL_API_KEY:
                logger.warning("MISTRAL_API_KEY is not set. Mistral client may fail to initialize.")
            self.client = OpenAI(
                base_url="https://api.mistral.ai/v1",
                api_key=MISTRAL_API_KEY
            )
            self.model_name = MISTRAL_MODEL
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _call_gemini(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        return response.text

    def _call_openai_compatible(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return response.choices[0].message.content

    def plan_next_step(self, objective: str, current_url: str, page_title: str, page_map: str, history: list) -> dict:
        """Determines the next action to perform using the selected LLM."""
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
        logger.info(f"Planning next step with {self.provider} using model {self.model_name}.")

        try:
            if self.provider == "gemini":
                response_text = self._call_gemini(prompt)
            elif self.provider in ("groq", "mistral"):
                response_text = self._call_openai_compatible(prompt)
            else:
                raise ValueError(f"Unsupported LLM provider: {self.provider}")
            
            cleaned_json = clean_json_string(response_text)
            decision = json.loads(cleaned_json)
            
            if "thought" not in decision or "action" not in decision:
                raise ValueError("Response JSON is missing 'thought' or 'action' key.")
                
            return decision

        except Exception as e:
            logger.error(f"Error calling {self.provider} model: {e}")
            return {
                "thought": f"An error occurred while calling the AI: {str(e)}. I will wait and retry.",
                "action": {
                    "name": "wait",
                    "seconds": 5
                }
            }
