"""Canonical, task-free conversation turn assembly."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, replace

from ..contracts import ConversationKeyV1, MediaRef, TurnEnvelope
from ..contracts.validation import ContractValidationError, require_finite_timestamp


def _merge_media(existing: tuple[MediaRef, ...], incoming: tuple[MediaRef, ...]) -> tuple[MediaRef, ...]:
    result: list[MediaRef] = []
    seen: set[str] = set()
    for item in (*existing, *incoming):
        if item.media_id in seen:
            continue
        seen.add(item.media_id)
        result.append(replace(item, order=len(result)))
    return tuple(result)


def _merged_text(existing: str, incoming: str) -> str:
    if not existing:
        return incoming
    if not incoming:
        return existing
    return f"{existing}\n{incoming}"


@dataclass(slots=True)
class _PendingTurn:
    turn: TurnEnvelope
    ready_at: float


class ConversationTurnAssemblerV1:
    """Finalize canonical user turns without cancellation or background tasks."""

    def __init__(self, *, quiet_window_seconds: float = 3.0, max_conversations: int = 128) -> None:
        if type(quiet_window_seconds) not in (int, float) or quiet_window_seconds <= 0:
            raise ContractValidationError("quiet_window_seconds must be a positive number")
        if type(max_conversations) is not int or max_conversations <= 0:
            raise ContractValidationError("max_conversations must be a positive integer")
        self.quiet_window_seconds = float(quiet_window_seconds)
        self.max_conversations = max_conversations
        self._active: OrderedDict[ConversationKeyV1, _PendingTurn] = OrderedDict()

    @staticmethod
    def _now(value: float | None) -> float:
        return time.time() if value is None else require_finite_timestamp(value, "now")

    @staticmethod
    def _key(turn: TurnEnvelope) -> ConversationKeyV1:
        raw = turn.metadata.get("conversation_key")
        if not isinstance(raw, dict):
            raise ContractValidationError("turn is missing canonical conversation key")
        return ConversationKeyV1.from_dict(raw)

    def _start(
        self, key: ConversationKeyV1, turn: TurnEnvelope, now: float
    ) -> TurnEnvelope | None:
        evicted: TurnEnvelope | None = None
        if key not in self._active and len(self._active) >= self.max_conversations:
            _, pending = self._active.popitem(last=False)
            # Capacity pressure must not silently erase a user's pending
            # turn.  Return it as a deterministic finalized result so the
            # caller can publish it to the bounded ledger.
            evicted = pending.turn
        # ``event_to_envelope`` may timestamp just before the assembler call;
        # never create an invalid envelope whose batch start is in the future.
        self._active[key] = _PendingTurn(
            replace(turn, batch_started_at=min(now, turn.received_at)),
            now + self.quiet_window_seconds,
        )
        return evicted

    def ingest(self, turn: TurnEnvelope, *, now: float | None = None) -> tuple[TurnEnvelope, ...]:
        if not isinstance(turn, TurnEnvelope):
            raise ContractValidationError("assembler accepts TurnEnvelope")
        current = self._now(now)
        key = self._key(turn)
        pending = self._active.get(key)
        if pending is None:
            evicted = self._start(key, turn, current)
            return (evicted,) if evicted is not None else ()
        self._active.move_to_end(key)
        if pending.turn.sender_id == turn.sender_id and current <= pending.ready_at:
            existing_ids = dict(pending.turn.metadata).get(
                "message_ids", [pending.turn.metadata.get("message_id", "")]
            )
            pending.turn = replace(
                pending.turn,
                text=_merged_text(pending.turn.text, turn.text),
                media=_merge_media(pending.turn.media, turn.media),
                received_at=max(pending.turn.received_at, turn.received_at),
                metadata={
                    **dict(pending.turn.metadata),
                    "message_ids": [*existing_ids, turn.metadata.get("message_id", "")],
                },
            )
            pending.ready_at = current + self.quiet_window_seconds
            return ()
        finalized = pending.turn
        evicted = self._start(key, turn, current)
        return (finalized, evicted) if evicted is not None else (finalized,)

    def flush_ready(self, *, now: float | None = None) -> tuple[TurnEnvelope, ...]:
        current = self._now(now)
        finalized: list[TurnEnvelope] = []
        for key, pending in list(self._active.items()):
            if current >= pending.ready_at:
                finalized.append(pending.turn)
                self._active.pop(key, None)
        return tuple(finalized)

    def finalize_for_request(self, key: ConversationKeyV1) -> TurnEnvelope | None:
        """Freeze the pending user turn at the Host request boundary.

        A request is an explicit execution boundary: even when the quiet
        window has not elapsed, the pending canonical turn must be committed
        before context is composed.  The operation is task-free and only
        affects the requested conversation key.
        """

        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("assembler key must be ConversationKeyV1")
        pending = self._active.pop(key, None)
        return pending.turn if pending is not None else None

    def clear(self, key: ConversationKeyV1) -> bool:
        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("assembler key must be ConversationKeyV1")
        return self._active.pop(key, None) is not None

    def clear_all(self) -> None:
        self._active.clear()
