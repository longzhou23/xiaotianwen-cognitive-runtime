"""Canonical conversation identity shared by ingress and context layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .validation import ContractValidationError, JsonValue, require_identifier


class ConversationScope(str, Enum):
    """The two supported conversation scopes."""

    PRIVATE = "PRIVATE"
    GROUP = "GROUP"


@dataclass(frozen=True, slots=True)
class ConversationKeyV1:
    """Stable conversation identity independent of UMO or message IDs.

    ``legacy_umo`` is deliberately not part of this value.  Callers may keep
    it as compatibility metadata, but changing it cannot split a conversation.
    """

    platform_id: str
    account_id: str
    scope_kind: ConversationScope
    conversation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform_id", require_identifier(self.platform_id, "platform_id"))
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        scope = self.scope_kind
        if not isinstance(scope, ConversationScope):
            try:
                scope = ConversationScope(str(scope).upper())
            except ValueError as exc:
                raise ContractValidationError("scope_kind must be PRIVATE or GROUP") from exc
        object.__setattr__(self, "scope_kind", scope)
        object.__setattr__(self, "conversation_id", require_identifier(self.conversation_id, "conversation_id"))

    @property
    def stable_id(self) -> str:
        """Return a collision-resistant session ID for legacy envelopes."""

        return (
            f"conversation:{self.platform_id}:{self.account_id}:"
            f"{self.scope_kind.value.lower()}:{self.conversation_id}"
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "version": "conversation-key-v1",
            "platform_id": self.platform_id,
            "account_id": self.account_id,
            "scope_kind": self.scope_kind.value,
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ConversationKeyV1:
        if not isinstance(value, dict):
            raise ContractValidationError("conversation key must be an object")
        if value.get("version") not in (None, "conversation-key-v1"):
            raise ContractValidationError("unsupported conversation key version")
        return cls(
            platform_id=value.get("platform_id", ""),
            account_id=value.get("account_id", ""),
            scope_kind=value.get("scope_kind", ""),
            conversation_id=value.get("conversation_id", ""),
        )
