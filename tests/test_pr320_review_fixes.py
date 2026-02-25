# Tests for PR #320 review fixes.
# Created: 2026-02-25
#
# Covers:
# - OAuthClient.matches_redirect_uri() (RFC 8252 compliance)
# - ToolRegistry parameter validation (None values, missing keys)
# - SSE session filter logic (strict session_key filtering)
# - SSE events envelope shape consistency
# - OpenAI Agents _extract_tool_name() helper
# - __main__.py cleanup exception scope

from types import SimpleNamespace

import pytest

from pocketpaw.api.oauth2.models import OAuthClient


# =============================================================================
# OAuthClient.matches_redirect_uri — RFC 8252 Section 7.3
# =============================================================================


class TestOAuthRedirectUriMatching:
    """Test RFC 8252 loopback redirect URI matching."""

    def _make_client(self, redirect_uris: list[str]) -> OAuthClient:
        return OAuthClient(
            client_id="test",
            client_name="Test",
            redirect_uris=redirect_uris,
        )

    def test_exact_match(self):
        client = self._make_client(["tauri://oauth-callback"])
        assert client.matches_redirect_uri("tauri://oauth-callback") is True

    def test_exact_match_no_match(self):
        client = self._make_client(["tauri://oauth-callback"])
        assert client.matches_redirect_uri("https://evil.com/callback") is False

    def test_localhost_port_ignored(self):
        """RFC 8252: loopback redirects may use any port."""
        client = self._make_client(["http://localhost:3000/callback"])
        assert client.matches_redirect_uri("http://localhost:9999/callback") is True

    def test_localhost_different_path_rejected(self):
        client = self._make_client(["http://localhost:3000/callback"])
        assert client.matches_redirect_uri("http://localhost:3000/evil") is False

    def test_127_0_0_1_port_ignored(self):
        """RFC 8252: 127.0.0.1 loopback also ignores port."""
        client = self._make_client(["http://127.0.0.1:8080/"])
        assert client.matches_redirect_uri("http://127.0.0.1:12345/") is True

    def test_non_localhost_port_must_match(self):
        """Non-loopback URIs should NOT get port-agnostic matching."""
        client = self._make_client(["https://example.com:443/callback"])
        assert client.matches_redirect_uri("https://example.com:8443/callback") is False

    def test_localhost_empty_path_normalization(self):
        """Empty path normalizes to / for comparison."""
        client = self._make_client(["http://localhost:3000"])
        assert client.matches_redirect_uri("http://localhost:5000/") is True
        assert client.matches_redirect_uri("http://localhost:5000") is True

    def test_https_localhost_not_matched(self):
        """Only http://localhost gets RFC 8252 treatment, not https."""
        client = self._make_client(["https://localhost:3000/callback"])
        # https is not "http", so the loopback rule shouldn't apply
        assert client.matches_redirect_uri("https://localhost:9999/callback") is False


# =============================================================================
# ToolRegistry parameter validation
# =============================================================================


class TestToolRegistryValidation:
    """Test that ToolRegistry.execute() validates required params properly."""

    @pytest.fixture
    def registry(self):
        from pocketpaw.tools.registry import ToolRegistry

        return ToolRegistry()

    @pytest.fixture
    def mock_tool(self):
        """Create a mock tool with required 'path' parameter."""
        from pocketpaw.tools.protocol import BaseTool

        class PathTool(BaseTool):
            @property
            def name(self) -> str:
                return "read_file"

            @property
            def description(self) -> str:
                return "Read a file"

            @property
            def parameters(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                    },
                    "required": ["path"],
                }

            async def execute(self, **params) -> str:
                return f"Read: {params['path']}"

        return PathTool()

    @pytest.mark.asyncio
    async def test_missing_required_param(self, registry, mock_tool):
        registry.register(mock_tool)
        result = await registry.execute("read_file")
        assert "Missing required parameter(s)" in result
        assert "path" in result

    @pytest.mark.asyncio
    async def test_none_required_param_rejected(self, registry, mock_tool):
        """Passing path=None should be treated as missing."""
        registry.register(mock_tool)
        result = await registry.execute("read_file", path=None)
        assert "Missing required parameter(s)" in result
        assert "path" in result

    @pytest.mark.asyncio
    async def test_valid_param_passes(self, registry, mock_tool):
        registry.register(mock_tool)
        result = await registry.execute("read_file", path="/tmp/test.txt")
        assert result == "Read: /tmp/test.txt"


# =============================================================================
# SSE session filter
# =============================================================================


