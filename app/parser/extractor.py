from playwright.async_api import Page
import logging

logger = logging.getLogger(__name__)

JS_EXTRACT_ELEMENTS = """
() => {
    // Helper to check if element is visible
    const isVisible = (elem) => {
        if (!elem) return false;
        const rect = elem.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        
        const style = window.getComputedStyle(elem);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) {
            return false;
        }
        
        // Check parent visibility
        let parent = elem.parentElement;
        while (parent) {
            const pStyle = window.getComputedStyle(parent);
            if (pStyle.display === 'none' || pStyle.visibility === 'hidden') {
                return false;
            }
            parent = parent.parentElement;
        }
        return true;
    };

    // Remove any previously injected agent IDs
    document.querySelectorAll('[data-agent-id]').forEach(el => {
        el.removeAttribute('data-agent-id');
    });

    const interactiveSelectors = [
        'a', 'button', 'input', 'select', 'textarea', 
        '[role="button"]', '[role="link"]', '[role="checkbox"]', 
        '[role="radio"]', '[role="tab"]', '[onclick]', 
        '.btn', '.button', '.link'
    ];

    const elements = document.querySelectorAll(interactiveSelectors.join(','));
    const results = [];
    let buttonCount = 0;
    let linkCount = 0;
    let inputCount = 0;
    let selectCount = 0;
    let otherCount = 0;

    elements.forEach(elem => {
        if (!isVisible(elem)) return;

        const tagName = elem.tagName.toUpperCase();
        const role = elem.getAttribute('role') || '';
        const type = elem.getAttribute('type') || '';
        
        let elemType = 'other';
        let prefix = 'other';
        
        if (tagName === 'INPUT' || tagName === 'TEXTAREA') {
            elemType = 'input';
            prefix = 'input';
        } else if (tagName === 'SELECT') {
            elemType = 'select';
            prefix = 'select';
        } else if (tagName === 'A' || role === 'link' || elem.classList.contains('link')) {
            elemType = 'link';
            prefix = 'link';
        } else if (tagName === 'BUTTON' || role === 'button' || elem.classList.contains('btn') || elem.classList.contains('button')) {
            elemType = 'button';
            prefix = 'button';
        }

        let id = '';
        if (prefix === 'button') {
            buttonCount++;
            id = `button-${buttonCount}`;
        } else if (prefix === 'link') {
            linkCount++;
            id = `link-${linkCount}`;
        } else if (prefix === 'input') {
            inputCount++;
            id = `input-${inputCount}`;
        } else if (prefix === 'select') {
            selectCount++;
            id = `select-${selectCount}`;
        } else {
            otherCount++;
            id = `other-${otherCount}`;
        }

        // Set the unique data attribute for our Playwright locator to target
        elem.setAttribute('data-agent-id', id);

        // Extract metadata
        const text = (elem.innerText || elem.ariaLabel || elem.title || elem.value || '').trim().replace(/\\s+/g, ' ');
        const placeholder = elem.getAttribute('placeholder') || '';
        const href = elem.getAttribute('href') || '';
        const isChecked = elem.checked || false;
        const isDisabled = elem.disabled || false;

        results.push({
            id: id,
            type: elemType,
            tagName: tagName,
            text: text.substring(0, 100), // Cap length
            placeholder: placeholder,
            href: href,
            checked: isChecked,
            disabled: isDisabled,
            selector: `[data-agent-id="${id}"]`
        });
    });

    return results;
}
"""

async def extract_interactive_elements(page: Page) -> list:
    """Executes element tagging JavaScript on the page and returns interactive elements metadata."""
    if not page:
        return []
    try:
        elements = await page.evaluate(JS_EXTRACT_ELEMENTS)
        return elements
    except Exception as e:
        logger.error(f"Error extracting interactive elements: {e}")
        return []

def generate_page_map(elements: list) -> str:
    """Formats elements list into a clean, text-based interactive map for the LLM."""
    if not elements:
        return "No interactive elements found on the page."
        
    lines = []
    for el in elements:
        details = []
        if el['text']:
            details.append(f"text: \"{el['text']}\"")
        if el['placeholder']:
            details.append(f"placeholder: \"{el['placeholder']}\"")
        if el['href'] and el['type'] == 'link':
            details.append(f"href: \"{el['href']}\"")
        if el['disabled']:
            details.append("disabled")
        if el['checked']:
            details.append("checked")
            
        details_str = ", ".join(details)
        elem_desc = f"[{el['id']}] ({el['type'].upper()}) {details_str}"
        lines.append(elem_desc)
        
    return "\n".join(lines)
