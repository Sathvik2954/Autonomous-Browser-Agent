import sys
import asyncio
import uvicorn
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Resolve Windows subprocess NotImplementedError for asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.api.routes import router as api_router
from app.database import init_db
from app.config import HOST, PORT

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Lifespan context manager for startup and shutdown actions
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully.")
    yield

app = FastAPI(
    title="Autonomous Browser Agent API",
    description="Backend API for managing AI-driven browser sessions.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router)

# Mount Frontend Static files
import os
from pathlib import Path
from app.config import ROOT_DIR

react_dist = ROOT_DIR / "frontend" / "dist"
if react_dist.exists():
    static_dir = react_dist
    logger.info(f"Serving production React frontend from {static_dir}")
else:
    static_dir = Path(__file__).resolve().parent / "static"
    logger.info(f"Serving fallback static frontend from {static_dir}")

os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    logger.info(f"Starting server on http://{HOST}:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
