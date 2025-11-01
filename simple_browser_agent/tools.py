"""
LangGraph-compatible browser tools for the browser agent.

This module provides browser actions as LangGraph @tool decorated functions.
Tools are created via a factory pattern to inject browser and LLM context.
"""
import logging
from typing import Any, Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def create_browser_tools(browser, llm, model: str = "gpt-4o-mini"):
    """
    Create all browser tools with browser and LLM context injected via closure.
    
    Args:
        browser: SimpleBrowserSession instance
        llm: LangChain AzureChatOpenAI client
        model: Model name for LLM operations
        
    Returns:
        List of 9 LangGraph-compatible tools
    """
    
    # ==============================================================
    # TOOL 1: NAVIGATE
    # ==============================================================
    
    @tool
    async def navigate(url: str) -> str:
        """
        Navigate the browser to a specific URL.
        
        Use this when you need to go to a website or webpage.
        
        Args:
            url: The complete URL to navigate to (e.g., "https://www.costco.com")
            
        Returns:
            Success message with the URL navigated to, or error message
            
        Examples:
            - navigate("https://www.costco.com")
            - navigate("https://www.google.com")
        """
        try:
            await browser.navigate(url)
            return f"✅ Successfully navigated to {url}"
        except Exception as e:
            logger.error(f"Navigate failed: {e}")
            return f"❌ Navigation error: {str(e)}"
    
    # ==============================================================
    # TOOL 2: CLICK
    # ==============================================================
    
    @tool
    async def click(index: int) -> str:
        """
        Click an element on the page by its index number.
        
        Each interactive element on the page has an index number like [0], [1], [2].
        Use the index from the Interactive Elements list provided in the browser state.
        
        This tool includes smart detection of what happened after the click:
        - Page navigation
        - Modal/popup appearance
        - Cart updates
        - Content changes
        
        Args:
            index: The index number of the element to click (from the elements list)
            
        Returns:
            Detailed feedback about what happened after the click
            
        Examples:
            - click(0) - Clicks the element at index 0
            - click(5) - Clicks the element at index 5
        """
        try:
            import asyncio
            
            # Capture state before click
            js_before = """
            (function() {
                return {
                    url: window.location.href,
                    modalCount: document.querySelectorAll('[role="dialog"], .modal, [class*="modal"], [class*="popup"], [class*="overlay"]').length,
                    bodyHash: document.body.innerHTML.length,
                    cartText: document.querySelector('[class*="cart"], [aria-label*="cart"], [id*="cart"]')?.textContent || ''
                };
            })();
            """
            result = await browser._send_command('Runtime.evaluate', {
                'expression': js_before,
                'returnByValue': True
            }, session_id=browser.session_id)
            state_before = result.get('result', {}).get('value', {})
            
            # Perform click (CDP mouse events)
            success = await browser.click(index)
            
            if not success:
                # Fallback: Try JavaScript click using CDP's DOM.resolveNode and Runtime.callFunctionOn
                logger.info(f"CDP click failed for element {index}, trying JavaScript click...")
                if index in browser.element_cache:
                    node_id = browser.element_cache[index]
                    try:
                        # Resolve the node to get a remote object
                        resolve_result = await browser._send_command('DOM.resolveNode', {
                            'nodeId': node_id
                        }, session_id=browser.session_id)
                        
                        if 'object' in resolve_result:
                            # Call click() on the resolved object
                            await browser._send_command('Runtime.callFunctionOn', {
                                'functionDeclaration': 'function() { this.click(); }',
                                'objectId': resolve_result['object']['objectId']
                            }, session_id=browser.session_id)
                            logger.info(f"✓ JavaScript click executed for element {index}")
                        else:
                            return f"❌ Element {index} not found or not clickable"
                    except Exception as e:
                        logger.error(f"JavaScript click failed: {e}")
                        return f"❌ Element {index} not clickable: {str(e)}"
                else:
                    return f"❌ Element {index} not found in cache"
            
            # Wait for page response
            await asyncio.sleep(0.8)
            
            # Capture state after click
            result = await browser._send_command('Runtime.evaluate', {
                'expression': js_before,
                'returnByValue': True
            }, session_id=browser.session_id)
            state_after = result.get('result', {}).get('value', {})
            
            # Analyze what changed
            url_changed = state_after.get('url') != state_before.get('url')
            modal_appeared = state_after.get('modalCount', 0) > state_before.get('modalCount', 0)
            page_changed = abs(state_after.get('bodyHash', 0) - state_before.get('bodyHash', 0)) > 100
            cart_changed = state_after.get('cartText', '') != state_before.get('cartText', '')
            
            # Determine what happened
            if url_changed:
                return f"✅ Clicked element {index} → Page navigated to {state_after.get('url')}"
            elif modal_appeared:
                return f"✅ Clicked element {index} → Modal/popup appeared"
            elif cart_changed:
                return f"✅ Clicked element {index} → Cart updated (item likely added)"
            elif page_changed:
                return f"✅ Clicked element {index} → Page content changed"
            else:
                # Nothing obvious changed - but click happened
                return f"⚠️ Clicked element {index} - no obvious changes detected (may still have worked)"
                
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return f"❌ Click error: {str(e)}"
    
    # ==============================================================
    # TOOL 3: INPUT_TEXT
    # ==============================================================
    
    @tool
    async def input_text(index: int, text: str) -> str:
        """
        Type text into an input field on the page.
        
        Use this to fill in forms, search boxes, text areas, etc.
        The element must be an input field, textarea, or contenteditable element.
        
        Args:
            index: The index number of the input element (from the elements list)
            text: The text to type into the field
            
        Returns:
            Success message or error if the element is not an input field
            
        Examples:
            - input_text(2, "organic milk") - Type "organic milk" into element 2
            - input_text(0, "test@example.com") - Type email into element 0
        """
        try:
            success = await browser.input_text(index, text)
            if success:
                return f"✅ Typed '{text}' into element {index}"
            else:
                return f"❌ Element {index} not found or not an input field"
        except Exception as e:
            logger.error(f"Input failed: {e}")
            return f"❌ Input error: {str(e)}"
    
    # ==============================================================
    # TOOL 4: EXTRACT
    # ==============================================================
    
    @tool
    async def extract(query: str) -> str:
        """
        Extract specific information from the current page using AI.
        
        Use this to pull out structured data, prices, product details, etc.
        The AI will read the page content and answer your query.
        
        Args:
            query: What information to extract (e.g., "product name and price", 
                   "list all available sizes", "what is the delivery date?")
            
        Returns:
            The extracted information or a message if not found
            
        Examples:
            - extract("product name and price")
            - extract("what is the shipping address shown?")
            - extract("list all items in the cart")
        """
        try:
            # Get page content
            content = await browser.extract_content()
            
            # Limit content length
            if len(content) > 10000:
                content = content[:10000] + "...[truncated]"
            
            # Use LLM to extract information
            prompt = f"""Extract the following information from the page content:

Query: {query}

Page content:
{content}

Provide a concise answer based only on the page content. If the information is not available, say so."""

            # Use LangChain invoke API
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content="You are a helpful assistant that extracts information from web pages."),
                HumanMessage(content=prompt)
            ]
            
            response = await llm.ainvoke(messages)
            extracted = response.content
            
            return f"✅ Extracted: {extracted}"
        except Exception as e:
            logger.error(f"Extract failed: {e}")
            return f"❌ Extract error: {str(e)}"
    
    # ==============================================================
    # TOOL 5: SEND_KEYS
    # ==============================================================
    
    @tool
    async def send_keys(keys: str) -> str:
        """
        Send keyboard keys like Enter, Tab, Escape, or keyboard shortcuts.
        
        Use this to submit forms (Enter), navigate between fields (Tab),
        close popups (Escape), or trigger keyboard shortcuts.
        
        Args:
            keys: The key or key combination to send.
                  Examples: "Enter", "Tab", "Escape", "ArrowDown", "Control+C"
            
        Returns:
            Confirmation that keys were sent
            
        Examples:
            - send_keys("Enter") - Press Enter to submit
            - send_keys("Tab") - Press Tab to move to next field
            - send_keys("Escape") - Press Escape to close modal
        """
        try:
            await browser.send_keys(keys)
            return f"✅ Sent keys: {keys}"
        except Exception as e:
            logger.error(f"Send keys failed: {e}")
            return f"❌ Send keys error: {str(e)}"
    
    # ==============================================================
    # TOOL 6: SCROLL
    # ==============================================================
    
    @tool
    async def scroll(down: bool = True, pages: float = 1.0) -> str:
        """
        Scroll the page up or down to reveal more content.
        
        Use this when you need to see more elements that are below/above
        the current viewport. Useful for long pages with product listings.
        
        Args:
            down: True to scroll down, False to scroll up (default: True)
            pages: How many pages to scroll (1.0 = one full page, 0.5 = half page)
                   (default: 1.0)
            
        Returns:
            Confirmation of scroll action
            
        Examples:
            - scroll(down=True, pages=1.0) - Scroll down one full page
            - scroll(down=False, pages=0.5) - Scroll up half a page
            - scroll() - Scroll down one page (using defaults)
        """
        try:
            await browser.scroll(down=down, pages=pages)
            direction = 'down' if down else 'up'
            return f"✅ Scrolled {direction} {pages} pages"
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return f"❌ Scroll error: {str(e)}"
    
    # ==============================================================
    # TOOL 7: SCREENSHOT
    # ==============================================================
    
    @tool
    async def screenshot() -> str:
        """
        Take a screenshot of the current page.
        
        Use this when you need to visually inspect the page or verify
        what's currently displayed. The screenshot will be captured and
        can be sent to vision-capable models.
        
        Returns:
            Confirmation that screenshot was captured
        """
        try:
            screenshot_b64 = await browser.take_screenshot()
            return f"✅ Screenshot captured (size: {len(screenshot_b64)} chars)"
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"❌ Screenshot error: {str(e)}"
    
    # ==============================================================
    # TOOL 8: ASK_USER
    # ==============================================================
    
    @tool
    def ask_user(question: str) -> str:
        """
        Ask the user a question and wait for their response in the terminal.
        
        Use this when you need user input to make a decision, such as
        selecting from a list of options or confirming an action.
        
        Args:
            question: The question to ask the user
            
        Returns:
            The user's response
            
        Examples:
            - ask_user("Which product would you like to select? (Enter the number)")
            - ask_user("Should I proceed with checkout? (yes/no)")
        """
        try:
            print("\n" + "="*70)
            print("🤔 USER INPUT NEEDED")
            print("="*70)
            print(f"\n{question}\n")
            user_response = input("Your response: ").strip()
            print("="*70 + "\n")
            return f"✅ User responded: {user_response}"
        except Exception as e:
            logger.error(f"Ask user failed: {e}")
            return f"❌ Ask user error: {str(e)}"
    
    # ==============================================================
    # TOOL 9: DONE
    # ==============================================================
    
    @tool
    def done(result: str, success: bool = True) -> str:
        """
        Mark the task as complete and return final results.
        
        Use this when you have successfully completed the user's task
        or when you cannot proceed further. Provide a summary of what
        was accomplished or why the task cannot be completed.
        
        Args:
            result: Summary of what was accomplished or final answer
            success: Whether the task was completed successfully (default: True)
            
        Returns:
            The final result message
            
        Examples:
            - done("Found Kirkland Organic Milk for $12.99", success=True)
            - done("Cannot complete: Sign-in required", success=False)
        """
        status = "✅" if success else "❌"
        return f"{status} TASK COMPLETE: {result}"
    
    # Return all 9 tools (added ask_user tool)
    return [navigate, click, input_text, extract, send_keys, scroll, screenshot, ask_user, done]


