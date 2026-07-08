import asyncio
import os
import uuid
from pathlib import Path
from playwright.async_api import async_playwright
from app.config import BROWSER_HEADLESS, BROWSER_TIMEOUT, SCREENSHOTS_DIR, SESSIONS_DIR

class BrowserController:
    def __init__(self, task_id: str, record_video: bool = True, headless: bool = None):
        self.task_id = task_id
        self.record_video = record_video
        self.headless = headless if headless is not None else BROWSER_HEADLESS
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.video_dir = SESSIONS_DIR / task_id
        self.video_dir.mkdir(parents=True, exist_ok=True)

    async def start(self):
        """Starts Playwright and launches the browser context."""
        self.playwright = await async_playwright().start()
        
        # Launch options
        launch_args = []
        
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args
        )
        
        # Context options (video, viewport)
        context_args = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept_downloads": True
        }
        
        if self.record_video:
            context_args["record_video_dir"] = str(self.video_dir)
            context_args["record_video_size"] = {"width": 1280, "height": 720}
            
        self.context = await self.browser.new_context(**context_args)
        self.context.set_default_timeout(BROWSER_TIMEOUT)
        self.page = await self.context.new_page()
        
        # Inject standard anti-bot behaviors if needed
        await self.page.add_init_script(
            "const newProto = navigator.__proto__;"
            "delete newProto.webdriver;"
            "navigator.__proto__ = newProto;"
        )
        
        return self.page

    async def stop(self):
        """Stops the browser session and saves recording details if applicable."""
        video_path = None
        if self.page:
            try:
                # If recording video, get path before closing context
                if self.record_video and self.page.video:
                    video_path = await self.page.video.path()
            except Exception:
                pass
            
            try:
                await self.page.close()
            except Exception:
                pass
                
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
                
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
                
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
                
        # If video was recorded, let's rename it to something simple inside video_dir
        final_video_path = None
        if video_path and os.path.exists(video_path):
            try:
                dest = self.video_dir / "recording.webm"
                os.replace(video_path, dest)
                final_video_path = str(dest)
            except Exception:
                final_video_path = video_path
                
        return final_video_path

    async def navigate(self, url: str):
        """Navigates to the specified URL."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        await self.page.goto(url, wait_until="load")
        # Wait a small buffer for dynamic DOM rendering
        await asyncio.sleep(2)

    async def click(self, selector: str):
        """Clicks an element matching the selector."""
        # Wait for element to be visible/attached
        element = self.page.locator(selector)
        await element.scroll_into_view_if_needed()
        await element.click(timeout=10000)
        # Small wait for events to process
        await asyncio.sleep(1.5)

    async def type_text(self, selector: str, text: str, press_enter: bool = False):
        """Fills an input field with text."""
        element = self.page.locator(selector)
        await element.scroll_into_view_if_needed()
        await element.fill(text, timeout=10000)
        if press_enter:
            await element.press("Enter")
        await asyncio.sleep(1.5)

    async def scroll(self, direction: str = "down", amount: int = 500):
        """Scrolls the page."""
        if direction == "down":
            await self.page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await self.page.evaluate(f"window.scrollBy(0, -{amount})")
        await asyncio.sleep(1)

    async def wait(self, seconds: float):
        """Waits for specified seconds."""
        await asyncio.sleep(seconds)

    async def get_url(self) -> str:
        return self.page.url if self.page else ""

    async def get_title(self) -> str:
        return await self.page.title() if self.page else ""

    async def take_screenshot(self, name: str = None) -> str:
        """Captures a screenshot of the current page and returns its path."""
        if not self.page:
            return ""
        if not name:
            name = f"{uuid.uuid4().hex}.png"
        
        # Ensure it has .png extension
        if not name.endswith(".png"):
            name += ".png"
            
        task_screenshot_dir = SCREENSHOTS_DIR / self.task_id
        task_screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        dest_path = task_screenshot_dir / name
        try:
            await self.page.screenshot(path=str(dest_path))
            return str(dest_path)
        except Exception:
            return ""
