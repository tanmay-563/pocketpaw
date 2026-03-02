# Tests for the paw MCP server (Phase 2 of PAW-SPEC).
# Created: 2026-03-02
# Covers: _ensure_soul, _ensure_config, create_server smoke-test,
#         all tool/resource/prompt functions via captured closures,
#         run_server entry-point existence.
# Strategy: mock fastmcp so create_server() runs even when fastmcp is not
#   installed. A CaptureMCP helper records every @mcp.tool / @mcp.resource /
#   @mcp.prompt decoration so we can call the inner async functions directly
#   while controlling _soul and _config at module level.

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# CaptureMCP — minimal FastMCP stand-in that records decorated functions
# ---------------------------------------------------------------------------


class CaptureMCP:
    """Minimal FastMCP stand-in. Records decorated async functions by name."""

    def __init__(self, *args, **kwargs):
        self._tools: dict = {}
        self._resources: dict = {}
        self._prompts: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator

    def resource(self, uri: str):
        def decorator(fn):
            self._resources[uri] = fn
            return fn
        return decorator

    def prompt(self):
        def decorator(fn):
            self._prompts[fn.__name__] = fn
            return fn
        return decorator

    def run(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_soul():
    soul = MagicMock()
    soul.name = "TestSoul"
    soul.did = "did:soul:test123"
    soul.archetype = "Test Archetype"
    soul.state = MagicMock(mood="curious", energy=85, social_battery=90)
    soul.self_model = None
    soul.remember = AsyncMock()
    soul.recall = AsyncMock(return_value=[])
    soul.observe = AsyncMock()
    soul.edit_core_memory = AsyncMock()
    soul.save = AsyncMock()
    soul.export = AsyncMock()
    soul.to_system_prompt = MagicMock(return_value="Test system prompt")
    return soul


@pytest.fixture
def mock_config(tmp_path):
    config = MagicMock()
    config.project_root = tmp_path
    config.soul_name = "TestSoul"
    config.provider = "claude"
    config.soul_path = None
    config.default_soul_path = tmp_path / ".paw" / "testsoul.soul"
    return config


@pytest.fixture
def captured_server(mock_soul, mock_config):
    """Build the MCP server with a mock FastMCP, return (capture_mcp, server_module)."""
    # Build a fake fastmcp module
    fake_fastmcp = types.ModuleType("fastmcp")
    capture = CaptureMCP()
    fake_fastmcp.FastMCP = lambda *a, **kw: capture

    with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
        # Remove cached server module to force reimport with our mock
        if "pocketpaw.paw.mcp.server" in sys.modules:
            del sys.modules["pocketpaw.paw.mcp.server"]
        if "pocketpaw.paw.mcp" in sys.modules:
            del sys.modules["pocketpaw.paw.mcp"]

        from pocketpaw.paw.mcp import server as server_module

        # Set module-level state
        server_module._soul = mock_soul
        server_module._config = mock_config

        # Run create_server to register all tools/resources/prompts
        server_module.create_server()

        yield capture, server_module

    # Cleanup: remove the module so subsequent imports start fresh
    for key in list(sys.modules.keys()):
        if "pocketpaw.paw.mcp" in key:
            del sys.modules[key]


# ---------------------------------------------------------------------------
# _ensure_soul / _ensure_config helpers
# ---------------------------------------------------------------------------


class TestEnsureHelpers:
    def test_ensure_soul_raises_when_no_soul(self):
        """_ensure_soul raises RuntimeError when _soul is None."""
        fake_fastmcp = types.ModuleType("fastmcp")
        fake_fastmcp.FastMCP = CaptureMCP

        with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
            if "pocketpaw.paw.mcp.server" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp.server"]
            if "pocketpaw.paw.mcp" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp"]

            from pocketpaw.paw.mcp import server as srv
            srv._soul = None

            with pytest.raises(RuntimeError, match="No soul loaded"):
                srv._ensure_soul()

        for k in list(sys.modules.keys()):
            if "pocketpaw.paw.mcp" in k:
                del sys.modules[k]

    def test_ensure_soul_returns_soul_when_loaded(self, mock_soul):
        """_ensure_soul returns the soul when it is loaded."""
        fake_fastmcp = types.ModuleType("fastmcp")
        fake_fastmcp.FastMCP = CaptureMCP

        with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
            if "pocketpaw.paw.mcp.server" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp.server"]
            if "pocketpaw.paw.mcp" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp"]

            from pocketpaw.paw.mcp import server as srv
            srv._soul = mock_soul

            result = srv._ensure_soul()

        assert result is mock_soul

        for k in list(sys.modules.keys()):
            if "pocketpaw.paw.mcp" in k:
                del sys.modules[k]

    def test_ensure_config_raises_when_no_config(self):
        """_ensure_config raises RuntimeError when _config is None."""
        fake_fastmcp = types.ModuleType("fastmcp")
        fake_fastmcp.FastMCP = CaptureMCP

        with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
            if "pocketpaw.paw.mcp.server" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp.server"]
            if "pocketpaw.paw.mcp" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp"]

            from pocketpaw.paw.mcp import server as srv
            srv._config = None

            with pytest.raises(RuntimeError, match="No config loaded"):
                srv._ensure_config()

        for k in list(sys.modules.keys()):
            if "pocketpaw.paw.mcp" in k:
                del sys.modules[k]

    def test_ensure_config_returns_config_when_loaded(self, mock_config):
        """_ensure_config returns the config when it is loaded."""
        fake_fastmcp = types.ModuleType("fastmcp")
        fake_fastmcp.FastMCP = CaptureMCP

        with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
            if "pocketpaw.paw.mcp.server" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp.server"]
            if "pocketpaw.paw.mcp" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp"]

            from pocketpaw.paw.mcp import server as srv
            srv._config = mock_config

            result = srv._ensure_config()

        assert result is mock_config

        for k in list(sys.modules.keys()):
            if "pocketpaw.paw.mcp" in k:
                del sys.modules[k]


# ---------------------------------------------------------------------------
# create_server
# ---------------------------------------------------------------------------


class TestCreateServer:
    def test_create_server_returns_mcp_instance(self, captured_server):
        """create_server() returns an MCP instance (CaptureMCP in tests)."""
        capture, _ = captured_server
        assert isinstance(capture, CaptureMCP)

    def test_create_server_registers_all_tools(self, captured_server):
        """create_server() registers all six expected tools."""
        capture, _ = captured_server
        expected_tools = {
            "paw_remember", "paw_recall", "paw_status",
            "paw_edit_core", "paw_ask", "paw_scan",
        }
        assert expected_tools.issubset(set(capture._tools.keys()))

    def test_create_server_registers_resources(self, captured_server):
        """create_server() registers paw://identity, paw://state, paw://config."""
        capture, _ = captured_server
        assert "paw://identity" in capture._resources
        assert "paw://state" in capture._resources
        assert "paw://config" in capture._resources

    def test_create_server_registers_system_prompt(self, captured_server):
        """create_server() registers paw_system_prompt prompt."""
        capture, _ = captured_server
        assert "paw_system_prompt" in capture._prompts

    def test_run_server_entry_point_exists(self):
        """run_server function is importable from the server module."""
        fake_fastmcp = types.ModuleType("fastmcp")
        fake_fastmcp.FastMCP = CaptureMCP

        with patch.dict(sys.modules, {"fastmcp": fake_fastmcp}):
            if "pocketpaw.paw.mcp.server" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp.server"]
            if "pocketpaw.paw.mcp" in sys.modules:
                del sys.modules["pocketpaw.paw.mcp"]

            from pocketpaw.paw.mcp import server as srv
            assert callable(srv.run_server)

        for k in list(sys.modules.keys()):
            if "pocketpaw.paw.mcp" in k:
                del sys.modules[k]


# ---------------------------------------------------------------------------
# paw_remember tool
# ---------------------------------------------------------------------------


class TestPawRememberTool:
    @pytest.mark.asyncio
    async def test_paw_remember_stores_memory(self, captured_server, mock_soul):
        """paw_remember calls soul.remember() with content and importance."""
        capture, _ = captured_server
        paw_remember = capture._tools["paw_remember"]

        await paw_remember("Project uses FastAPI", importance=7)

        mock_soul.remember.assert_awaited_once_with(
            "Project uses FastAPI", importance=7
        )

    @pytest.mark.asyncio
    async def test_paw_remember_returns_json_status(self, captured_server):
        """paw_remember returns JSON with status=remembered."""
        capture, _ = captured_server
        paw_remember = capture._tools["paw_remember"]

        result = await paw_remember("A fact", importance=5)

        data = json.loads(result)
        assert data["status"] == "remembered"
        assert data["importance"] == 5

    @pytest.mark.asyncio
    async def test_paw_remember_clamps_importance_low(self, captured_server, mock_soul):
        """Importance below 1 is clamped to 1."""
        capture, _ = captured_server
        paw_remember = capture._tools["paw_remember"]

        result = await paw_remember("fact", importance=-5)

        data = json.loads(result)
        assert data["importance"] == 1
        mock_soul.remember.assert_awaited_once_with("fact", importance=1)

    @pytest.mark.asyncio
    async def test_paw_remember_clamps_importance_high(self, captured_server, mock_soul):
        """Importance above 10 is clamped to 10."""
        capture, _ = captured_server
        paw_remember = capture._tools["paw_remember"]

        result = await paw_remember("critical fact", importance=99)

        data = json.loads(result)
        assert data["importance"] == 10
        mock_soul.remember.assert_awaited_once_with("critical fact", importance=10)

    @pytest.mark.asyncio
    async def test_paw_remember_preview_truncated_at_200_chars(self, captured_server):
        """Preview in response is capped at 200 characters."""
        capture, _ = captured_server
        paw_remember = capture._tools["paw_remember"]
        long_content = "x" * 300

        result = await paw_remember(long_content, importance=5)

        data = json.loads(result)
        assert len(data["preview"]) == 200

    @pytest.mark.asyncio
    async def test_paw_remember_raises_when_no_soul(self, captured_server, mock_config):
        """paw_remember raises RuntimeError when no soul is loaded."""
        capture, server_module = captured_server
        server_module._soul = None
        paw_remember = capture._tools["paw_remember"]

        with pytest.raises(RuntimeError, match="No soul loaded"):
            await paw_remember("fact")

        # Restore so other tests aren't affected
        server_module._soul = MagicMock()


# ---------------------------------------------------------------------------
# paw_recall tool
# ---------------------------------------------------------------------------


class TestPawRecallTool:
    @pytest.mark.asyncio
    async def test_paw_recall_returns_memories(self, captured_server, mock_soul):
        """paw_recall calls soul.recall() and returns matching memories as JSON."""
        mem = MagicMock()
        mem.content = "project uses Python"
        mem.importance = 8
        mem.emotion = None
        mock_soul.recall = AsyncMock(return_value=[mem])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        result = await paw_recall("Python", limit=5)

        data = json.loads(result)
        assert data["count"] == 1
        assert data["memories"][0]["content"] == "project uses Python"

    @pytest.mark.asyncio
    async def test_paw_recall_empty_returns_empty_list(self, captured_server, mock_soul):
        """paw_recall returns empty memories list when no results."""
        mock_soul.recall = AsyncMock(return_value=[])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        result = await paw_recall("nonexistent")

        data = json.loads(result)
        assert data["memories"] == []
        assert data["query"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_paw_recall_clamps_limit_low(self, captured_server, mock_soul):
        """limit below 1 is clamped to 1."""
        mock_soul.recall = AsyncMock(return_value=[])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        await paw_recall("test", limit=0)

        mock_soul.recall.assert_awaited_once_with("test", limit=1)

    @pytest.mark.asyncio
    async def test_paw_recall_clamps_limit_high(self, captured_server, mock_soul):
        """limit above 20 is clamped to 20."""
        mock_soul.recall = AsyncMock(return_value=[])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        await paw_recall("test", limit=50)

        mock_soul.recall.assert_awaited_once_with("test", limit=20)

    @pytest.mark.asyncio
    async def test_paw_recall_includes_emotion_when_present(self, captured_server, mock_soul):
        """paw_recall includes emotion in memory entry when present."""
        mem = MagicMock()
        mem.content = "exciting launch day"
        mem.importance = 9
        mem.emotion = "joy"
        mock_soul.recall = AsyncMock(return_value=[mem])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        result = await paw_recall("launch")

        data = json.loads(result)
        assert data["memories"][0]["emotion"] == "joy"

    @pytest.mark.asyncio
    async def test_paw_recall_content_truncated_at_500_chars(self, captured_server, mock_soul):
        """Memory content is truncated to 500 chars in response."""
        mem = MagicMock()
        mem.content = "a" * 600
        mem.importance = 5
        mem.emotion = None
        mock_soul.recall = AsyncMock(return_value=[mem])

        capture, _ = captured_server
        paw_recall = capture._tools["paw_recall"]

        result = await paw_recall("test")

        data = json.loads(result)
        assert len(data["memories"][0]["content"]) == 500


# ---------------------------------------------------------------------------
# paw_status tool
# ---------------------------------------------------------------------------


class TestPawStatusTool:
    @pytest.mark.asyncio
    async def test_paw_status_returns_soul_name_and_state(self, captured_server, mock_soul):
        """paw_status includes soul name, mood, energy, social_battery."""
        capture, _ = captured_server
        paw_status = capture._tools["paw_status"]

        result = await paw_status()

        data = json.loads(result)
        assert data["name"] == "TestSoul"
        assert data["mood"] == "curious"
        assert data["energy"] == 85
        assert data["social_battery"] == 90

    @pytest.mark.asyncio
    async def test_paw_status_includes_domains_when_self_model_present(
        self, captured_server, mock_soul
    ):
        """paw_status includes domains from self_model.get_active_self_images."""
        img = MagicMock(domain="Python", confidence=0.9)
        self_model = MagicMock()
        self_model.get_active_self_images.return_value = [img]
        mock_soul.self_model = self_model

        capture, _ = captured_server
        paw_status = capture._tools["paw_status"]

        result = await paw_status()

        data = json.loads(result)
        assert "domains" in data
        assert data["domains"][0]["domain"] == "Python"
        assert data["domains"][0]["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_paw_status_no_soul_raises(self, captured_server, mock_soul):
        """paw_status raises RuntimeError when no soul loaded."""
        capture, server_module = captured_server
        server_module._soul = None
        paw_status = capture._tools["paw_status"]

        with pytest.raises(RuntimeError, match="No soul loaded"):
            await paw_status()

        server_module._soul = mock_soul


# ---------------------------------------------------------------------------
# paw_edit_core tool
# ---------------------------------------------------------------------------


class TestPawEditCoreTool:
    @pytest.mark.asyncio
    async def test_paw_edit_core_updates_persona(self, captured_server, mock_soul):
        """paw_edit_core calls soul.edit_core_memory with persona arg."""
        capture, _ = captured_server
        paw_edit_core = capture._tools["paw_edit_core"]

        result = await paw_edit_core(persona="I am a code assistant")

        mock_soul.edit_core_memory.assert_awaited_once_with(persona="I am a code assistant")
        data = json.loads(result)
        assert data["status"] == "updated"
        assert "persona" in data["fields"]

    @pytest.mark.asyncio
    async def test_paw_edit_core_updates_human(self, captured_server, mock_soul):
        """paw_edit_core calls soul.edit_core_memory with human arg."""
        capture, _ = captured_server
        paw_edit_core = capture._tools["paw_edit_core"]

        result = await paw_edit_core(human="Alice, a senior engineer")

        mock_soul.edit_core_memory.assert_awaited_once_with(human="Alice, a senior engineer")
        data = json.loads(result)
        assert "human" in data["fields"]

    @pytest.mark.asyncio
    async def test_paw_edit_core_empty_args_returns_error(self, captured_server):
        """paw_edit_core returns error JSON when no args provided."""
        capture, _ = captured_server
        paw_edit_core = capture._tools["paw_edit_core"]

        result = await paw_edit_core()

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_paw_edit_core_empty_args_does_not_call_soul(self, captured_server, mock_soul):
        """soul.edit_core_memory is not called when no args provided."""
        capture, _ = captured_server
        paw_edit_core = capture._tools["paw_edit_core"]

        await paw_edit_core()

        mock_soul.edit_core_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paw_edit_core_updates_both(self, captured_server, mock_soul):
        """paw_edit_core passes both persona and human when both provided."""
        capture, _ = captured_server
        paw_edit_core = capture._tools["paw_edit_core"]

        result = await paw_edit_core(persona="New persona", human="Bob the developer")

        mock_soul.edit_core_memory.assert_awaited_once_with(
            persona="New persona", human="Bob the developer"
        )
        data = json.loads(result)
        assert set(data["fields"]) == {"persona", "human"}


# ---------------------------------------------------------------------------
# paw_ask tool
# ---------------------------------------------------------------------------


class TestPawAskTool:
    @pytest.mark.asyncio
    async def test_paw_ask_recalls_memories_for_question(self, captured_server, mock_soul):
        """paw_ask calls soul.recall() with the question."""
        mock_soul.recall = AsyncMock(return_value=[])

        capture, _ = captured_server
        paw_ask = capture._tools["paw_ask"]

        await paw_ask("what is this project?")

        mock_soul.recall.assert_awaited_once_with("what is this project?", limit=5)

    @pytest.mark.asyncio
    async def test_paw_ask_returns_memories_when_found(self, captured_server, mock_soul):
        """paw_ask returns memories in JSON when memories exist."""
        mem = MagicMock()
        mem.content = "This project is a FastAPI backend"
        mock_soul.recall = AsyncMock(return_value=[mem])

        capture, _ = captured_server
        paw_ask = capture._tools["paw_ask"]

        result = await paw_ask("what is this?")

        data = json.loads(result)
        assert data["count"] == 1
        assert "This project is a FastAPI backend" in data["memories"]

    @pytest.mark.asyncio
    async def test_paw_ask_returns_no_memories_note_when_empty(self, captured_server, mock_soul):
        """paw_ask returns note about scanning when no memories found."""
        mock_soul.recall = AsyncMock(return_value=[])

        capture, _ = captured_server
        paw_ask = capture._tools["paw_ask"]

        result = await paw_ask("anything")

        data = json.loads(result)
        assert data["count"] == 0
        assert "note" in data
        assert data["memories"] == []


# ---------------------------------------------------------------------------
# paw_scan tool
# ---------------------------------------------------------------------------


class TestPawScanTool:
    @pytest.mark.asyncio
    async def test_paw_scan_calls_heuristic_scan(self, captured_server, mock_soul, tmp_path):
        """paw_scan invokes heuristic_scan on the target directory."""
        capture, _ = captured_server
        paw_scan = capture._tools["paw_scan"]

        with patch("pocketpaw.paw.scan.heuristic_scan", new=AsyncMock()) as mock_scan:
            result = await paw_scan(path=str(tmp_path))

        mock_scan.assert_awaited_once()
        data = json.loads(result)
        assert data["status"] == "scanned"

    @pytest.mark.asyncio
    async def test_paw_scan_invalid_path_returns_error(self, captured_server):
        """paw_scan returns error JSON when path is not a directory."""
        capture, _ = captured_server
        paw_scan = capture._tools["paw_scan"]

        result = await paw_scan(path="/nonexistent/path/xyz")

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_paw_scan_saves_soul_after_scan(self, captured_server, mock_soul, tmp_path):
        """paw_scan saves soul after successful scan."""
        capture, _ = captured_server
        paw_scan = capture._tools["paw_scan"]

        with patch("pocketpaw.paw.scan.heuristic_scan", new=AsyncMock()):
            await paw_scan(path=str(tmp_path))

        mock_soul.save.assert_awaited()


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    @pytest.mark.asyncio
    async def test_identity_resource_returns_name_and_did(self, captured_server, mock_soul):
        """paw://identity resource returns soul name, did, and archetype."""
        capture, _ = captured_server
        get_identity = capture._resources["paw://identity"]

        result = await get_identity()

        data = json.loads(result)
        assert data["name"] == "TestSoul"
        assert data["did"] == "did:soul:test123"
        assert data["archetype"] == "Test Archetype"

    @pytest.mark.asyncio
    async def test_state_resource_returns_mood_and_energy(self, captured_server, mock_soul):
        """paw://state resource returns mood, energy, social_battery."""
        capture, _ = captured_server
        get_state = capture._resources["paw://state"]

        result = await get_state()

        data = json.loads(result)
        assert data["mood"] == "curious"
        assert data["energy"] == 85
        assert data["social_battery"] == 90

    @pytest.mark.asyncio
    async def test_config_resource_returns_project_info(self, captured_server, mock_config, tmp_path):
        """paw://config resource returns project_root, soul_name, provider."""
        capture, _ = captured_server
        get_config = capture._resources["paw://config"]

        result = await get_config()

        data = json.loads(result)
        assert data["soul_name"] == "TestSoul"
        assert data["provider"] == "claude"
        assert "project_root" in data

    @pytest.mark.asyncio
    async def test_identity_resource_no_soul_raises(self, captured_server, mock_soul):
        """paw://identity raises RuntimeError when no soul loaded."""
        capture, server_module = captured_server
        server_module._soul = None
        get_identity = capture._resources["paw://identity"]

        with pytest.raises(RuntimeError, match="No soul loaded"):
            await get_identity()

        server_module._soul = mock_soul

    @pytest.mark.asyncio
    async def test_state_resource_no_soul_raises(self, captured_server, mock_soul):
        """paw://state raises RuntimeError when no soul loaded."""
        capture, server_module = captured_server
        server_module._soul = None
        get_state = capture._resources["paw://state"]

        with pytest.raises(RuntimeError, match="No soul loaded"):
            await get_state()

        server_module._soul = mock_soul

    @pytest.mark.asyncio
    async def test_config_resource_no_config_raises(self, captured_server, mock_config):
        """paw://config raises RuntimeError when no config loaded."""
        capture, server_module = captured_server
        server_module._config = None
        get_config = capture._resources["paw://config"]

        with pytest.raises(RuntimeError, match="No config loaded"):
            await get_config()

        server_module._config = mock_config


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    @pytest.mark.asyncio
    async def test_system_prompt_returns_soul_prompt(self, captured_server, mock_soul):
        """paw_system_prompt returns soul.to_system_prompt() result."""
        capture, _ = captured_server
        paw_system_prompt = capture._prompts["paw_system_prompt"]

        result = await paw_system_prompt()

        assert result == "Test system prompt"

    @pytest.mark.asyncio
    async def test_system_prompt_fallback_when_no_soul(self, captured_server, mock_soul):
        """paw_system_prompt returns fallback message when no soul loaded."""
        capture, server_module = captured_server
        server_module._soul = None
        paw_system_prompt = capture._prompts["paw_system_prompt"]

        result = await paw_system_prompt()

        assert "No soul loaded" in result

        server_module._soul = mock_soul
