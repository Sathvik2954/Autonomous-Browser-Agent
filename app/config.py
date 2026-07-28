import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent

SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SESSIONS_DIR = ROOT_DIR / "sessions"
REPORTS_DIR = ROOT_DIR / "reports"
LOGS_DIR = ROOT_DIR / "logs"

for directory in [SCREENSHOTS_DIR, SESSIONS_DIR, REPORTS_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

DB_PATH = LOGS_DIR / "agent.db"

# Local LLM configuration (Ollama's OpenAI-compatible API). No API key, no
# cloud provider -- everything runs on this machine. See README for setup.
#
# Default model is qwen2.5:3b -- a lightweight (~2GB) model chosen so the
# agent runs on modest hardware (no GPU required) while still following the
# JSON-structured "thought + action" instructions in app/planner/planner.py
# reliably enough to be usable. If you have a stronger machine and want
# noticeably better planning/reasoning, override OLLAMA_MODEL with a larger
# model in the same family (e.g. qwen2.5:7b or qwen2.5:14b) -- no code
# changes needed, just `ollama pull <model>` and update .env.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# Optional fallback models, tried in order (still through the same local
# Ollama server -- e.g. a Gemma model) if OLLAMA_MODEL fails to respond or
# returns unparseable output. Comma-separated, empty by default (off unless
# you opt in). Each one has to be pulled locally first, same as OLLAMA_MODEL:
# `ollama pull gemma2:2b`. See app/planner/planner.py for the fallback logic.
OLLAMA_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("OLLAMA_FALLBACK_MODELS", "").split(",") if m.strip()
]

# Browser Configurations
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "False").lower() in ("true", "1", "yes")
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "30000"))
BROWSER_RECORD_VIDEO = os.getenv("BROWSER_RECORD_VIDEO", "True").lower() in ("true", "1", "yes")

# Server configurations
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