class TestSSESessionFilter:
    """Test that the _on_system callback in _APISessionBridge filters correctly.

    The filter logic: events must have a session_key that ends with ":chat_id".
    Events without a session_key (global events like health/daemon) should be
    blocked from individual chat SSE streams.
    """

    def _should_pass_filter(self, chat_id: str, data: dict) -> bool:
        """Replicate the filter logic from chat.py _on_system."""
        sk = data.get("session_key", "")
        # This matches the FIXED logic: `if not sk or not sk.endswith(...): return`
        # So should_pass is True only when sk is truthy AND ends with :chat_id
        return bool(sk) and sk.endswith(f":{chat_id}")

    def test_matching_session_passes(self):
        """Events with matching session_key should be delivered."""
        assert self._should_pass_filter(
            "abc123", {"session_key": "websocket:abc123", "name": "shell"}
        )

    def test_different_session_blocked(self):
        """Events with a different session_key should be blocked."""
        assert not self._should_pass_filter(
            "abc123", {"session_key": "websocket:other_session", "name": "shell"}
        )

    def test_missing_session_key_blocked(self):
        """Events without session_key should be blocked (not leaked to all clients)."""
        assert not self._should_pass_filter("abc123", {"name": "health_update"})

    def test_empty_session_key_blocked(self):
        """Events with empty string session_key should be blocked."""
        assert not self._should_pass_filter(
            "abc123", {"session_key": "", "name": "daemon_event"}
        )

    def test_chat_py_has_strict_filter(self):
        """Verify the actual source code uses the strict filter."""
        from pathlib import Path

        chat_path = (
            Path(__file__).parent.parent / "src" / "pocketpaw" / "api" / "v1" / "chat.py"
        )
        source = chat_path.read_text()
        # The strict filter: block if session_key is missing or doesn't match
        assert "if not sk or not sk.endswith" in source


# =============================================================================
# SSE envelope shape consistency
# =============================================================================


class TestSSEEnvelopeShape:
    """Verify both SSE endpoints use consistent envelope keys."""

    def test_events_sse_uses_event_key(self):
        """The events.py SSE stream should use 'event' not 'event_type' in envelope."""
        from pathlib import Path

        events_path = (
            Path(__file__).parent.parent / "src" / "pocketpaw" / "api" / "v1" / "events.py"
        )
        source = events_path.read_text()
        # After our fix, the dict should use "event", not "event_type"
        assert '"event": evt.event_type' in source
        assert '"event_type": evt.event_type' not in source

    def test_chat_sse_uses_event_key(self):
        """The chat.py SSE stream should use 'event' key in envelope."""
        from pathlib import Path

        chat_path = (
            Path(__file__).parent.parent / "src" / "pocketpaw" / "api" / "v1" / "chat.py"
        )
        source = chat_path.read_text()
        # chat.py has always used "event" key
        assert '"event": "chunk"' in source or '"event": "tool_start"' in source


# =============================================================================
# OpenAI Agents _extract_tool_name
# =============================================================================


class TestExtractToolName:
    """Test the _extract_tool_name helper in OpenAI Agents backend."""

    def _call(self, item):
        from pocketpaw.agents.openai_agents import OpenAIAgentsBackend

        return OpenAIAgentsBackend._extract_tool_name(item)

    def test_function_tool_call(self):
        """Extract name from a function tool call via raw_item.function.name."""
        item = SimpleNamespace(
            raw_item=SimpleNamespace(function=SimpleNamespace(name="web_search"))
        )
        assert self._call(item) == "web_search"

    def test_builtin_tool_type(self):
        """Extract name from built-in tool type (computer_use, file_search, etc.)."""
        item = SimpleNamespace(raw_item=SimpleNamespace(type="computer_use"))
        assert self._call(item) == "Computer"

    def test_file_search_type(self):
        item = SimpleNamespace(raw_item=SimpleNamespace(type="file_search"))
        assert self._call(item) == "File Search"

    def test_code_interpreter_type(self):
        item = SimpleNamespace(raw_item=SimpleNamespace(type="code_interpreter"))
        assert self._call(item) == "Code Interpreter"

    def test_unknown_type_title_cased(self):
        item = SimpleNamespace(raw_item=SimpleNamespace(type="custom_tool"))
        assert self._call(item) == "Custom Tool"

    def test_direct_name_attribute_fallback(self):
        """If raw_item doesn't have function or type, try direct .name."""
        item = SimpleNamespace(name="direct_tool")
        assert self._call(item) == "direct_tool"

    def test_no_attributes_returns_fallback(self):
        """If nothing is found, return the fallback 'Tool'."""
        item = SimpleNamespace()
        result = self._call(item)
        assert result == "Tool"

    def test_none_item_returns_fallback(self):
        """None should not crash, returns fallback."""
        result = self._call(None)
        assert result == "Tool"


# =============================================================================
# Ctrl+C cleanup — exception scope
# =============================================================================


class TestMainExceptionHandling:
    """Verify __main__.py cleanup only catches expected exceptions."""

    def test_finally_block_catches_narrow_exceptions(self):
        """The finally block should catch RuntimeError and OSError, not bare Exception."""
        from pathlib import Path

        main_path = Path(__file__).parent.parent / "src" / "pocketpaw" / "__main__.py"
        source = main_path.read_text()
        # The shutdown finally block should use narrow exception catch
        assert "except (RuntimeError, OSError):" in source
        # Find the shutdown block specifically — it should NOT use bare Exception
        shutdown_idx = source.find("shutdown_all()")
        assert shutdown_idx > 0
        # Get the except clause after shutdown_all()
        after_shutdown = source[shutdown_idx:]
        first_except = after_shutdown[after_shutdown.find("except") :]
        # The first except after shutdown_all should be the narrow one
        assert first_except.startswith("except (RuntimeError, OSError):")
