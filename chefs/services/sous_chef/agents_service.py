# chefs/services/sous_chef/agents_service.py
"""
Sous Chef service using OpenAI Agents SDK.

Drop-in replacement for SousChefService that uses the Agents SDK
with Groq via LiteLLM as the backend.
"""

import logging
import re
from typing import Dict, Any, Optional, Generator

from .agents_factory import AgentsSousChefFactory
from .html_converter import markdown_to_html
from .thread_manager import ThreadManager
from .tools.agents_tools import ToolContext

logger = logging.getLogger(__name__)

# Check if Agents SDK is available
try:
    from agents import Runner
    from agents.lifecycle import RunHooksBase
    AGENTS_SDK_AVAILABLE = True
except ImportError:
    AGENTS_SDK_AVAILABLE = False
    Runner = None
    RunHooksBase = None


class ActionCaptureHooks(RunHooksBase if RunHooksBase else object):
    """
    Captures action-type tool results for frontend rendering.

    When tools return results with `render_as_action: True`, this hook
    captures them so they can be merged into the response as action blocks.
    """

    def __init__(self):
        self.captured_actions = []

    async def on_tool_end(self, context, agent, tool, result) -> None:
        """Capture tool results that should render as actions."""
        import json
        tool_name = getattr(tool, 'name', 'unknown')
        logger.info(f"[ActionCaptureHooks] on_tool_end called for tool: {tool_name}")
        logger.info(f"[ActionCaptureHooks] Tool result type: {type(result).__name__}")

        # Handle result - it may be a dict or a JSON string
        data = None
        if isinstance(result, dict):
            data = result
        elif isinstance(result, str):
            try:
                data = json.loads(result)
            except (json.JSONDecodeError, TypeError) as e:
                logger.info(f"[ActionCaptureHooks] Failed to parse result as JSON: {e}")
                return
        else:
            logger.info(f"[ActionCaptureHooks] Unexpected result type: {type(result)}")
            return

        logger.info(f"[ActionCaptureHooks] Parsed data: {data}")
        if isinstance(data, dict) and (
            data.get("render_as_action")
            or data.get("render_as_payment_preview")
            or data.get("render_as_payment_confirmation")
        ):
            logger.info(f"[ActionCaptureHooks] CAPTURED action: {data}")
            self.captured_actions.append(data)
        else:
            logger.info(f"[ActionCaptureHooks] Not an action (render_as_action={data.get('render_as_action') if isinstance(data, dict) else 'N/A'})")


