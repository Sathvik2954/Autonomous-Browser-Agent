import asyncio
import logging
from datetime import datetime
from app.browser.controller import BrowserController
from app.parser.extractor import extract_interactive_elements, generate_page_map
from app.planner.planner import AIPlanner
from app.database import (
    get_task,
    update_task_status,
    add_action,
    add_log,
    add_extracted_data
)
from app.config import BROWSER_RECORD_VIDEO

logger = logging.getLogger(__name__)

# Global cache of latest interactive elements per task for DOM inspection API
latest_interactive_elements = {}

async def run_agent_task(task_id: str, prompt: str, provider: str = None, headless: bool = None):
    """Asynchronously runs the agent task step-by-step."""
    logger.info(f"Starting execution for task {task_id} with prompt: {prompt}")
    add_log(task_id, f"Initializing browser agent for task: '{prompt}'", "info")
    
    # Instantiate browser controller
    browser = BrowserController(task_id=task_id, record_video=BROWSER_RECORD_VIDEO, headless=headless)
    planner = AIPlanner(provider=provider)
    
    step = 0
    max_steps = 20
    error_count = 0
    max_errors = 3
    
    try:
        page = await browser.start()
        add_log(task_id, "Browser successfully launched.", "info")
        
        # Take initial screenshot of blank or home page
        screenshot_path = await browser.take_screenshot(name=f"step_{step}_start.png")
        add_action(
            task_id=task_id,
            step=step,
            action_type="start",
            description="Browser started",
            screenshot_path=screenshot_path,
            url=await browser.get_url()
        )
        
        # We start by navigating to Google or a relevant search engine if it's not a URL
        initial_url = "https://www.google.com"
        # Quick heuristic: if prompt looks like it contains a URL, or has a specific domain, we can navigate there
        # but the planner will decide that, or we can bootstrap by starting at Google.
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
            url=await browser.get_url()
        )
        
        # Execution loop
        while step < max_steps:
            # 1. Check if task was stopped by the user
            current_task = get_task(task_id)
            if not current_task or current_task["status"] == "stopped":
                add_log(task_id, "Task execution stopped by user request.", "info")
                break
                
            # 2. Extract page elements
            elements = await extract_interactive_elements(page)
            latest_interactive_elements[task_id] = elements
            page_map = generate_page_map(elements)
            current_url = await browser.get_url()
            page_title = await browser.get_title()
            
            # Fetch actions timeline history for LLM context
            from app.database import get_actions
            action_history = get_actions(task_id)
            
            # 3. Call Planner
            add_log(task_id, f"Analyzing page state at {current_url}...", "info")
            plan = planner.plan_next_step(
                objective=prompt,
                current_url=current_url,
                page_title=page_title,
                page_map=page_map,
                history=action_history
            )
            
            thought = plan.get("thought", "")
            action_data = plan.get("action", {})
            action_name = action_data.get("name", "").lower()
            
            # Log the thought
            add_log(task_id, f"Thought: {thought}", "thought")
            logger.info(f"Task {task_id} - Step {step} - Thought: {thought}")
            
            step += 1
            
            if action_name == "complete":
                summary = action_data.get("summary", "Task completed.")
                add_log(task_id, f"Goal achieved! Completion summary: {summary}", "info")
                
                # Take final screenshot
                screenshot_path = await browser.take_screenshot(name=f"step_{step}_complete.png")
                add_action(
                    task_id=task_id,
                    step=step,
                    action_type="complete",
                    description=summary,
                    screenshot_path=screenshot_path,
                    url=current_url
                )
                
                update_task_status(task_id, "completed", result_summary=summary)
                break
                
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
                        url=await browser.get_url()
                    )
                    error_count = 0  # reset errors on successful navigation
                except Exception as e:
                    error_count += 1
                    err_msg = f"Failed navigation to {target_url}: {str(e)}"
                    add_log(task_id, err_msg, "error")
                    add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)
                    
            elif action_name in ("click", "type", "extract"):
                element_id = action_data.get("element_id", "")
                
                # Find matching element in our extracted list to resolve selector
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
                        
                    elif action_name == "extract":
                        extracted_dict = action_data.get("data", {})
                        desc = f"Extracted data properties: {extracted_dict}"
                        add_log(task_id, f"Action: {desc}", "info")
                        add_extracted_data(task_id, extracted_dict)
                        
                    # Save screenshot after element interaction
                    screenshot_path = await browser.take_screenshot(name=f"step_{step}_{action_name}.png")
                    add_action(
                        task_id=task_id,
                        step=step,
                        action_type=action_name,
                        description=desc,
                        screenshot_path=screenshot_path,
                        url=await browser.get_url()
                    )
                    error_count = 0  # reset errors on success
                    
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
                    url=await browser.get_url()
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
                    url=await browser.get_url()
                )
                
            else:
                err_msg = f"Unknown action proposed: {action_name}"
                add_log(task_id, err_msg, "warning")
                add_action(task_id=task_id, step=step, action_type="error", description=err_msg, url=current_url)
                await asyncio.sleep(2)
                
            # Check for consecutive errors limit
            if error_count >= max_errors:
                err_msg = f"Terminating task due to {max_errors} consecutive failures."
                add_log(task_id, err_msg, "error")
                update_task_status(task_id, "failed", error=err_msg)
                break
                
            # Pause briefly between steps
            await asyncio.sleep(1)
            
        else:
            # Reached max steps limit
            err_msg = "Task stopped because it exceeded the maximum allowed steps (20)."
            add_log(task_id, err_msg, "warning")
            update_task_status(task_id, "failed", error=err_msg)
            
    except Exception as e:
        err_msg = f"Execution error in run_agent_task: {str(e)}"
        logger.error(err_msg, exc_info=True)
        add_log(task_id, err_msg, "error")
        update_task_status(task_id, "failed", error=err_msg)
        
    finally:
        # If headed mode was used, keep browser open for 60 seconds so user can inspect it
        if headless is False:
            add_log(task_id, "Task finished in headed mode. Keeping browser window open for 60 seconds for inspection...", "info")
            await asyncio.sleep(60)
            
        # Stop browser and clean up
        add_log(task_id, "Shutting down browser context...", "info")
        video_path = await browser.stop()
        
        # Save video path to task db if recorded
        if video_path:
            conn = None
            try:
                import sqlite3
                from app.config import DB_PATH
                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.cursor()
                cursor.execute("UPDATE tasks SET result_summary = COALESCE(result_summary, '') || '\nVideo path: ' || ? WHERE id = ?", (video_path, task_id))
                conn.commit()
            except Exception:
                pass
            finally:
                if conn:
                    conn.close()
                    
        add_log(task_id, "Browser agent shutdown complete.", "info")
