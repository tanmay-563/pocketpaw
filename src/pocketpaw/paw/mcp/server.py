# Paw MCP server — FastMCP server exposing soul tools, resources, and prompts.
# Created: 2026-03-02
# Follows the same pattern as soul-protocol's MCP server (fastmcp decorators,
# lifespan-managed startup, stdio transport).
# Tools: paw_remember, paw_recall, paw_status, paw_edit_core, paw_ask, paw_scan.
# Resources: paw://identity, paw://state, paw://config.
# Prompts: paw_system_prompt.

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state (set during lifespan)
_soul: Any = None
_config: Any = None


def _ensure_soul() -> Any:
    """Return the loaded soul or raise."""
    if _soul is None:
        raise RuntimeError("No soul loaded. Run 'paw init' first to create a soul.")
    return _soul


def _ensure_config() -> Any:
    """Return the loaded config or raise."""
    if _config is None:
        raise RuntimeError("No config loaded. Run 'paw init' first.")
    return _config


def create_server():
    """Create and return the FastMCP server instance."""
    from fastmcp import FastMCP

    @asynccontextmanager
    async def _lifespan(server: FastMCP):
        """Load soul and config on startup, clean up on shutdown."""
        global _soul, _config
        try:
            from pocketpaw.paw.config import PawConfig

            _config = PawConfig.load()
            soul_path = _config.soul_path or _config.default_soul_path

            if soul_path.exists():
                from soul_protocol import Soul

                _soul = await Soul.awaken(soul_path)
                logger.info("MCP server loaded soul from %s", soul_path)
            else:
                logger.warning("No soul file at %s — some tools will be unavailable", soul_path)
        except ImportError:
            logger.warning("soul-protocol not installed — soul tools unavailable")
        except Exception as e:
            logger.warning("Failed to load soul: %s", e)

        yield

        _soul = None
        _config = None

    mcp = FastMCP(
        "paw",
        instructions=(
            "Paw MCP server. Provides tools to interact with your project's AI soul — "
            "remember facts, recall memories, check status, and ask questions."
        ),
        lifespan=_lifespan,
    )

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def paw_remember(content: str, importance: int = 5) -> str:
        """Store a fact or observation in the soul's persistent memory.

        Args:
            content: The information to remember (be specific and clear).
            importance: Importance level from 1 (trivial) to 10 (critical). Default: 5.
        """
        soul = _ensure_soul()
        importance = max(1, min(10, importance))
        await soul.remember(content, importance=importance)
        return json.dumps({
            "status": "remembered",
            "importance": importance,
            "preview": content[:200],
        })

    @mcp.tool()
    async def paw_recall(query: str, limit: int = 5) -> str:
        """Search the soul's persistent memories for relevant information.

        Args:
            query: What to search for in memories.
            limit: Maximum number of memories to return (1-20). Default: 5.
        """
        soul = _ensure_soul()
        limit = max(1, min(20, limit))
        memories = await soul.recall(query, limit=limit)
        if not memories:
            return json.dumps({"memories": [], "query": query})

        results = []
        for m in memories:
            entry: dict[str, Any] = {
                "content": m.content[:500],
                "importance": m.importance,
            }
            if hasattr(m, "emotion") and m.emotion:
                entry["emotion"] = str(m.emotion)
            results.append(entry)

        return json.dumps({"memories": results, "query": query, "count": len(results)})

    @mcp.tool()
    async def paw_status() -> str:
        """Check the soul's current state including mood, energy, and expertise domains."""
        soul = _ensure_soul()
        state = soul.state
        status: dict[str, Any] = {"name": soul.name if hasattr(soul, "name") else "Paw"}

        if hasattr(state, "mood"):
            status["mood"] = str(state.mood)
        if hasattr(state, "energy"):
            status["energy"] = state.energy
        if hasattr(state, "social_battery"):
            status["social_battery"] = state.social_battery
        if hasattr(state, "lifecycle"):
            status["lifecycle"] = str(state.lifecycle)

        if hasattr(soul, "self_model") and soul.self_model:
            try:
                images = soul.self_model.get_active_self_images(limit=5)
                status["domains"] = [
                    {"domain": img.domain, "confidence": img.confidence} for img in images
                ]
            except Exception:
                pass

        return json.dumps(status, default=str)

    @mcp.tool()
    async def paw_edit_core(persona: str = "", human: str = "") -> str:
        """Edit the soul's core memory — persistent persona and human descriptions.

        Args:
            persona: Updated persona description for the agent.
            human: Updated description of the human user.
        """
        soul = _ensure_soul()
        if not persona and not human:
            return json.dumps({"error": "Provide at least one of 'persona' or 'human'."})

        edit_args: dict[str, str] = {}
        if persona:
            edit_args["persona"] = persona
        if human:
            edit_args["human"] = human

        await soul.edit_core_memory(**edit_args)
        return json.dumps({"status": "updated", "fields": list(edit_args.keys())})

    @mcp.tool()
    async def paw_ask(question: str) -> str:
        """Ask the soul a question about the project. Uses recalled memories for context.

        Args:
            question: Your question about the project.
        """
        soul = _ensure_soul()

        # Recall relevant memories
        memories = await soul.recall(question, limit=5)
        memory_context = [m.content for m in memories] if memories else []

        # Build response from memories (full agent routing requires LLM backend)
        if memory_context:
            return json.dumps({
                "memories": memory_context,
                "count": len(memory_context),
                "note": "Showing recalled memories. For full agent responses, use paw chat.",
            })
        else:
            return json.dumps({
                "memories": [],
                "count": 0,
                "note": "No relevant memories found. Run 'paw init --scan' to scan the project.",
            })

    @mcp.tool()
    async def paw_scan(path: str = ".") -> str:
        """Scan or re-scan the project directory to update the soul's knowledge.

        Args:
            path: Project directory to scan (default: current directory).
        """
        soul = _ensure_soul()
        from pocketpaw.paw.scan import heuristic_scan

        project_path = Path(path).resolve()
        if not project_path.is_dir():
            return json.dumps({"error": f"Not a directory: {project_path}"})

        await heuristic_scan(project_path, soul)

        # Save updated soul
        config = _ensure_config()
        soul_path = config.soul_path or config.default_soul_path
        try:
            await soul.save(soul_path)
        except Exception:
            pass

        return json.dumps({"status": "scanned", "path": str(project_path)})

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    @mcp.resource("paw://identity")
    async def get_identity() -> str:
        """Soul identity information (name, archetype, DID)."""
        soul = _ensure_soul()
        identity: dict[str, Any] = {"name": soul.name if hasattr(soul, "name") else "Paw"}

        if hasattr(soul, "did"):
            identity["did"] = str(soul.did)
        if hasattr(soul, "archetype"):
            identity["archetype"] = soul.archetype

        return json.dumps(identity, default=str)

    @mcp.resource("paw://state")
    async def get_state() -> str:
        """Current soul state (mood, energy, social battery)."""
        soul = _ensure_soul()
        state = soul.state
        result: dict[str, Any] = {}

        if hasattr(state, "mood"):
            result["mood"] = str(state.mood)
        if hasattr(state, "energy"):
            result["energy"] = state.energy
        if hasattr(state, "social_battery"):
            result["social_battery"] = state.social_battery

        return json.dumps(result, default=str)

    @mcp.resource("paw://config")
    async def get_config() -> str:
        """Paw configuration for this project."""
        config = _ensure_config()
        return json.dumps({
            "project_root": str(config.project_root),
            "soul_name": config.soul_name,
            "provider": config.provider,
            "soul_path": str(config.soul_path or config.default_soul_path),
        })

    # -----------------------------------------------------------------------
    # Prompts
    # -----------------------------------------------------------------------

    @mcp.prompt()
    async def paw_system_prompt() -> str:
        """Generate the full system prompt for this project's soul."""
        if _soul is None:
            return "No soul loaded. Run 'paw init' to create one."
        return _soul.to_system_prompt()

    return mcp


def run_server() -> None:
    """Entry point for running the MCP server via stdio."""
    mcp = create_server()
    mcp.run()
