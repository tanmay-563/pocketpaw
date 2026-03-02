# Soul channel observer — intercepts message bus traffic to feed soul.observe().
# Created: 2026-03-02
# Phase 3 of PAW-SPEC roadmap.
# Non-invasive: wraps bus methods without modifying existing source files.
# Observation failures are silently swallowed to never break the message flow.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soul_protocol import Soul

    from pocketpaw.bus.queue import MessageBus


class SoulChannelObserver:
    """Observes message bus traffic and feeds interactions to soul.observe().

    Wraps the bus's publish_inbound and publish_outbound methods to intercept
    messages without modifying any existing PocketPaw source files.

    On each completed interaction (non-streaming outbound or stream_end),
    it calls soul.observe() with the matched user input and agent response.
    """

    def __init__(self, soul: Soul, bus: MessageBus) -> None:
        self._soul = soul
        self._bus = bus
        self._pending: dict[str, str] = {}  # session_key → last user input
        self._stream_buffers: dict[str, list[str]] = {}  # session_key → chunk buffer
        self._installed = False

    def install(self) -> None:
        """Install observer hooks on the message bus.

        Call this once after creating the observer. Safe to call multiple times
        (subsequent calls are no-ops).
        """
        if self._installed:
            return

        original_inbound = self._bus.publish_inbound
        original_outbound = self._bus.publish_outbound

        async def _observed_inbound(msg: Any) -> None:
            """Record inbound user messages for later matching."""
            try:
                self._pending[msg.session_key] = msg.content
            except Exception:
                pass
            await original_inbound(msg)

        async def _observed_outbound(msg: Any) -> None:
            """Match outbound responses to inbound messages and observe."""
            await original_outbound(msg)

            try:
                session_key = f"{msg.channel.value}:{msg.chat_id}"

                if msg.is_stream_chunk:
                    # Buffer streaming chunks
                    if session_key not in self._stream_buffers:
                        self._stream_buffers[session_key] = []
                    self._stream_buffers[session_key].append(msg.content or "")
                    return

                if msg.is_stream_end:
                    # Assemble full response from buffered chunks
                    chunks = self._stream_buffers.pop(session_key, [])
                    full_response = "".join(chunks)
                elif msg.content:
                    # Non-streaming message
                    full_response = msg.content
                else:
                    return

                user_input = self._pending.pop(session_key, None)
                if user_input and full_response:
                    await self._observe_interaction(user_input, full_response)
            except Exception as e:
                logger.debug("Observer outbound hook error (non-fatal): %s", e)

        self._bus.publish_inbound = _observed_inbound  # type: ignore[assignment]
        self._bus.publish_outbound = _observed_outbound  # type: ignore[assignment]
        self._installed = True
        logger.info("Soul channel observer installed on message bus")

    async def _observe_interaction(self, user_input: str, agent_output: str) -> None:
        """Feed a completed interaction to soul.observe()."""
        try:
            from soul_protocol import Interaction

            await self._soul.observe(
                Interaction(user_input=user_input, agent_output=agent_output)
            )
            logger.debug("Soul observed interaction: %.50s... → %.50s...", user_input, agent_output)
        except ImportError:
            pass  # soul-protocol not available
        except Exception as e:
            logger.debug("Soul observation failed (non-fatal): %s", e)

    @property
    def pending_count(self) -> int:
        """Number of inbound messages waiting for responses."""
        return len(self._pending)

    @property
    def is_installed(self) -> bool:
        """Whether the observer is currently installed."""
        return self._installed
