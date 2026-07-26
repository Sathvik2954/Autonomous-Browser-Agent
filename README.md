# Autonomous Browser Agent (ABA)

This repository contains the Autonomous Browser Agent, developed as a submission for the HackWeek 2026 Competition. The agent uses FastAPI, Playwright, and a **local** LLM (served by Ollama) to complete browser and file-organizing tasks from natural language prompts -- no cloud API keys required.

## Project Overview

ABA takes a plain-language instruction and routes it to one of two engines:

- **Browser tasks** -- reads the current page, catalogs interactive elements, asks a local model what to do next, and acts. It replans at every step, so it adapts to dynamic pages, overlays, and unexpected transitions instead of following a fixed script.
- **Organizer tasks** -- scans a local folder for generically-named Word documents (`doc1.docx`, `Untitled.docx`, etc.) and renames them based on their actual content, entirely offline.

A lightweight keyword-based dispatcher decides which engine handles a given prompt, so both live behind the same "describe what you want" input.

## Key Features

1. **Local-only reasoning** -- the planner talks to a model served by [Ollama](https://ollama.com) over its OpenAI-compatible API. Nothing leaves your machine; there's no API key to configure or pay for.
2. **Adaptive reasoning loop** -- runs a step-by-step plan-act-observe cycle instead of a static script, replanning at each step based on the current page state.
3. **Local web search** -- a `web_search` action queries DuckDuckGo's HTML endpoint directly for structured results (title/url/snippet), instead of driving the browser through a search engine's DOM.
4. **Element mapping heuristics** -- evaluates visible interactive elements on the DOM and labels them with concise IDs such as `button-1` or `input-3`, avoiding passing massive, token-heavy HTML to the model.
5. **Document auto-organizing** -- local, offline keyword extraction (`yake`) names documents from their actual content; renames are collision-safe and logged for traceability.
6. **Session recovery** -- a stopped, failed, or completed browser task can be resumed: the new run continues from the last known URL and the model is given the prior run's action history for context, instead of starting over.
7. **Session records** -- saves a screenshot at every step and compiles each run into a webm video recording.
8. **Structured exporters** -- collects tabular data extracted during a run and exports it to JSON or CSV.
9. **SPA management dashboard** -- a single-page dashboard to submit instructions, watch live screenshots, inspect the step timeline, and review logs.

## System Architecture

The frontend dashboard talks to a FastAPI backend. Submitting a prompt creates a task record and starts a background worker:

**Browser tasks:**
1. Extract visible interactive DOM elements and map their selectors.
2. Send the current state, prior action history, and the element map to the local model.
3. Receive the next step as structured JSON: `{"thought": ..., "action": {...}}`.
4. Execute the action -- `web_search`, `navigate`, `click`, `type`, `scroll`, `wait`, `extract`, or `complete`.
5. Capture a screenshot, log the step to SQLite, and continue until the model signals completion or a step/error limit is hit.
6. Write a final report and video recording when the run ends.

**Organizer tasks:**
1. Resolve which folder the prompt refers to (an explicit path, or a common alias like "Downloads").
2. Scan for `.docx` files that look auto-generated.
3. Extract each file's title metadata, headings, and body text; derive a descriptive name.
4. Rename collision-safely and log every rename for traceability.

## Installation

### Prerequisites
- Python 3.10 or higher
- Node.js (for the frontend, if you're rebuilding it)
- Windows, macOS, or Linux
- [Ollama](https://ollama.com) installed and running locally

### Step 1: Install Ollama and pull a model
Install Ollama from https://ollama.com, then pull the default model:
```bash
ollama pull qwen2.5:3b
```
`qwen2.5:3b` is a lightweight (~2GB) model chosen so this runs on modest hardware without a GPU. If you have a stronger machine and want noticeably better planning quality, pull a larger model in the same family instead (e.g. `qwen2.5:7b` or `qwen2.5:14b`) and point `OLLAMA_MODEL` at it -- no code changes needed.

Start the Ollama server (if it isn't already running as a service):
```bash
ollama serve
```

### Step 2: Install Python Dependencies
Install the required packages from the project root:
```bash
pip install -r requirements.txt
```

### Step 3: Install Playwright Chromium
Download the required browser binaries for Playwright:
```bash
playwright install chromium
```

### Step 4: Configure Environment Variables
Create a `.env` file in the project root:
```bash
copy .env.example .env
```
The defaults work out of the box as long as Ollama is running with the model pulled. Relevant values:
- `OLLAMA_BASE_URL`: Ollama's OpenAI-compatible endpoint (default `http://localhost:11434/v1`).
- `OLLAMA_MODEL`: which model to use (default `qwen2.5:3b`).
- `BROWSER_HEADLESS`: `True` to run tasks in the background, `False` to see the Chromium window.

## Running the Application

Start the backend FastAPI server:
```bash
python -m app.main
```

Once started:
- Access the dashboard at http://127.0.0.1:8000
- Describe your goal in the prompt box and click Execute Prompt. Be specific -- name the site/target for browsing tasks, or the exact folder for organizing tasks (the agent won't guess a folder on its own).
- Logs, the step timeline, and screenshots update live while the task runs.

## API Specification

### Task Endpoints
- `POST /api/tasks` -- Launches a new task, routed automatically to the browser agent or the document organizer.
  - Request Body: `{"prompt": "Find the cheapest laptop under 50000 rupees on Amazon", "headless": false}`
  - Response: `{"task_id": "task_abc", "prompt": "...", "status": "running"}`
- `GET /api/tasks` -- Returns a list of all historical task runs.
- `GET /api/tasks/{task_id}` -- Retrieves detailed state, the action timeline, logs, extracted data, and the latest screenshot path.
- `POST /api/tasks/{task_id}/stop` -- Stops a running task's execution loop.
- `POST /api/tasks/{task_id}/resume` -- Starts a new task that continues a previous one: browser tasks pick up from the last known URL with prior history for context; organizer tasks are simply re-run (idempotent, since already-renamed files are skipped automatically).

### Assets and Export Endpoints
- `GET /api/tasks/{task_id}/screenshot` -- Streams the screenshot image for a specific step.
- `GET /api/tasks/{task_id}/video` -- Streams the recorded webm video file.
- `GET /api/tasks/{task_id}/report` -- Generates and returns a markdown executive summary.
- `GET /api/tasks/{task_id}/export/{csv|json}` -- Downloads the extracted structured data.

## Command-Line Tools

- `python scripts/organize_documents.py <folder>` -- previews document renames without touching anything; pass `--apply` to actually rename, `--all` to include non-generically-named files, `--recursive` to scan subfolders.

## Testing

```bash
pytest tests/
```

Tests that require a real Chromium binary or live network access (DuckDuckGo, Ollama) are skipped/mocked where the environment doesn't support them; see individual test docstrings for what's verified offline versus what needs a live check on your machine.