class AgentsSousChefService:
    """
    Sous Chef service using OpenAI Agents SDK.
    
    This is a drop-in replacement for SousChefService that uses
    the Agents SDK for agent orchestration instead of manual
    Groq API calls.
    
    Usage:
        service = AgentsSousChefService(chef_id=1, channel="telegram")
        result = service.send_message("What orders do I have?")
    """
    
    def __init__(
        self,
        chef_id: int,
        channel: str = "web",
        family_id: Optional[int] = None,
        family_type: Optional[str] = None,
        client_type: str = "web",
    ):
        """
        Initialize the service.

        Args:
            chef_id: ID of the chef
            channel: Channel type ('web', 'telegram', 'line', 'api')
            family_id: Optional family/customer ID
            family_type: 'customer' or 'lead' if family_id provided
            client_type: Client type for response formatting ('web', 'ios', 'android')
        """
        if not AGENTS_SDK_AVAILABLE:
            raise ImportError(
                "OpenAI Agents SDK not installed. "
                "Run: pip install 'openai-agents[litellm]>=0.6.0'"
            )

        self.chef_id = chef_id
        self.channel = channel
        self.family_id = family_id
        self.family_type = family_type
        self.client_type = client_type
        
        # Initialize factory
        self.factory = AgentsSousChefFactory(
            chef_id=chef_id,
            channel=channel,
            family_id=family_id,
            family_type=family_type,
        )
        
        # Initialize thread manager
        self.thread_manager = ThreadManager(
            chef_id=chef_id,
            family_id=family_id,
            family_type=family_type,
            channel=channel,
        )
        
        # Create agent
        self.agent = self.factory.create_agent()
        
        # Set tool context
        ToolContext.set(
            chef=self.factory.chef,
            customer=self.factory.customer,
            lead=self.factory.lead,
            channel=channel,
        )
    
    def send_message(self, message: str) -> Dict[str, Any]:
        """
        Send a message and get a response (synchronous).

        Args:
            message: The user's message

        Returns:
            Dict with status, message, and thread_id
        """
        try:
            # Get or create thread
            thread = self.thread_manager.get_or_create_thread()

            # Build message with history context
            # TODO: Investigate how to pass history to Agents SDK
            # For now, we include recent history in the message
            history_context = self._get_history_context()

            if history_context:
                full_message = f"{history_context}\n\nUser: {message}"
            else:
                full_message = message

            # Run agent
            result = Runner.run_sync(self.agent, full_message)
            response = result.final_output or "I processed your request."

            # Save turn to thread
            self.thread_manager.save_turn(message, response)

            return {
                "status": "success",
                "message": response,
                "thread_id": thread.id,
            }

        except Exception as e:
            logger.error(f"AgentsSousChefService error: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "thread_id": getattr(self.thread_manager, 'thread_id', None),
            }

    def send_structured_message(self, message: str) -> Dict[str, Any]:
        """
        Send message and get structured response appropriate for the channel.

        Web/API: {status, content: {blocks: [...]}, thread_id}
        Telegram/Line: {status, message: "<markdown>", thread_id}

        Args:
            message: The user's message

        Returns:
            Dict with status and channel-appropriate response format
        """
        if self.channel in ("telegram", "line"):
            # For chat platforms, use regular send_message (markdown output)
            return self.send_message(message)

        # For web/api, generate structured JSON blocks
        return self._send_structured_web(message)

    def _send_structured_web(self, message: str) -> Dict[str, Any]:
        """
        Generate structured JSON response for web channel.

        Args:
            message: The user's message

        Returns:
            Dict with status, content (blocks), and thread_id
        """
        try:
            thread = self.thread_manager.get_or_create_thread()

            # Build message with history context
            history_context = self._get_history_context()
            if history_context:
                full_message = f"{history_context}\n\nUser: {message}"
            else:
                full_message = message

            # Run agent with hooks to capture action tool results
            hooks = ActionCaptureHooks()
            logger.info(f"[_send_structured_web] Running agent with message: {message[:100]}...")
            result = Runner.run_sync(self.agent, full_message, hooks=hooks)
            agent_response = result.final_output or ""
            logger.info(f"[_send_structured_web] Agent response: {agent_response[:500]}...")
            logger.info(f"[_send_structured_web] Captured actions: {hooks.captured_actions}")

            # Convert to structured blocks with HTML, including captured actions
            structured_content = self._convert_to_blocks_html(
                agent_response,
                actions=hooks.captured_actions
            )
            logger.info(f"[_send_structured_web] Structured HTML content: {structured_content}")

            # Save to thread
            self.thread_manager.save_turn(message, agent_response)

            return {
                "status": "success",
                "content": structured_content,
                "thread_id": thread.id,
            }

        except Exception as e:
            logger.error(f"Structured message error: {e}", exc_info=True)
            # Return success with fallback so UI doesn't break
            return {
                "status": "success",
                "content": {
                    "blocks": [
                        {"type": "html", "content": "I ran into an issue. Could you try again?"}
                    ]
                },
                "thread_id": getattr(self.thread_manager, 'thread_id', None),
            }

    def _normalize_markdown(self, text: str) -> str:
        """
        Normalize markdown output - fix missing newlines from LLM.

        Some LLMs (especially via Groq/LiteLLM) output markdown without
        proper line breaks. This method fixes common issues before
        sending to the frontend.

        Args:
            text: Raw text from LLM

        Returns:
            Normalized text with proper newlines
        """
        import re

        if not text:
            return text

        result = text

        # Convert <br> tags to newlines
        result = re.sub(r'<br\s*/?>', '\n', result, flags=re.IGNORECASE)

        # Fix inline list items by processing line by line
        # This avoids breaking table cells like "| Item - Value |"
        lines = result.split('\n')
        fixed_lines = []
        for line in lines:
            # Skip table rows (lines that start and end with |)
            if line.strip().startswith('|') and line.strip().endswith('|'):
                fixed_lines.append(line)
            else:
                # Convert " - " to newline + "- " for list items
                # But only after sentence-ending punctuation or after a previous list item
                fixed_line = re.sub(r'([.:!?])\s+-\s+', r'\1\n\n- ', line)
                # Then handle any remaining " - " sequences that look like list continuations
                fixed_line = re.sub(r'\s+-\s+', '\n- ', fixed_line)
                fixed_lines.append(fixed_line)
        result = '\n'.join(fixed_lines)

        # Fix headers not on their own line
        result = re.sub(r'([^\n])(#{1,6}\s+)', r'\1\n\n\2', result)

        # Fix table rows on single line: "| a | b | | c | d |" -> separate lines
        result = re.sub(r'(\|[^|\n]+\|)\s*(?=\|)', r'\1\n', result)

        # Clean up excessive newlines (more than 2 in a row)
        result = re.sub(r'\n{3,}', '\n\n', result)

        # Remove markdown horizontal rules (---) that don't render well in chat
        result = re.sub(r'\s*-{3,}\s*', '\n\n', result)

        return result

    def _convert_to_blocks(self, text: str, actions: list = None) -> Dict[str, Any]:
        """
        Convert text response to structured blocks, including captured actions.

        Args:
            text: The agent's text response
            actions: List of action dicts captured from tool results via RunHooks

        Returns:
            Dict with blocks array containing text and action blocks
        """
        normalized = self._normalize_markdown(text)
        blocks = []

        # Clean up text (remove any JSON artifacts that might be in the response)
        remaining_text = normalized
        remaining_text = re.sub(r'Executing navigation[…\.]*\s*', '', remaining_text)
        remaining_text = re.sub(r'\s*```json\s*```\s*', '', remaining_text)
        # Remove "json { ... }" patterns (tool result echoes)
        remaining_text = re.sub(r'\s*json\s*\{[^}]*\}\s*', ' ', remaining_text)
        # Remove standalone JSON objects with tool-result keys
        remaining_text = re.sub(
            r'\s*\{\s*"(?:tab_name|action_type|status|render_as_action|render_as_payment)"[^}]*\}\s*',
            ' ',
            remaining_text
        )
        remaining_text = remaining_text.strip()

        # Add text block if there's content
        if remaining_text:
            blocks.append({"type": "text", "content": remaining_text})

        # Add action blocks from captured tool results (via RunHooks)
        for action in (actions or []):
            if action.get("render_as_payment_preview"):
                blocks.append({
                    "type": "payment_preview",
                    "preview": action.get("preview", {}),
                    "note": action.get("note", ""),
                })
            elif action.get("render_as_payment_confirmation"):
                blocks.append({
                    "type": "payment_confirmation",
                    "payment_link": action.get("payment_link", {}),
                    "summary": action.get("summary", ""),
                    "warning": action.get("warning"),
                })
            else:
                blocks.append({
                    "type": "action",
                    "action_type": action.get("action_type"),
                    "label": action.get("label", f"Go to {action.get('tab', 'dashboard')}"),
                    "payload": {
                        "tab": action.get("tab"),
                        "form_type": action.get("form_type"),
                        "values": action.get("values"),
                    },
                    "reason": action.get("reason", ""),
                    "auto_execute": action.get("auto_execute", False),
                })

        if not blocks:
            blocks.append({"type": "text", "content": ""})

        return {"blocks": blocks}

    def _convert_to_blocks_html(self, text: str, actions: list = None) -> Dict[str, Any]:
        """
        Convert text response to structured blocks with HTML content.

        Similar to _convert_to_blocks but converts markdown to HTML for richer
        rendering on web and mobile clients.

        Args:
            text: The agent's text response (markdown)
            actions: List of action dicts captured from tool results via RunHooks

        Returns:
            Dict with blocks array containing html and action blocks
        """
        normalized = self._normalize_markdown(text)
        blocks = []

        # Clean up text (remove any JSON artifacts that might be in the response)
        remaining_text = normalized
        remaining_text = re.sub(r'Executing navigation[…\.]*\s*', '', remaining_text)
        remaining_text = re.sub(r'\s*```json\s*```\s*', '', remaining_text)
        # Remove "json { ... }" patterns (tool result echoes)
        remaining_text = re.sub(r'\s*json\s*\{[^}]*\}\s*', ' ', remaining_text)
        # Remove standalone JSON objects with tool-result keys
        remaining_text = re.sub(
            r'\s*\{\s*"(?:tab_name|action_type|status|render_as_action|render_as_payment)"[^}]*\}\s*',
            ' ',
            remaining_text
        )
        remaining_text = remaining_text.strip()

        # Add HTML block if there's content
        if remaining_text:
            html_content = markdown_to_html(remaining_text)
            blocks.append({"type": "html", "content": html_content})

        # Add action blocks from captured tool results (via RunHooks)
        for action in (actions or []):
            if action.get("render_as_payment_preview"):
                blocks.append({
                    "type": "payment_preview",
                    "preview": action.get("preview", {}),
                    "note": action.get("note", ""),
                })
            elif action.get("render_as_payment_confirmation"):
                blocks.append({
                    "type": "payment_confirmation",
                    "payment_link": action.get("payment_link", {}),
                    "summary": action.get("summary", ""),
                    "warning": action.get("warning"),
                })
            else:
                blocks.append({
                    "type": "action",
                    "action_type": action.get("action_type"),
                    "label": action.get("label", f"Go to {action.get('tab', 'dashboard')}"),
                    "payload": {
                        "tab": action.get("tab"),
                        "form_type": action.get("form_type"),
                        "values": action.get("values"),
                    },
                    "reason": action.get("reason", ""),
                    "auto_execute": action.get("auto_execute", False),
                })

        if not blocks:
            blocks.append({"type": "html", "content": ""})

        return {"blocks": blocks}

    async def send_message_async(self, message: str) -> Dict[str, Any]:
        """
        Send a message and get a response (asynchronous).
        
        Args:
            message: The user's message
        
        Returns:
            Dict with status, message, and thread_id
        """
        try:
            thread = self.thread_manager.get_or_create_thread()
            
            history_context = self._get_history_context()
            if history_context:
                full_message = f"{history_context}\n\nUser: {message}"
            else:
                full_message = message
            
            result = await Runner.run(self.agent, full_message)
            response = result.final_output or "I processed your request."
            
            self.thread_manager.save_turn(message, response)
            
            return {
                "status": "success",
                "message": response,
                "thread_id": thread.id,
            }
            
        except Exception as e:
            logger.error(f"AgentsSousChefService async error: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "thread_id": getattr(self.thread_manager, 'thread_id', None),
            }
    
    def stream_message(self, message: str) -> Generator[Dict[str, Any], None, None]:
        """
        Stream a response (for web UI).

        Note: Agents SDK streaming support may be limited.
        Falls back to non-streaming if not available.

        Args:
            message: The user's message

        Yields:
            Dict events with type and content
        """
        try:
            thread = self.thread_manager.get_or_create_thread()

            # Check if streaming is supported
            if hasattr(Runner, 'run_streamed'):
                # Use streaming if available
                history_context = self._get_history_context()
                if history_context:
                    full_message = f"{history_context}\n\nUser: {message}"
                else:
                    full_message = message

                # TODO: Implement proper streaming when SDK supports it
                # For now, fall back to sync with hooks to capture actions
                import json as json_module
                hooks = ActionCaptureHooks()
                logger.info(f"[stream_message] Running agent with message: {message[:100]}...")
                result = Runner.run_sync(self.agent, full_message, hooks=hooks)
                response = result.final_output or ""
                logger.info(f"[stream_message] Agent response: {response[:500]}...")
                logger.info(f"[stream_message] Captured actions: {hooks.captured_actions}")

                # Convert markdown to HTML for all clients
                normalized = self._normalize_markdown(response)
                html_content = markdown_to_html(normalized)

                # For iOS/Android clients, return HTML directly (no JSON wrapper)
                if self.client_type in ("ios", "android"):
                    logger.info(f"[stream_message] Sending HTML for {self.client_type} client")
                    yield {"type": "text", "content": html_content}
                else:
                    # For web, convert response to structured blocks with HTML content
                    structured = self._convert_to_blocks_html(response, actions=hooks.captured_actions)
                    logger.info(f"[stream_message] Structured HTML content: {structured}")
                    yield {"type": "text", "content": json_module.dumps(structured)}

                self.thread_manager.save_turn(message, response)
                yield {"type": "done", "thread_id": thread.id}
            else:
                # Fallback to send_message and convert to HTML
                import json as json_module

                result = self.send_message(message)
                raw_text = result.get("message", "")
                normalized = self._normalize_markdown(raw_text)
                html_content = markdown_to_html(normalized)

                # For iOS/Android clients, return HTML directly
                if self.client_type in ("ios", "android"):
                    yield {"type": "text", "content": html_content}
                    yield {"type": "done", "thread_id": result.get("thread_id")}
                else:
                    # For web, wrap in structured blocks format
                    structured = {"blocks": [{"type": "html", "content": html_content}]}
                    yield {"type": "text", "content": json_module.dumps(structured)}
                    yield {"type": "done", "thread_id": result.get("thread_id")}
                
        except Exception as e:
            logger.error(f"AgentsSousChefService stream error: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}
    
    def _get_history_context(self, max_turns: int = 5) -> str:
        """
        Get recent conversation history as context string.
        
        Args:
            max_turns: Maximum conversation turns to include
        
        Returns:
            Formatted history string or empty string
        """
        try:
            history = self.thread_manager.get_history(limit=max_turns * 2)
            
            if not history:
                return ""
            
            # Format as conversation
            lines = ["Recent conversation:"]
            for msg in history[-max_turns * 2:]:
                role = "User" if msg.get("role") == "chef" else "Assistant"
                content = msg.get("content", "")[:500]  # Truncate long messages
                lines.append(f"{role}: {content}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.warning(f"Failed to get history context: {e}")
            return ""
    
    def new_conversation(self) -> Dict[str, Any]:
        """
        Start a new conversation (clear history).
        
        Returns:
            Dict with status and new thread_id
        """
        thread = self.thread_manager.new_conversation()
        return {
            "status": "success",
            "thread_id": thread.id,
            "family_name": thread.family_name,
        }
    
    def get_history(self) -> list:
        """
        Get conversation history.
        
        Returns:
            List of message dicts
        """
        return self.thread_manager.get_history()
