"""
Simple browser session using CDP (Chrome DevTools Protocol).
"""
import asyncio
import json
import logging
import subprocess
import time
from typing import Optional, Dict, Any

import websockets

logger = logging.getLogger(__name__)


class SimpleBrowserSession:
    """A minimal browser controller using CDP"""
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.chrome_process = None
        self.ws = None
        self.cdp_url = None
        self.session_id = None
        self.target_id = None
        self.message_id = 0
        # Cache for mapping indexes to node IDs for proper clicking
        self.element_cache = {}  # {index: node_id}
        
    async def start(self):
        """Start Chrome and connect via CDP"""
        # Start Chrome with remote debugging
        port = 9222
        
        # Try to find Chrome executable
        chrome_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS
            'google-chrome',  # Linux
            'chromium-browser',  # Linux
            'chromium',  # Linux
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',  # Windows
        ]
        
        chrome_path = None
        for path in chrome_paths:
            # Simple check - just use the first path that exists
            import os
            if os.path.exists(path) or path in ['google-chrome', 'chromium-browser', 'chromium']:
                chrome_path = path
                break
        
        if not chrome_path:
            raise RuntimeError("Chrome/Chromium not found. Please install Chrome.")
        
        # Create temporary user data directory
        import tempfile
        user_data_dir = tempfile.mkdtemp(prefix='simple_browser_agent_')
        
        chrome_args = [
            chrome_path,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={user_data_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
            '--no-sandbox',
        ]
        
        if self.headless:
            chrome_args.append('--headless=new')
            
        logger.info(f"Starting Chrome from: {chrome_path}")
        
        self.chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for Chrome to start - try multiple times
        import httpx
        max_retries = 15
        for i in range(max_retries):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f'http://localhost:{port}/json/version', timeout=3.0)
                    data = response.json()
                    self.cdp_url = data['webSocketDebuggerUrl']
                    logger.info(f"✓ Connected to Chrome on port {port}")
                    break
            except Exception as e:
                if i == max_retries - 1:
                    if self.chrome_process:
                        self.chrome_process.terminate()
                    raise RuntimeError(f"Failed to connect to Chrome after {max_retries} attempts: {e}")
                logger.debug(f"Attempt {i+1}/{max_retries}: Waiting for Chrome...")
                continue
        
        # Connect to WebSocket with larger message size limit
        self.ws = await websockets.connect(
            self.cdp_url,
            max_size=10 * 1024 * 1024  # 10MB limit
        )
        
        # Create a target (new page)
        result = await self._send_command('Target.createTarget', {
            'url': 'about:blank'
        })
        self.target_id = result['targetId']
        
        # Attach to the target
        result = await self._send_command('Target.attachToTarget', {
            'targetId': self.target_id,
            'flatten': True
        })
        self.session_id = result['sessionId']
        
        # Enable necessary domains
        await self._send_command('Page.enable', session_id=self.session_id)
        await self._send_command('DOM.enable', session_id=self.session_id)
        await self._send_command('Runtime.enable', session_id=self.session_id)
        
        logger.info("Browser started successfully")
        
    async def _send_command(self, method: str, params: Optional[Dict] = None, session_id: Optional[str] = None) -> Any:
        """Send a CDP command"""
        self.message_id += 1
        message = {
            'id': self.message_id,
            'method': method,
            'params': params or {}
        }
        
        if session_id:
            message['sessionId'] = session_id
            
        await self.ws.send(json.dumps(message))
        
        # Wait for response
        while True:
            response = await self.ws.recv()
            data = json.loads(response)
            
            if data.get('id') == self.message_id:
                if 'error' in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get('result', {})
                
    async def navigate(self, url: str):
        """Navigate to a URL"""
        await self._send_command('Page.navigate', {'url': url}, session_id=self.session_id)
        await asyncio.sleep(2)  # Wait for page load
        
    async def observe_browser_state(self) -> Dict[str, Any]:
        """Get current page state with interactive elements (browser-use approach)"""
        # Clear previous cache
        self.element_cache = {}
        
        # Get page info
        result = await self._send_command('Target.getTargetInfo', 
                                          {'targetId': self.target_id})
        target_info = result['targetInfo']
        
        # BROWSER-USE APPROACH: Get full DOM tree using CDP
        logger.info("📋 Fetching DOM tree...")
        dom_result = await self._send_command('DOM.getDocument', {
            'depth': -1,  # Get entire tree
            'pierce': True  # Pierce through shadow DOM
        }, session_id=self.session_id)
        
        root_node = dom_result['root']
        
        # Get computed styles for visibility checking AND bounds
        logger.info("📋 Getting DOM snapshot for visibility and positions...")
        snapshot_result = await self._send_command('DOMSnapshot.captureSnapshot', {
            'computedStyles': ['display', 'visibility', 'opacity'],
            'includePaintOrder': False,
            'includeDOMRects': True  # ✨ This gives us element positions!
        }, session_id=self.session_id)
        
        # Build lookup for visibility AND positions
        visibility_map = {}
        position_map = {}  # ✨ NEW: Store element positions
        if snapshot_result and 'documents' in snapshot_result:
            for doc in snapshot_result['documents']:
                nodes = doc.get('nodes', {})
                layout = doc.get('layout', {})
                node_index = layout.get('nodeIndex', [])
                bounds = layout.get('bounds', [])
                backend_node_ids = nodes.get('backendNodeId', [])
                
                # FIX: The layout.nodeIndex contains indices into the nodes arrays
                # We need to map layout index -> snapshot node index -> backend node ID
                for i, snapshot_idx in enumerate(node_index):
                    # snapshot_idx is the index into the nodes.backendNodeId array
                    if snapshot_idx >= len(backend_node_ids):
                        continue
                    
                    backend_node_id = backend_node_ids[snapshot_idx]
                    
                    # Simple visibility check based on bounds
                    is_visible = True
                    if i < len(bounds):
                        bound = bounds[i]
                        # Check if element has any size
                        if isinstance(bound, list) and len(bound) >= 6:
                            x = bound[0]
                            y = bound[1]
                            width = bound[2]
                            height = bound[3]
                            is_visible = width > 0 and height > 0
                            
                            # ✨ Store position using backendNodeId
                            if is_visible:
                                position_map[backend_node_id] = {
                                    'x': x,
                                    'y': y,
                                    'width': width,
                                    'height': height
                                }
                    
                    visibility_map[backend_node_id] = is_visible
                
                logger.debug(f"📊 Position map has {len(position_map)} elements with valid positions")
        
        # Extract interactive elements
        interactive_elements = []
        
        def traverse_dom(node, depth=0):
            """Recursively traverse DOM and collect interactive elements"""
            if depth > 50:  # Prevent infinite loops
                return
                
            node_id = node.get('nodeId')
            backend_node_id = node.get('backendNodeId')
            node_type = node.get('nodeType', 0)
            
            # Skip non-element nodes and invisible elements
            if node_type != 1:  # Not an ELEMENT_NODE
                # Process children
                for child in node.get('children', []):
                    traverse_dom(child, depth + 1)
                return
            
            # Check if visible using backendNodeId
            local_name = node.get('localName', '').lower()
            if (backend_node_id not in visibility_map or
                    not visibility_map.get(backend_node_id, False)):
                # Still traverse children even if parent invisible
                for child in node.get('children', []):
                    traverse_dom(child, depth + 1)
                return
            
            # Check if interactive
            interactive_tags = {'a', 'button', 'input', 'textarea', 'select'}
            attributes = {}
            if 'attributes' in node:
                attrs = node['attributes']
                for i in range(0, len(attrs), 2):
                    if i + 1 < len(attrs):
                        attributes[attrs[i]] = attrs[i + 1]
            
            role = attributes.get('role', '')
            onclick = 'onclick' in attributes
            
            is_interactive = (
                local_name in interactive_tags or
                role in ['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem'] or
                onclick
            )
            
            if is_interactive:
                # Build element description
                text = ''
                # Get text content from children
                def get_text(n):
                    texts = []
                    if n.get('nodeType') == 3:  # TEXT_NODE
                        texts.append(n.get('nodeValue', ''))
                    for child in n.get('children', []):
                        texts.extend(get_text(child))
                    return texts
                
                text_parts = get_text(node)
                text = ' '.join(text_parts).strip()[:100]
                
                # Fallback to attributes
                if not text:
                    text = (attributes.get('aria-label') or 
                           attributes.get('title') or
                           attributes.get('placeholder') or
                           attributes.get('value') or
                           attributes.get('alt') or
                           f'{local_name} element')
                
                element_info = {
                    'node_id': node_id,
                    'backend_node_id': backend_node_id,
                    'tag': local_name,
                    'text': text[:80],  # Limit text length
                    'attributes': {
                        k: v[:50] for k, v in attributes.items()
                        if k in ['id', 'class', 'name', 'type',
                                 'href', 'aria-label']
                    },
                    'position': position_map.get(backend_node_id)
                }
                
                interactive_elements.append(element_info)
            
            # Process children (including shadow roots)
            for child in node.get('children', []):
                traverse_dom(child, depth + 1)
            
            # Process shadow roots
            if 'shadowRoots' in node:
                for shadow in node['shadowRoots']:
                    traverse_dom(shadow, depth + 1)
        
        # Start traversal
        traverse_dom(root_node)
        
        # Limit to first 100 elements to avoid overwhelming LLM
        interactive_elements = interactive_elements[:100]
        
        logger.info(f"📋 Found {len(interactive_elements)} interactive elements")
        
        # FALLBACK: Get positions using DOM.getBoxModel for elements without positions
        elements_without_positions = sum(1 for elem in interactive_elements if elem.get('position') is None)
        if elements_without_positions > 0:
            logger.info(f"🔧 Fetching positions for {elements_without_positions} elements using DOM.getBoxModel...")
            for elem in interactive_elements:
                if elem.get('position') is None and elem.get('node_id'):
                    try:
                        box_result = await self._send_command('DOM.getBoxModel', {
                            'nodeId': elem['node_id']
                        }, session_id=self.session_id)
                        
                        if 'model' in box_result and 'content' in box_result['model']:
                            content = box_result['model']['content']
                            # content is [x1, y1, x2, y2, x3, y3, x4, y4] for the 4 corners
                            x = min(content[0], content[2], content[4], content[6])
                            y = min(content[1], content[3], content[5], content[7])
                            width = max(content[0], content[2], content[4], content[6]) - x
                            height = max(content[1], content[3], content[5], content[7]) - y
                            
                            if width > 0 and height > 0:
                                elem['position'] = {
                                    'x': x,
                                    'y': y,
                                    'width': width,
                                    'height': height
                                }
                    except Exception as e:
                        logger.debug(f"Failed to get box model for element: {e}")
            
            elements_with_positions = sum(1 for elem in interactive_elements if elem.get('position') is not None)
            logger.info(f"✅ Now {elements_with_positions}/{len(interactive_elements)} elements have positions")
        
        # Build element descriptions with indexes
        element_lines = []
        for idx, elem in enumerate(interactive_elements):
            # Cache node_id for clicking
            self.element_cache[idx] = elem['node_id']
            
            # Format element
            tag = elem['tag']
            text = elem['text']
            attrs = elem['attributes']
            
            attr_str = ''
            if attrs:
                attr_parts = [f"{k}='{v}'" for k, v in attrs.items() if v]
                if attr_parts:
                    attr_str = ' ' + ' '.join(attr_parts[:3])  # Limit attributes
            
            element_lines.append(f"[{idx}] <{tag}{attr_str}> {text}")
        
        elements_text = '\n'.join(element_lines) if element_lines else 'No interactive elements found'
        
        # HIGHLIGHT ELEMENTS ON PAGE (browser-use approach!)
        if interactive_elements:
            await self._highlight_elements(interactive_elements)
            # Wait briefly for highlights to render
            await asyncio.sleep(0.2)
        
        # AUTO-CAPTURE SCREENSHOT for LLM vision (after highlighting!)
        screenshot_b64 = None
        try:
            screenshot_b64 = await self.take_screenshot()
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
        
        return {
            'url': target_info['url'],
            'title': target_info['title'],
            'elements': elements_text,  # Back to elements list
            'screenshot_available': screenshot_b64 is not None,
            'screenshot': screenshot_b64
        }
    
    async def _highlight_elements(self, elements: list):
        """Highlight interactive elements on the page with orange boxes and index numbers
        
        Uses pre-computed positions from DOMSnapshot.captureSnapshot instead of calling
        DOM.getBoxModel for each element (browser-use approach).
        """
        try:
            # Build elements data for JavaScript using pre-computed positions
            elements_data = []
            for idx, elem in enumerate(elements):
                # ✨ BROWSER-USE APPROACH: Use position from DOM snapshot
                position = elem.get('position')
                
                if position and position['width'] > 0 and position['height'] > 0:
                    elements_data.append({
                        'index': idx,
                        'x': position['x'],
                        'y': position['y'],
                        'width': position['width'],
                        'height': position['height']
                    })
                else:
                    # Element has no valid position (off-screen or hidden)
                    logger.debug(f"Element {idx} has no valid position - skipping highlight")
            
            if not elements_data:
                logger.warning("⚠️ No elements with valid positions to highlight")
                return
            
            logger.info(f"✨ Highlighting {len(elements_data)}/{len(elements)} elements on page")
            
            # Inject highlighting script (from browser-use)
            script = f"""
            (function() {{
                // Remove existing highlights
                const existing = document.getElementById('simple-agent-highlights');
                if (existing) existing.remove();
                
                // Element data
                const elements = {json.dumps(elements_data)};
                
                // Create container
                const container = document.createElement('div');
                container.id = 'simple-agent-highlights';
                container.style.cssText = `
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100vw;
                    height: 100vh;
                    pointer-events: none;
                    z-index: 2147483647;
                    overflow: visible;
                `;
                
                // Add highlight for each element
                elements.forEach(el => {{
                    const highlight = document.createElement('div');
                    highlight.style.cssText = `
                        position: absolute;
                        left: ${{el.x}}px;
                        top: ${{el.y}}px;
                        width: ${{el.width}}px;
                        height: ${{el.height}}px;
                        outline: 2px solid #FF7F27;
                        outline-offset: -2px;
                        background: rgba(255, 127, 39, 0.1);
                        pointer-events: none;
                    `;
                    
                    // Add index label
                    const label = document.createElement('div');
                    label.textContent = el.index;
                    label.style.cssText = `
                        position: absolute;
                        top: -20px;
                        left: 0;
                        background-color: #FF7F27;
                        color: white;
                        padding: 2px 6px;
                        font-size: 12px;
                        font-family: monospace;
                        font-weight: bold;
                        border-radius: 3px;
                        white-space: nowrap;
                    `;
                    
                    highlight.appendChild(label);
                    container.appendChild(highlight);
                }});
                
                document.body.appendChild(container);
                return {{ added: elements.length }};
            }})();
            """
            
            result = await self._send_command('Runtime.evaluate', {
                'expression': script,
                'returnByValue': True
            }, session_id=self.session_id)
            
            if result and 'result' in result and 'value' in result['result']:
                added = result['result']['value'].get('added', 0)
                logger.info(f"✨ Highlighted {added} elements on page")
        
        except Exception as e:
            logger.warning(f"Failed to highlight elements: {e}")
        
    async def click(self, index: int) -> bool:
        """Click an element by index using CDP (browser-use approach)"""
        if index not in self.element_cache:
            logger.error(f"Element index {index} not found in cache")
            return False
        
        node_id = self.element_cache[index]
        
        try:
            # CRITICAL: Scroll element into view first!
            # Use CDP DOM.scrollIntoViewIfNeeded to ensure element is visible
            try:
                await self._send_command('DOM.scrollIntoViewIfNeeded', {
                    'nodeId': node_id
                }, session_id=self.session_id)
                await asyncio.sleep(0.3)  # Wait for scroll animation
                logger.debug(f"Scrolled element [{index}] into view")
            except Exception as scroll_err:
                # Fallback: use JavaScript scrollIntoView
                logger.debug(f"CDP scroll failed, using JS fallback: {scroll_err}")
                await self._send_command('Runtime.evaluate', {
                    'expression': f'''
                        (function() {{
                            const node = document.querySelector('[data-node-id="{node_id}"]');
                            if (node) {{
                                node.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                                return true;
                            }}
                            return false;
                        }})()
                    ''',
                    'returnByValue': True
                }, session_id=self.session_id)
                await asyncio.sleep(0.3)
            
            # Get the box model for the element (AFTER scrolling!)
            box_result = await self._send_command('DOM.getBoxModel', {
                'nodeId': node_id
            }, session_id=self.session_id)
            
            if 'model' not in box_result:
                logger.error(f"No box model for element {index}")
                return False
            
            # Get the center point of the element
            content = box_result['model']['content']
            x = (content[0] + content[4]) / 2
            y = (content[1] + content[5]) / 2
            
            # Dispatch mouse events
            await self._send_command('Input.dispatchMouseEvent', {
                'type': 'mousePressed',
                'x': x,
                'y': y,
                'button': 'left',
                'clickCount': 1
            }, session_id=self.session_id)
            
            await asyncio.sleep(0.1)
            
            await self._send_command('Input.dispatchMouseEvent', {
                'type': 'mouseReleased',
                'x': x,
                'y': y,
                'button': 'left',
                'clickCount': 1
            }, session_id=self.session_id)
            
            await asyncio.sleep(1)  # Wait for action effect
            logger.info(f"✓ Clicked element [{index}] at ({x}, {y})")
            return True
            
        except Exception as e:
            logger.error(f"Click failed for element [{index}]: {e}")
            return False
        
    async def input_text(self, index: int, text: str) -> bool:
        """Input text into an element using CDP and node_id from cache"""
        if index not in self.element_cache:
            logger.error(f"Element index {index} not found in cache")
            return False
        
        node_id = self.element_cache[index]
        
        try:
            # Use CDP DOM.focus to focus the element
            await self._send_command('DOM.focus', {
                'nodeId': node_id
            }, session_id=self.session_id)
            
            await asyncio.sleep(0.1)
            
            # Clear existing text first (select all + delete)
            await self._send_command('Input.dispatchKeyEvent', {
                'type': 'keyDown',
                'key': 'a',
                'code': 'KeyA',
                'modifiers': 2  # Control/Command modifier
            }, session_id=self.session_id)
            
            await self._send_command('Input.dispatchKeyEvent', {
                'type': 'keyUp',
                'key': 'a',
                'code': 'KeyA',
                'modifiers': 2
            }, session_id=self.session_id)
            
            await asyncio.sleep(0.05)
            
            # Type the new text character by character
            for char in text:
                await self._send_command('Input.dispatchKeyEvent', {
                    'type': 'char',
                    'text': char
                }, session_id=self.session_id)
                await asyncio.sleep(0.02)  # Small delay between characters
            
            await asyncio.sleep(0.2)
            logger.info(f"✓ Typed '{text}' into element [{index}]")
            return True
            
        except Exception as e:
            logger.error(f"Input text failed for element [{index}]: {e}")
            return False
        
    async def extract_content(self) -> str:
        """Extract page text content"""
        js = "document.body.innerText"
        result = await self._send_command('Runtime.evaluate', {
            'expression': js,
            'returnByValue': True
        }, session_id=self.session_id)
        
        return result.get('result', {}).get('value', '')
    
    async def send_keys(self, keys: str):
        """Send keyboard keys using CDP Input.dispatchKeyEvent"""
        # Normalize key names
        key_aliases = {
            'enter': 'Enter',
            'tab': 'Tab',
            'escape': 'Escape',
            'esc': 'Escape',
            'ctrl': 'Control',
            'control': 'Control',
            'alt': 'Alt',
            'shift': 'Shift',
            'meta': 'Meta',
            'space': ' ',
            'backspace': 'Backspace',
            'delete': 'Delete',
            'arrowup': 'ArrowUp',
            'arrowdown': 'ArrowDown',
            'arrowleft': 'ArrowLeft',
            'arrowright': 'ArrowRight',
        }
        
        normalized = key_aliases.get(keys.lower(), keys)
        
        # Handle key combinations like "Control+A"
        if '+' in normalized:
            parts = normalized.split('+')
            modifiers = parts[:-1]
            main_key = parts[-1]
            
            # Calculate modifier bitmask
            modifier_value = 0
            modifier_map = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
            for mod in modifiers:
                modifier_value |= modifier_map.get(mod, 0)
            
            # Press modifiers
            for mod in modifiers:
                await self._dispatch_key_event('rawKeyDown', mod)
            
            # Press main key WITH modifiers
            await self._dispatch_key_event('keyDown', main_key, modifier_value)
            await self._dispatch_key_event('keyUp', main_key, modifier_value)
            
            # Release modifiers
            for mod in reversed(modifiers):
                await self._dispatch_key_event('keyUp', mod)
        else:
            # Simple key press
            await self._dispatch_key_event('keyDown', normalized)
            await self._dispatch_key_event('keyUp', normalized)
        
        await asyncio.sleep(0.3)  # Wait for key effect
    
    async def _dispatch_key_event(self, event_type: str, key: str, modifiers: int = 0):
        """Dispatch a keyboard event via CDP"""
        # Get key code
        key_codes = {
            'Enter': 13,
            'Tab': 9,
            'Escape': 27,
            'Backspace': 8,
            'Delete': 46,
            ' ': 32,
            'ArrowUp': 38,
            'ArrowDown': 40,
            'ArrowLeft': 37,
            'ArrowRight': 39,
            'Control': 17,
            'Alt': 18,
            'Shift': 16,
            'Meta': 91,
        }
        
        params = {
            'type': event_type,
        }
        
        # Add key info
        if key in key_codes:
            params['key'] = key
            params['code'] = key
            params['windowsVirtualKeyCode'] = key_codes[key]
            params['nativeVirtualKeyCode'] = key_codes[key]
        else:
            # Regular character
            params['key'] = key
            params['code'] = f'Key{key.upper()}' if len(key) == 1 else key
            params['text'] = key
            params['unmodifiedText'] = key
            params['windowsVirtualKeyCode'] = ord(key.upper()) if len(key) == 1 else 0
        
        if modifiers:
            params['modifiers'] = modifiers
        
        await self._send_command('Input.dispatchKeyEvent', params, session_id=self.session_id)
    
    async def scroll(self, down: bool = True, pages: float = 1.0):
        """Scroll the page using mouse wheel"""
        # Get viewport height
        try:
            metrics = await self._send_command('Page.getLayoutMetrics', session_id=self.session_id)
            viewport_height = metrics.get('cssVisualViewport', {}).get('clientHeight', 1000)
        except:
            viewport_height = 1000  # Fallback
        
        # Calculate scroll amount
        pixels = int(pages * viewport_height)
        if not down:
            pixels = -pixels
        
        # Dispatch mouse wheel event
        await self._send_command('Input.dispatchMouseEvent', {
            'type': 'mouseWheel',
            'x': 400,
            'y': 400,
            'deltaX': 0,
            'deltaY': pixels,
        }, session_id=self.session_id)
        
        await asyncio.sleep(0.5)  # Wait for scroll to complete
    
    async def take_screenshot(self) -> str:
        """Take a screenshot and return base64 encoded image"""
        result = await self._send_command('Page.captureScreenshot', {
            'format': 'jpeg',
            'quality': 60,
        }, session_id=self.session_id)
        
        return result['data']  # Already base64 encoded
        
    async def close(self):
        """Close browser"""
        if self.ws:
            await self.ws.close()
        if self.chrome_process:
            self.chrome_process.terminate()
            self.chrome_process.wait()

