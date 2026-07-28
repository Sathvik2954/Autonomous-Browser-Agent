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
from app.config import HOST, PORT, ROOT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully.")
    yield

app = FastAPI(
    title="Wisp API",
    description="Backend API for Wisp -- a local-LLM agent that browses the web and organizes files.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Serve the built React dashboard. If it hasn't been built yet, skip the
# mount entirely rather than serving an empty/broken directory -- the API
# still works, but `npm run build` inside frontend/ is required for the UI.
react_dist = ROOT_DIR / "frontend" / "dist"
if react_dist.exists():
    logger.info(f"Serving frontend from {react_dist}")
    app.mount("/", StaticFiles(directory=str(react_dist), html=True), name="static")
else:
    logger.warning(
        "frontend/dist not found -- the dashboard won't be served until you "
        "run `npm install && npm run build` inside frontend/."
    )

if __name__ == "__main__":
    logger.info(f"Starting server on http://{HOST}:{PORT}")
    # reload_dirs is scoped to app/ only -- without this, uvicorn's default
    # reload watches the entire project root, INCLUDING logs/, sessions/,
    # screenshots/, and reports/, which the app itself writes to on every
    # task step (every screenshot, every log line to agent.db, every video).
    # That turns normal task execution into a stream of self-triggered
    # "changes detected" restarts, which can kill a task mid-run. It also
    # meant edits to tests/, scripts/, or the frontend triggered a backend
    # restart even though nothing the server actually imports had changed.
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=[str(ROOT_DIR / "app")],
    )
