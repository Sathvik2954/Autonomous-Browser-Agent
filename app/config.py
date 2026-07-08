import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent

# Output and runtime directories
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SESSIONS_DIR = ROOT_DIR / "sessions"
REPORTS_DIR = ROOT_DIR / "reports"
LOGS_DIR = ROOT_DIR / "logs"

# Ensure directories exist
for directory in [SCREENSHOTS_DIR, SESSIONS_DIR, REPORTS_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Database path
DB_PATH = LOGS_DIR / "agent.db"

# LLM Configurations
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "mistral").lower()

# Model Names
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-4-scout-17b-16e")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# Browser Configurations
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "False").lower() in ("true", "1", "yes")
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "30000"))
BROWSER_RECORD_VIDEO = os.getenv("BROWSER_RECORD_VIDEO", "True").lower() in ("true", "1", "yes")

# Server configurations
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
