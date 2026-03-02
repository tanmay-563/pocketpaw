# Tests for the SoulChannelObserver (Phase 3 of PAW-SPEC).
# Created: 2026-03-02
# Covers: install(), idempotency, inbound tracking, outbound observation,
#         stream buffering, error swallowing, pending_count, session key matching,
#         empty content skipping, and graceful handling when soul-protocol is absent.

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pocketpaw.bus.events import Channel, InboundMessage, OutboundMessage
from pocketpaw.bus.queue import MessageBus
from pocketpaw.paw.observer import SoulChannelObserver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_soul():
    soul = MagicMock()
    soul.observe = AsyncMock()
    return soul


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def observer(mock_soul, bus):
    return SoulChannelObserver(mock_soul, bus)


def _inbound(content: str = "hello", chat_id: str = "chat1") -> InboundMessage:
    return InboundMessage(
        channel=Channel.CLI,
        sender_id="user1",
        chat_id=chat_id,
        content=content,
    )


def _outbound(
    content: str = "hello back",
    chat_id: str = "chat1",
    is_stream_chunk: bool = False,
    is_stream_end: bool = False,
) -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.CLI,
        chat_id=chat_id,
        content=content,
        is_stream_chunk=is_stream_chunk,
        is_stream_end=is_stream_end,
    )


# ---------------------------------------------------------------------------
# install()
# ---------------------------------------------------------------------------


class TestObserverInstall:
    def test_install_wraps_bus_methods(self, observer, bus):
        """install() replaces bus.publish_inbound and publish_outbound with wrappers."""
        original_inbound = bus.publish_inbound
        original_outbound = bus.publish_outbound

        observer.install()

        assert bus.publish_inbound is not original_inbound
        assert bus.publish_outbound is not original_outbound

    def test_is_installed_false_before_install(self, observer):
        """is_installed returns False before install() is called."""
        assert observer.is_installed is False

    def test_is_installed_true_after_install(self, observer):
        """is_installed returns True after install() is called."""
        observer.install()
        assert observer.is_installed is True

    def test_install_idempotent_does_not_double_wrap(self, observer, bus):
        """Calling install() twice does not wrap the bus methods a second time."""
        observer.install()
        wrapped_inbound = bus.publish_inbound

        observer.install()  # second call — should be a no-op

        assert bus.publish_inbound is wrapped_inbound

    def test_install_idempotent_is_installed_still_true(self, observer):
        """is_installed stays True after redundant install() calls."""
        observer.install()
        observer.install()
        assert observer.is_installed is True


# ---------------------------------------------------------------------------
# Inbound tracking
# ---------------------------------------------------------------------------


class TestObserverInboundTracking:
    @pytest.mark.asyncio
    async def test_observer_records_inbound_message(self, observer, bus):
        """After an inbound message, the content is stored in _pending."""
        observer.install()
        msg = _inbound("user query", chat_id="chat1")

        await bus.publish_inbound(msg)

        assert observer._pending.get("cli:chat1") == "user query"

    @pytest.mark.asyncio
    async def test_observer_pending_count_increases_on_inbound(self, observer, bus):
        """pending_count increases for each inbound message without a response."""
        observer.install()

        await bus.publish_inbound(_inbound("msg1", chat_id="chat1"))
        await bus.publish_inbound(_inbound("msg2", chat_id="chat2"))

        assert observer.pending_count == 2

    @pytest.mark.asyncio
    async def test_observer_inbound_still_queued_on_bus(self, observer, bus):
        """Inbound messages still reach the bus queue after interception."""
        observer.install()
        msg = _inbound("queue me")

        await bus.publish_inbound(msg)

        assert bus.inbound_pending() == 1

    @pytest.mark.asyncio
    async def test_observer_matches_session_key_by_channel_and_chat_id(self, observer, bus):
        """Session key is composed as channel.value:chat_id."""
        observer.install()
        msg = _inbound("hello", chat_id="room42")

        await bus.publish_inbound(msg)

        assert "cli:room42" in observer._pending


# ---------------------------------------------------------------------------
# Outbound observation — non-streaming
# ---------------------------------------------------------------------------


