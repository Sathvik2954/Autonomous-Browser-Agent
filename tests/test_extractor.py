import pytest
from playwright.async_api import async_playwright
from app.parser.extractor import extract_interactive_elements, generate_page_map

@pytest.mark.asyncio
async def test_element_extractor():
    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Set mock HTML content
        html_content = """
        <html>
            <body>
                <button id="btn1">Submit Query</button>
                <a href="/about" class="link">Read More</a>
                <input type="text" placeholder="Enter name" />
                <div role="button" aria-label="Custom Click">Click Me</div>
                <div style="display: none;"><button>Hidden Button</button></div>
            </body>
        </html>
        """
        await page.set_content(html_content)
        
        # Run extractor
        elements = await extract_interactive_elements(page)
        
        # Assertions
        assert len(elements) == 4, f"Expected 4 interactive elements, found {len(elements)}"
        
        # Check element types
        types = [el['type'] for el in elements]
        assert 'button' in types
        assert 'link' in types
        assert 'input' in types
        
        # Verify tag assignment
        assert elements[0]['id'] == 'button-1'
        assert elements[0]['text'] == 'Submit Query'
        assert elements[1]['id'] == 'link-1'
        assert elements[2]['id'] == 'input-1'
        
        # Generate page map
        page_map = generate_page_map(elements)
        assert "[button-1] (BUTTON) text: \"Submit Query\"" in page_map
        assert "[link-1] (LINK)" in page_map
        
        await browser.close()
