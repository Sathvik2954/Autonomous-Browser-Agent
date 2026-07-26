import asyncio
import logging

from app.browser.controller import BrowserController
from app.parser.extractor import extract_interactive_elements, generate_page_map
from app.planner.planner import AIPlanner
from app.search.duckduckgo import search_web, SearchError
from app.database import (
    get_task,
    update_task_status,
    add_action,
    add_log,
    add_extracted_data,
    get_actions,
)
from app.config import BROWSER_RECORD_VIDEO

logger = logging.getLogger(__name__)

# Global cache of latest interactive elements per task, read by the frontend's
# Developer Console DOM inspector panel.
latest_interactive_elements = {}


async def run_agent_task(task_id: str, prompt: str, provider: str = None, headless: bool = None, resume_context: dict = None):
    """Runs the agent task step-by-step: read the page, ask the local LLM what to
    do next, execute that action, repeat. `provider` is accepted for API
    backward compatibility but unused -- there's only one planner now (Ollama).

    `resume_context`, if given, is `{"source_task_id": str, "last_url": str,
    "prior_actions": list}` built by the /tasks/{id}/resume endpoint. Instead
    of starting fresh from google.com, this task picks up browsing from the
    prior task's last known URL, and the prior task's action history is fed
    to the planner alongside this task's own so it has continuity of context
    (what was already tried, what was already found) rather than repeating
    work or losing track of what it was doing."""
    logger.info(f"Starting execution for task {task_id} with prompt: {prompt}")
    add_log(task_id, f"Initializing browser agent for task: '{prompt}'", "info")

    browser = BrowserController(task_id=task_id, record_video=BROWSER_RECORD_VIDEO, headless=headless)
    planner = AIPlanner()

    step = 0
    max_steps = 20
    error_count = 0
    max_errors = 3

    prior_history = []
    initial_url = "https://www.google.com"
    if resume_context:
        source_task_id = resume_context.get("source_task_id", "unknown")
        last_url = resume_context.get("last_url")
        if last_url:
            initial_url = last_url
        prior_history = [
            {**a, "description": f"[Previous session] {a.get('description', '')}"}
            for a in resume_context.get("prior_actions", [])
        ]
        add_log(task_id, f"Resuming from task {source_task_id} -- continuing from {initial_url}", "info")

    try:
        page = await browser.start()
        add_log(task_id, "Browser successfully launched.", "info")

        screenshot_path = await browser.take_screenshot(name=f"step_{step}_start.png")
        add_action(
            task_id=task_id,
            step=step,
            action_type="start",
            description="Browser started",
            screenshot_path=screenshot_path,
            url=await browser.get_url(),
        )

        add_log(task_id, f"Navigating to initial landing page: {initial_url}", "info")
        await browser.navigate(initial_url)

        step += 1
        screenshot_path = await browser.take_screenshot(name=f"step_{step}_nav.png")
        add_action(
            task_id=task_id,
            step=step,
            action_type="navigate",
            description=f"Navigated to {initial_url}",
            screenshot_path=screenshot_path,
            url=await browser.get_url(),
        )

        while step < max_steps:
            current_task = get_task(task_id)
            if not current_task or current_task["status"] == "stopped":
                add_log(task_id, "Task execution stopped by user request.", "info")
                break

            elements = await extract_interactive_elements(page)
            latest_interactive_elements[task_id] = elements
            page_map = generate_page_map(elements)
            current_url = await browser.get_url()
            page_title = await browser.get_title()

            action_history = get_actions(task_id)

            add_log(task_id, f"Analyzing page state at {current_url}...", "info")
            plan = planner.plan_next_step(
                objective=prompt,
                current_url=current_url,
                page_title=page_title,
                page_map=page_map,
                history=prior_history + action_history,
            )

            thought = plan.get("thought", "")
            action_data = plan.get("action", {})
            action_name = action_data.get("name", "").lower()

            add_log(task_id, f"Thought: {thought}", "thought")
            logger.info(f"Task {task_id} - Step {step} - Thought: {thought}")

            step += 1

            if action_name == "complete":
                summary = action_data.get("summary", "Task completed.")
                add_log(task_id, f"Goal achieved! Completion summary: {summary}", "info")

                screenshot_path = await browser.take_screenshot(name=f"step_{step}_complete.png")
                add_action(
                    task_id=task_id,
                    step=step,
                    action_type="complete",
                    description=summary,
                    screenshot_path=screenshot_path,
                    url=current_url,
                )

                update_task_status(task_id, "completed", result_summary=summary)
                break

            elif action_name == "web_search":
                query = action_data.get("query", "")
                add_log(task_id, f"Action: Searching the web for '{query}'", "info")

                try:
                    results = search_web(query, max_results=5)
                    if results:
                        lines = [f"{i+1}. {r.title} — {r.url}\n   {r.snippet}" for i, r in enumerate(results)]
                        desc = f"Search results for '{query}':\n" + "\n".join(lines)
                    else:
                        desc = f"Search for '{query}' returned no results."

                    add_log(task_id, desc, "info")
                    screenshot_path = await browser.take_screenshot(name=f"step_{step}_search.png")
                    add_action(
                        task_id=task_id,
                        step=step,
                        action_type="web_search",
                        description=desc,
                        screenshot_path=screenshot_path,
                        url=await browser.get_url(),
                    )
                    error_count = 0
                except SearchError as e:
                    error_count += 1
                    err_msg = f"Web search failed: {e}"
                    add_log(task_id, err_msg, "error")
                    add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)

            elif action_name == "navigate":
                target_url = action_data.get("url", "")
                add_log(task_id, f"Action: Navigate to {target_url}", "info")

                try:
                    await browser.navigate(target_url)
                    screenshot_path = await browser.take_screenshot(name=f"step_{step}_navigate.png")
                    add_action(
                        task_id=task_id,
                        step=step,
                        action_type="navigate",
                        description=f"Navigated to {target_url}",
                        screenshot_path=screenshot_path,
                        url=await browser.get_url(),
                    )
                    error_count = 0
                except Exception as e:
                    error_count += 1
                    err_msg = f"Failed navigation to {target_url}: {str(e)}"
                    add_log(task_id, err_msg, "error")
                    add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)

            elif action_name in ("click", "type", "extract"):
                element_id = action_data.get("element_id", "")

                if action_name == "extract":
                    extracted_dict = action_data.get("data", {})
                    desc = f"Extracted data properties: {extracted_dict}"
                    add_log(task_id, f"Action: {desc}", "info")
                    add_extracted_data(task_id, extracted_dict)

                    screenshot_path = await browser.take_screenshot(name=f"step_{step}_extract.png")
                    add_action(
                        task_id=task_id,
                        step=step,
                        action_type="extract",
                        description=desc,
                        screenshot_path=screenshot_path,
                        url=await browser.get_url(),
                    )
                    error_count = 0
                    await asyncio.sleep(1)
                    continue

                matching_element = next((el for el in elements if el["id"] == element_id), None)

                if not matching_element:
                    err_msg = f"Element {element_id} was not found on the current page."
                    add_log(task_id, err_msg, "warning")
                    add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)
                    error_count += 1
                    await asyncio.sleep(2)
                    continue

                selector = matching_element["selector"]

                try:
                    if action_name == "click":
                        desc = f"Clicked element [{element_id}] ('{matching_element['text']}')"
                        add_log(task_id, f"Action: {desc}", "info")
                        await browser.click(selector)

                    elif action_name == "type":
                        text_to_type = action_data.get("text", "")
                        press_enter = action_data.get("press_enter", False)
                        desc = f"Typed '{text_to_type}' into [{element_id}]"
                        if press_enter:
                            desc += " and pressed Enter"
                        add_log(task_id, f"Action: {desc}", "info")
                        await browser.type_text(selector, text_to_type, press_enter=press_enter)

                    screenshot_path = await browser.take_screenshot(name=f"step_{step}_{action_name}.png")
                    add_action(
                        task_id=task_id,
                        step=step,
                        action_type=action_name,
                        description=desc,
                        screenshot_path=screenshot_path,
                        url=await browser.get_url(),
                    )
                    error_count = 0

                except Exception as e:
                    error_count += 1
                    err_msg = f"Action failed on element {element_id}: {str(e)}"
                    add_log(task_id, err_msg, "error")
                    add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)
                    await asyncio.sleep(2)

            elif action_name == "scroll":
                direction = action_data.get("direction", "down")
                desc = f"Scrolled page {direction}"
                add_log(task_id, f"Action: {desc}", "info")
                await browser.scroll(direction=direction)

                screenshot_path = await browser.take_screenshot(name=f"step_{step}_scroll.png")
                add_action(
                    task_id=task_id,
                    step=step,
                    action_type="scroll",
                    description=desc,
                    screenshot_path=screenshot_path,
                    url=await browser.get_url(),
                )

            elif action_name == "wait":
                secs = float(action_data.get("seconds", 3))
                desc = f"Waited {secs} seconds"
                add_log(task_id, f"Action: {desc}", "info")
                await browser.wait(secs)

                screenshot_path = await browser.take_screenshot(name=f"step_{step}_wait.png")
                add_action(
                    task_id=task_id,
                    step=step,
                    action_type="wait",
                    description=desc,
                    screenshot_path=screenshot_path,
                    url=await browser.get_url(),
                )

            else:
                err_msg = f"Unknown action proposed: {action_name}"
                add_log(task_id, err_msg, "warning")
                add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)
                await asyncio.sleep(2)

            if error_count >= max_errors:
                err_msg = f"Terminating task due to {max_errors} consecutive failures."
                add_log(task_id, err_msg, "error")
                update_task_status(task_id, "failed", error=err_msg)
                break

            await asyncio.sleep(1)

        else:
            err_msg = "Task stopped because it exceeded the maximum allowed steps (20)."
            add_log(task_id, err_msg, "warning")
            update_task_status(task_id, "failed", error=err_msg)

    except Exception as e:
        err_msg = f"Execution error in run_agent_task: {str(e)}"
        logger.error(err_msg, exc_info=True)
        add_log(task_id, err_msg, "error")
        update_task_status(task_id, "failed", error=err_msg)

    finally:
        if headless is False:
            add_log(task_id, "Task finished in headed mode. Keeping browser window open for 60 seconds for inspection...", "info")
            await asyncio.sleep(60)

        add_log(task_id, "Shutting down browser context...", "info")
        video_path = await browser.stop()

        if video_path:
            conn = None
            try:
                import sqlite3
                from app.config import DB_PATH

                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE tasks SET result_summary = COALESCE(result_summary, '') || '\nVideo path: ' || ? WHERE id = ?",
                    (video_path, task_id),
                )
                conn.commit()
            except Exception:
                pass
            finally:
                if conn:
                    conn.close()

        add_log(task_id, "Browser agent shutdown complete.", "info")