class TestObserverOutboundObservation:
    @pytest.mark.asyncio
    async def test_observer_calls_soul_observe_on_non_stream_outbound(
        self, observer, bus, mock_soul
    ):
        """soul.observe() is called when a non-streaming outbound message matches a pending inbound."""
        observer.install()
        # Register subscriber so publish_outbound doesn't warn about no subscribers
        received = []

        async def _sub(msg: OutboundMessage) -> None:
            received.append(msg)

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("question?", chat_id="c1"))
        await bus.publish_outbound(_outbound("answer!", chat_id="c1"))

        mock_soul.observe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_observer_pending_cleared_after_response(self, observer, bus):
        """After a matched outbound, the pending entry is removed."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))
        await bus.publish_outbound(_outbound("a", chat_id="c1"))

        assert observer.pending_count == 0

    @pytest.mark.asyncio
    async def test_observer_ignores_outbound_with_empty_content(self, observer, bus, mock_soul):
        """soul.observe() is NOT called when outbound content is empty."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))
        # outbound with empty string — should not trigger observe
        await bus.publish_outbound(_outbound("", chat_id="c1"))

        mock_soul.observe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_observer_no_observe_without_matching_inbound(self, observer, bus, mock_soul):
        """soul.observe() is NOT called when there is no matching pending inbound."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        # No inbound published first
        await bus.publish_outbound(_outbound("response", chat_id="orphan"))

        mock_soul.observe.assert_not_awaited()


# ---------------------------------------------------------------------------
# Stream buffering
# ---------------------------------------------------------------------------


class TestObserverStreamBuffering:
    @pytest.mark.asyncio
    async def test_observer_buffers_stream_chunks(self, observer, bus, mock_soul):
        """Stream chunks accumulate in buffer; soul.observe() is NOT called on each chunk."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))
        await bus.publish_outbound(_outbound("chunk1", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound(" chunk2", chat_id="c1", is_stream_chunk=True))

        # Still buffering — not observed yet
        mock_soul.observe.assert_not_awaited()
        assert "cli:c1" in observer._stream_buffers

    @pytest.mark.asyncio
    async def test_observer_calls_observe_on_stream_end(self, observer, bus, mock_soul):
        """soul.observe() is called when stream_end message is received."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("stream q", chat_id="c1"))
        await bus.publish_outbound(_outbound("part1", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound(" part2", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound("", chat_id="c1", is_stream_end=True))

        mock_soul.observe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_observer_assembles_full_response_from_stream(self, observer, bus, mock_soul):
        """Assembled response from stream chunks is passed to soul.observe()."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        # Patch _observe_interaction to capture what it receives
        observed_calls = []

        async def _capture(user_input: str, agent_output: str) -> None:
            observed_calls.append((user_input, agent_output))

        observer._observe_interaction = _capture

        await bus.publish_inbound(_inbound("my question", chat_id="c1"))
        await bus.publish_outbound(_outbound("Hello", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound(" World", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound("", chat_id="c1", is_stream_end=True))

        assert len(observed_calls) == 1
        user_in, agent_out = observed_calls[0]
        assert user_in == "my question"
        assert agent_out == "Hello World"

    @pytest.mark.asyncio
    async def test_observer_clears_buffer_after_stream_end(self, observer, bus):
        """Stream buffer is removed after stream_end."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))
        await bus.publish_outbound(_outbound("chunk", chat_id="c1", is_stream_chunk=True))
        await bus.publish_outbound(_outbound("", chat_id="c1", is_stream_end=True))

        assert "cli:c1" not in observer._stream_buffers


# ---------------------------------------------------------------------------
# Error swallowing
# ---------------------------------------------------------------------------


class TestObserverErrorSwallowing:
    @pytest.mark.asyncio
    async def test_observer_swallows_soul_observe_errors(self, observer, bus, mock_soul):
        """Errors from soul.observe() are swallowed and do not break message flow."""
        mock_soul.observe = AsyncMock(side_effect=RuntimeError("soul exploded"))
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))
        # This should NOT raise even though soul.observe() fails
        await bus.publish_outbound(_outbound("a", chat_id="c1"))

    @pytest.mark.asyncio
    async def test_observer_swallows_inbound_tracking_errors(self, observer, bus):
        """Errors when recording inbound are swallowed; message still reaches bus."""
        observer.install()

        # Create a message that will fail attribute access in tracking
        bad_msg = MagicMock(spec=InboundMessage)
        bad_msg.channel = Channel.CLI
        bad_msg.sender_id = "u1"
        bad_msg.chat_id = "c1"
        bad_msg.content = "hi"
        # Make session_key raise
        type(bad_msg).session_key = property(lambda self: (_ for _ in ()).throw(AttributeError))

        # Should not raise — error is swallowed
        await bus.publish_inbound(bad_msg)

    @pytest.mark.asyncio
    async def test_observer_swallows_soul_protocol_import_error(self, observer, bus, mock_soul):
        """ImportError from soul_protocol is swallowed gracefully."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q", chat_id="c1"))

        with patch.dict(sys.modules, {"soul_protocol": None}):
            # Should not raise even with soul_protocol unavailable
            await bus.publish_outbound(_outbound("a", chat_id="c1"))


# ---------------------------------------------------------------------------
# pending_count property
# ---------------------------------------------------------------------------


class TestPendingCount:
    @pytest.mark.asyncio
    async def test_pending_count_zero_initially(self, observer):
        """pending_count is 0 before any messages are processed."""
        assert observer.pending_count == 0

    @pytest.mark.asyncio
    async def test_pending_count_reflects_unmatched_inbounds(self, observer, bus):
        """pending_count equals the number of inbound messages without responses."""
        observer.install()

        await bus.publish_inbound(_inbound("a", chat_id="c1"))
        await bus.publish_inbound(_inbound("b", chat_id="c2"))
        await bus.publish_inbound(_inbound("c", chat_id="c3"))

        assert observer.pending_count == 3

    @pytest.mark.asyncio
    async def test_pending_count_decreases_on_response(self, observer, bus):
        """pending_count decreases when a response is matched."""
        observer.install()

        async def _sub(msg: OutboundMessage) -> None:
            pass

        bus.subscribe_outbound(Channel.CLI, _sub)

        await bus.publish_inbound(_inbound("q1", chat_id="c1"))
        await bus.publish_inbound(_inbound("q2", chat_id="c2"))
        await bus.publish_outbound(_outbound("a1", chat_id="c1"))

        assert observer.pending_count == 1
