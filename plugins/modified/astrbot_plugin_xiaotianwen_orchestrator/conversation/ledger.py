"""In-memory, bounded conversation ledger with explicit speaker boundaries."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum

from ..contracts.conversation import ConversationKeyV1
from ..contracts.validation import (
    ContractValidationError,
    JsonValue,
    require_finite_timestamp,
    require_identifier,
    require_non_empty_string,
)


class ConversationRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


@dataclass(frozen=True, slots=True)
class CanonicalConversationTurnV1:
    """One immutable speaker turn; sends are not represented here."""

    conversation_key: ConversationKeyV1
    role: ConversationRole
    speaker_id: str
    speaker_name: str
    content: str
    turn_id: str
    occurred_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_key, ConversationKeyV1):
            raise ContractValidationError("conversation_key must be ConversationKeyV1")
        role = self.role
        if not isinstance(role, ConversationRole):
            try:
                role = ConversationRole(str(role).upper())
            except ValueError as exc:
                raise ContractValidationError("role must be USER or ASSISTANT") from exc
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "speaker_id", require_identifier(self.speaker_id, "speaker_id"))
        object.__setattr__(self, "speaker_name", require_non_empty_string(self.speaker_name, "speaker_name"))
        object.__setattr__(self, "content", require_non_empty_string(self.content, "content"))
        object.__setattr__(self, "turn_id", require_identifier(self.turn_id, "turn_id"))
        object.__setattr__(self, "occurred_at", require_finite_timestamp(self.occurred_at, "occurred_at"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "conversation_key": self.conversation_key.to_dict(),
            "role": self.role.value,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "content": self.content,
            "turn_id": self.turn_id,
            "occurred_at": self.occurred_at,
        }


@dataclass(slots=True)
class ConversationLedgerV1:
    """Bounded ledger keyed exclusively by ``ConversationKeyV1``."""

    max_conversations: int = 128
    max_turns_per_conversation: int = 40
    _turns: OrderedDict[ConversationKeyV1, list[CanonicalConversationTurnV1]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if type(self.max_conversations) is not int or self.max_conversations <= 0:
            raise ContractValidationError("max_conversations must be a positive integer")
        if type(self.max_turns_per_conversation) is not int or self.max_turns_per_conversation <= 0:
            raise ContractValidationError("max_turns_per_conversation must be a positive integer")

    @property
    def conversation_count(self) -> int:
        return len(self._turns)

    def _bucket(self, key: ConversationKeyV1) -> list[CanonicalConversationTurnV1]:
        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("ledger key must be ConversationKeyV1")
        bucket = self._turns.get(key)
        if bucket is None:
            if len(self._turns) >= self.max_conversations:
                self._turns.popitem(last=False)
            bucket = []
            self._turns[key] = bucket
        else:
            self._turns.move_to_end(key)
        return bucket

    def append(self, turn: CanonicalConversationTurnV1) -> bool:
        if not isinstance(turn, CanonicalConversationTurnV1):
            raise ContractValidationError("ledger accepts CanonicalConversationTurnV1")
        bucket = self._bucket(turn.conversation_key)
        if any(existing.turn_id == turn.turn_id for existing in bucket):
            return False
        bucket.append(turn)
        if len(bucket) > self.max_turns_per_conversation:
            del bucket[: len(bucket) - self.max_turns_per_conversation]
        return True

    def append_user_turn(
        self,
        key: ConversationKeyV1,
        *,
        speaker_id: str,
        speaker_name: str,
        content: str,
        turn_id: str,
        occurred_at: float,
    ) -> bool:
        return self.append(
            CanonicalConversationTurnV1(
                key,
                ConversationRole.USER,
                speaker_id,
                speaker_name,
                content,
                turn_id,
                occurred_at,
            )
        )

    def append_assistant_turn(
        self,
        key: ConversationKeyV1,
        *,
        content: str,
        logical_response_id: str,
        occurred_at: float,
        speaker_id: str = "xiaotianwen",
        speaker_name: str = "小天文",
    ) -> bool:
        return self.append(
            CanonicalConversationTurnV1(
                key,
                ConversationRole.ASSISTANT,
                speaker_id,
                speaker_name,
                content,
                logical_response_id,
                occurred_at,
            )
        )

    def history(self, key: ConversationKeyV1) -> tuple[CanonicalConversationTurnV1, ...]:
        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("ledger key must be ConversationKeyV1")
        bucket = self._turns.get(key)
        if bucket is None:
            return ()
        self._turns.move_to_end(key)
        return tuple(bucket)

    def snapshot(self) -> tuple[tuple[ConversationKeyV1, tuple[CanonicalConversationTurnV1, ...]], ...]:
        return tuple((key, tuple(value)) for key, value in self._turns.items())

    def clear(self, key: ConversationKeyV1) -> bool:
        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("ledger key must be ConversationKeyV1")
        return self._turns.pop(key, None) is not None

    reset = clear

    def clear_all(self) -> None:
        self._turns.clear()