# Test function for standalone testing
async def test_tools():
    """Test tools with real browser"""
    from browser import SimpleBrowserSession
    import asyncio
    
    logger.info("Starting browser tools test...")
    browser = SimpleBrowserSession(headless=False)
    await browser.start()
    
    try:
        # Create tools
        tools = create_browser_tools(browser, None, "gpt-4o-mini")
        
        # Test 1: Navigate
        logger.info("\n" + "="*60)
        logger.info("TEST 1: Navigate to Costco")
        logger.info("="*60)
        result = await tools[0].ainvoke({"url": "https://www.costco.com"})
        logger.info(f"Result: {result}")
        await asyncio.sleep(3)
        
        # Test 2: Get elements and click
        logger.info("\n" + "="*60)
        logger.info("TEST 2: Observe page and try clicking")
        logger.info("="*60)
        state = await browser.observe_browser_state()
        logger.info(f"URL: {state['url']}")
        logger.info(f"Title: {state['title']}")
        elements = state['elements'].split('\n')[:10]  # First 10 elements
        logger.info("First 10 elements:")
        for elem in elements:
            logger.info(f"  {elem}")
        
        # Try clicking first element
        if elements:
            logger.info("\nTrying to click element 0...")
            result = await tools[1].ainvoke({"index": 0})
            logger.info(f"Result: {result}")
            await asyncio.sleep(3)
        
        logger.info("\n✅ Tools test completed!")
        
    finally:
        await browser.close()


if __name__ == '__main__':
    # Run standalone test
    import asyncio
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    asyncio.run(test_tools())
