"""Conversation-ledger to one bounded ContextSection bridge."""

from __future__ import annotations

from ..contracts import ContextSection
from ..contracts.conversation import ConversationKeyV1
from ..contracts.validation import ContractValidationError, require_non_negative_int
from ..conversation import CanonicalConversationTurnV1, ConversationLedgerV1


class ContextBridgeV1:
    """Render prior ledger turns without duplicating the current turn."""

    source = "conversation_history"
    version = "conversation-history-v1"

    def __init__(self, *, max_chars: int = 4_000) -> None:
        self.max_chars = require_non_negative_int(max_chars, "max_chars")

    @staticmethod
    def _line(turn: CanonicalConversationTurnV1) -> str:
        return f"{turn.speaker_name}: {turn.content}"

    def render(
        self,
        key: ConversationKeyV1,
        ledger: ConversationLedgerV1,
        *,
        current_turn_id: str | None = None,
    ) -> str:
        if not isinstance(ledger, ConversationLedgerV1):
            raise ContractValidationError("bridge requires ConversationLedgerV1")
        turns = ledger.history(key)
        lines = [
            self._line(turn)
            for turn in turns
            if current_turn_id is None or turn.turn_id != current_turn_id
        ]
        if not lines:
            return ""
        title = "[最近对话]"
        if self.max_chars <= len(title):
            return title[: self.max_chars]
        # Prefer the newest complete turns while keeping a deterministic title.
        available = self.max_chars - len(title) - 1
        selected: list[str] = []
        used = 0
        for line in reversed(lines):
            extra = len(line) + (1 if selected else 0)
            if used + extra > available:
                # A single oversized newest turn must not erase all useful
                # context.  Keep a deterministic speaker-preserving prefix
                # fragment, then stop; older turns remain lower priority.
                remaining = available - used - (1 if selected else 0)
                if remaining > 0:
                    selected.append(line[:remaining])
                break
            selected.append(line)
            used += extra
        selected.reverse()
        return title + "\n" + "\n".join(selected)

    def section(
        self,
        key: ConversationKeyV1,
        ledger: ConversationLedgerV1,
        *,
        current_turn_id: str | None = None,
    ) -> ContextSection | None:
        content = self.render(key, ledger, current_turn_id=current_turn_id)
        if not content:
            return None
        return ContextSection(
            source=self.source,
            priority=30,
            content=content,
            max_chars=self.max_chars,
            cache_scope="request",
            version=self.version,
            sensitive=True,
        )
