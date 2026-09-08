"""Bounded, manually approved response-expression preferences.

This module contains only the closed response-expression parameters.  It does
not infer preferences from ordinary messages, review evidence, emotion,
relationship state, or learning output.  Candidates come from the existing
explicit command or one fixed, deterministic continuous-request phrase;
approval is a separate administrator operation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from iris_memory.cognitive.interaction_trace import (
    ConversationKeyV1,
    ScopeKind,
    conversation_key_from_event,
)

RESPONSE_PREFERENCE_SCHEMA_VERSION = "response-style-preference.v1"
RESPONSE_PREFERENCE_KV_KEY = "response_style_preference:v1"
RESPONSE_EXPANSION_PARAMETER = "response_expansion"
RESPONSE_LENGTH_PARAMETER = "response_length"
MEMORY_RETRIEVAL_PARAMETER = "tool_memory_retrieval"
RELATIONSHIP_FAMILIARITY_PARAMETER = "relationship_familiarity"
DEFAULT = "DEFAULT"
CONCLUSION_FIRST = "CONCLUSION_FIRST"
SHORT = "SHORT"
MEMORY_RETRIEVAL_ON = "ON"
FAMILIAR = "FAMILIAR"
SUPPORTED_RESPONSE_EXPANSIONS = frozenset({DEFAULT, CONCLUSION_FIRST})
SUPPORTED_RESPONSE_LENGTHS = frozenset({DEFAULT, SHORT})
SUPPORTED_MEMORY_RETRIEVAL_VALUES = frozenset({MEMORY_RETRIEVAL_ON})
SUPPORTED_RESPONSE_PARAMETERS = frozenset(
    {
        RESPONSE_EXPANSION_PARAMETER,
        RESPONSE_LENGTH_PARAMETER,
        MEMORY_RETRIEVAL_PARAMETER,
        RELATIONSHIP_FAMILIARITY_PARAMETER,
    }
)
APPROVAL_TTL_SECONDS = 7 * 24 * 60 * 60

PENDING = "PENDING"
APPROVED = "APPROVED"
REVOKED = "REVOKED"
SUSPENDED = "SUSPENDED"
SUPERSEDED = "SUPERSEDED"
STORED_STATUSES = frozenset({PENDING, APPROVED, REVOKED, SUSPENDED, SUPERSEDED})

SOURCE_KIND = "EXPLICIT_CONTROLLED_REQUEST"
RESPONSE_LENGTH_FEEDBACK_AGGREGATE_SOURCE_KIND = "RESPONSE_LENGTH_FEEDBACK_AGGREGATE"
RESPONSE_PREFERENCE_MARKER = "<iris:response_style_preference>"
TOOL_PREFERENCE_MARKER = "<iris:tool_preference>"
_DETAIL_REQUEST_PATTERN = re.compile(
    r"^\s*(?:这次|本次|这轮|此次)\s*(?:请)?\s*(?:详细|完整)\s*"
    r"(?:解释|说明|展开|回答)(?:一下|一些)?(?:.*?)?[。.!！?？]*\s*$",
    re.IGNORECASE,
)
_CONTINUOUS_CONCLUSION_REQUEST_PATTERN = re.compile(
    r"^\s*以后(?:这里|这个私聊)\s*先给结论\s*[吧呀喔]?\s*[。.!！?？]?\s*$",
    re.IGNORECASE,
)
_CONTINUOUS_FAMILIARITY_REQUEST_PATTERN = re.compile(
    r"^\s*以后(?:这里|这个私聊)\s*(?:可以)?按熟人相处\s*[吧呀喔]?\s*[。.!！?？]?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_NO_TOOL_PHRASES = (
    "不联网",
    "不要联网",
    "不要调用工具",
    "不要使用工具",
    "不要检索",
    "不要搜索",
    "不要查资料",
)
_INDIRECT_COMPONENT_TOKENS = frozenset({"reply", "quote", "forward", "node"})


class ResponsePreferenceIntegrityError(ValueError):
    """Raised when the dedicated KV value is not the known schema."""


class ResponsePreferenceScopeError(ValueError):
    """Raised when a host event does not provide a trusted private scope."""


def _strict_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ResponsePreferenceIntegrityError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _strict_text(value, field)


def _strict_timestamp(value: object, field: str, *, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or isinstance(value, bool):
        raise ResponsePreferenceIntegrityError(f"{field} must be a timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ResponsePreferenceIntegrityError(f"{field} must be a finite timestamp")
    return result


def normalize_response_expansion(value: object) -> str:
    """Accept only the two closed values; never retain caller-provided text."""

    if type(value) is not str:
        raise ValueError("response_expansion 只能是 DEFAULT 或 CONCLUSION_FIRST")
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_RESPONSE_EXPANSIONS:
        raise ValueError("response_expansion 只能是 DEFAULT 或 CONCLUSION_FIRST")
    return normalized


def normalize_response_length(value: object) -> str:
    """Accept only the closed concise/default values."""

    if type(value) is not str:
        raise ValueError("response_length 只能是 DEFAULT 或 SHORT")
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_RESPONSE_LENGTHS:
        raise ValueError("response_length 只能是 DEFAULT 或 SHORT")
    return normalized


def normalize_memory_retrieval_preference(value: object) -> str:
    """Accept only the one explicitly frozen memory-retrieval value."""

    if type(value) is not str:
        raise ValueError("tool_memory_retrieval 只能是 ON")
    normalized = value.strip().upper()
    if normalized not in SUPPORTED_MEMORY_RETRIEVAL_VALUES:
        raise ValueError("tool_memory_retrieval 只能是 ON")
    return normalized


def normalize_relationship_familiarity(value: object) -> str:
    """Accept the one deliberately bounded relationship state."""

    if type(value) is not str or value.strip().upper() != FAMILIAR:
        raise ValueError("relationship_familiarity 只能是 FAMILIAR")
    return FAMILIAR


def normalize_response_preference_value(parameter: object, value: object) -> str:
    """Normalize one whitelisted parameter without accepting arbitrary keys."""

    if parameter == RESPONSE_EXPANSION_PARAMETER:
        return normalize_response_expansion(value)
    if parameter == RESPONSE_LENGTH_PARAMETER:
        return normalize_response_length(value)
    if parameter == MEMORY_RETRIEVAL_PARAMETER:
        return normalize_memory_retrieval_preference(value)
    if parameter == RELATIONSHIP_FAMILIARITY_PARAMETER:
        return normalize_relationship_familiarity(value)
    raise ValueError("unknown response preference parameter")


def explicit_no_tool_request(text: object) -> bool:
    """Recognize only fixed current-turn no-tool instructions.

    This is an override at the request boundary.  It does not infer a
    preference from tone, cost concerns, or an indirect statement.
    """

    if type(text) is not str:
        return False
    return any(phrase in text for phrase in _EXPLICIT_NO_TOOL_PHRASES)


def explicit_response_preference_value(text: object) -> str | None:
    """Map one exact continuous request to the existing candidate value.

    A sentence must contain the continuous marker and the complete fixed
    response-order request.  This intentionally does not parse ordinary
    feedback, a one-turn request, a third-party statement, or a vague
    expression.
    """

    if type(text) is not str:
        return None
    return (
        CONCLUSION_FIRST
        if _CONTINUOUS_CONCLUSION_REQUEST_PATTERN.fullmatch(text)
        else None
    )


def explicit_relationship_familiarity_value(text: object) -> str | None:
    """Recognize one direct, durable familiarity request and nothing else."""

    if type(text) is not str:
        return None
    return FAMILIAR if _CONTINUOUS_FAMILIARITY_REQUEST_PATTERN.fullmatch(text) else None


def _indirect_component_marker(value: object) -> bool:
    """Detect only explicit quote/forward component markers, fail closed."""

    if isinstance(value, Mapping):
        for key in ("type", "type_name", "component_type", "name"):
            marker = value.get(key)
            if isinstance(marker, str) and any(
                token in marker.casefold() for token in _INDIRECT_COMPONENT_TOKENS
            ):
                return True
        for key in ("message", "messages", "data", "content"):
            nested = value.get(key)
            if isinstance(nested, (Mapping, list, tuple)) and _indirect_component_marker(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_indirect_component_marker(item) for item in value)
    type_name = type(value).__name__.casefold()
    return any(token in type_name for token in _INDIRECT_COMPONENT_TOKENS)


def event_contains_indirect_content(event: object) -> bool:
    """Return whether the event carries a quote/forward/reply component.

    The current message text is never inspected as a substitute for the
    component chain.  A missing or malformed chain is rejected when the host
    exposes the accessor, so flattened forwarded text cannot become a
    preference request by accident.
    """

    getter = getattr(event, "get_messages", None)
    if callable(getter):
        try:
            messages = getter()
        except Exception:  # noqa: BLE001 - malformed chain is fail-closed
            return True
        if type(messages) not in (list, tuple):
            return True
        if any(_indirect_component_marker(item) for item in messages):
            return True

    message_obj = getattr(event, "message_obj", None)
    raw_message = getattr(message_obj, "raw_message", None)
    return _indirect_component_marker(raw_message)


@dataclass(frozen=True, slots=True)
class ResponsePreferenceScope:
    """Exact private conversation identity used for matching."""

    platform_id: str
    account_id: str
    user_id: str
    conversation_id: str
    scope_kind: str = ScopeKind.PRIVATE.value

    def __post_init__(self) -> None:
        for field in ("platform_id", "account_id", "user_id", "conversation_id"):
            object.__setattr__(self, field, _strict_text(getattr(self, field), field))
        if self.scope_kind != ScopeKind.PRIVATE.value:
            raise ResponsePreferenceIntegrityError("response preference scope must be PRIVATE")

    @classmethod
    def from_conversation_key(cls, key: ConversationKeyV1) -> ResponsePreferenceScope:
        if type(key) is not ConversationKeyV1 or key.scope_kind is not ScopeKind.PRIVATE:
            raise ResponsePreferenceScopeError("只支持可信的一处私聊 scope")
        return cls(
            platform_id=key.platform_id,
            account_id=key.account_id,
            user_id=key.conversation_id,
            conversation_id=key.conversation_id,
        )

    @classmethod
    def from_dict(cls, value: object) -> ResponsePreferenceScope:
        if not isinstance(value, Mapping) or set(value) != {
            "platform_id",
            "account_id",
            "user_id",
            "conversation_id",
            "scope_kind",
        }:
            raise ResponsePreferenceIntegrityError("invalid response preference scope")
        return cls(**dict(value))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, str]:
        return {
            "platform_id": self.platform_id,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "scope_kind": self.scope_kind,
        }


@dataclass(frozen=True, slots=True)
class ResponsePreferenceSource:
    """Minimal trusted source reference; no reconstructed historical body."""

    source_kind: str
    source_event_id: str

    def __post_init__(self) -> None:
        if self.source_kind not in {
            SOURCE_KIND,
            RESPONSE_LENGTH_FEEDBACK_AGGREGATE_SOURCE_KIND,
        }:
            raise ResponsePreferenceIntegrityError("unknown response preference source kind")
        object.__setattr__(self, "source_event_id", _strict_text(self.source_event_id, "source_event_id"))

    @classmethod
    def from_dict(cls, value: object) -> ResponsePreferenceSource:
        if not isinstance(value, Mapping) or set(value) != {"source_kind", "source_event_id"}:
            raise ResponsePreferenceIntegrityError("invalid response preference source")
        return cls(**dict(value))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, str]:
        return {
            "source_kind": self.source_kind,
            "source_event_id": self.source_event_id,
        }


@dataclass(frozen=True, slots=True)
class ResponsePreferenceRecord:
    candidate_id: str
    scope: ResponsePreferenceScope
    parameter: str
    value: str
    source: ResponsePreferenceSource
    status: str
    requested_at: float
    approved_by: str | None = None
    approved_at: float | None = None
    expires_at: float | None = None
    revoked_by: str | None = None
    revoked_at: float | None = None
    suspended_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _strict_text(self.candidate_id, "candidate_id"))
        if type(self.scope) is not ResponsePreferenceScope:
            raise ResponsePreferenceIntegrityError("invalid response preference scope")
        if self.parameter not in SUPPORTED_RESPONSE_PARAMETERS:
            raise ResponsePreferenceIntegrityError("unknown response preference parameter")
        try:
            object.__setattr__(
                self,
                "value",
                normalize_response_preference_value(self.parameter, self.value),
            )
        except ValueError as exc:
            raise ResponsePreferenceIntegrityError(str(exc)) from exc
        if type(self.source) is not ResponsePreferenceSource:
            raise ResponsePreferenceIntegrityError("invalid response preference source")
        if self.candidate_id != candidate_id_for(
            self.scope, self.source, self.value, self.parameter
        ):
            raise ResponsePreferenceIntegrityError("response preference candidate id mismatch")
        if self.status not in STORED_STATUSES:
            raise ResponsePreferenceIntegrityError("unknown response preference status")
        requested_at = _strict_timestamp(self.requested_at, "requested_at", nullable=False)
        object.__setattr__(self, "requested_at", requested_at)
        for field in ("approved_at", "expires_at", "revoked_at"):
            object.__setattr__(self, field, _strict_timestamp(getattr(self, field), field))
        for field in ("approved_by", "revoked_by", "suspended_reason"):
            object.__setattr__(self, field, _optional_text(getattr(self, field), field))
        if self.status == PENDING and any(
            value is not None
            for value in (self.approved_by, self.approved_at, self.expires_at, self.revoked_by, self.revoked_at)
        ):
            raise ResponsePreferenceIntegrityError("pending preference has lifecycle fields")
        if self.status in {PENDING, APPROVED, SUPERSEDED} and (
            self.revoked_by is not None
            or self.revoked_at is not None
            or self.suspended_reason is not None
        ):
            raise ResponsePreferenceIntegrityError(
                "response preference has lifecycle fields incompatible with status"
            )
        if self.status in {PENDING, APPROVED, REVOKED, SUPERSEDED} and self.suspended_reason is not None:
            raise ResponsePreferenceIntegrityError(
                "response preference has suspension lifecycle incompatible with status"
            )
        if self.status == APPROVED and (
            not self.approved_by or self.approved_at is None or self.expires_at is None
        ):
            raise ResponsePreferenceIntegrityError("approved preference is missing approval lifecycle")
        if self.status == APPROVED and self.expires_at <= self.approved_at:
            raise ResponsePreferenceIntegrityError("approved preference expiry is not after approval")
        if self.status == REVOKED and (not self.revoked_by or self.revoked_at is None):
            raise ResponsePreferenceIntegrityError("revoked preference is missing revocation lifecycle")
        if self.status == SUSPENDED and (
            self.revoked_by is not None or self.revoked_at is not None
        ):
            raise ResponsePreferenceIntegrityError(
                "suspended preference has revocation lifecycle"
            )
        if self.status == SUSPENDED and not self.suspended_reason:
            raise ResponsePreferenceIntegrityError("suspended preference is missing a reason")

    @classmethod
    def from_dict(cls, value: object) -> ResponsePreferenceRecord:
        expected = {
            "candidate_id",
            "scope",
            "parameter",
            "value",
            "source",
            "status",
            "requested_at",
            "approved_by",
            "approved_at",
            "expires_at",
            "revoked_by",
            "revoked_at",
            "suspended_reason",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ResponsePreferenceIntegrityError("invalid response preference record")
        payload = dict(value)
        payload["scope"] = ResponsePreferenceScope.from_dict(payload["scope"])
        payload["source"] = ResponsePreferenceSource.from_dict(payload["source"])
        return cls(**payload)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "scope": self.scope.to_dict(),
            "parameter": self.parameter,
            "value": self.value,
            "source": self.source.to_dict(),
            "status": self.status,
            "requested_at": self.requested_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "expires_at": self.expires_at,
            "revoked_by": self.revoked_by,
            "revoked_at": self.revoked_at,
            "suspended_reason": self.suspended_reason,
        }

    def is_active(self, now: float) -> bool:
        return (
            self.status == APPROVED
            and self.expires_at is not None
            and self.expires_at > now
        )

    def display_status(self, now: float) -> str:
        if self.status == APPROVED and not self.is_active(now):
            return "EXPIRED"
        return self.status


@dataclass(frozen=True, slots=True)
class PreferenceOperationResult:
    success: bool
    code: str
    record: ResponsePreferenceRecord | None = None
    affected: int = 0


def scope_from_event(event: object) -> ResponsePreferenceScope | None:
    """Build a private scope from the existing authoritative event accessors."""

    try:
        key = conversation_key_from_event(event)
        if key is None:
            return None
        return ResponsePreferenceScope.from_conversation_key(key)
    except (ResponsePreferenceScopeError, ResponsePreferenceIntegrityError, ValueError, TypeError):
        return None


def _message_id_from_event(event: object) -> str | None:
    message_obj = getattr(event, "message_obj", None)
    value = getattr(message_obj, "message_id", None)
    if type(value) in (str, int) and str(value).strip():
        return str(value).strip()
    getter = getattr(event, "get_message_id", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:  # noqa: BLE001 - missing platform source is fail-closed
            value = None
        if type(value) in (str, int) and str(value).strip():
            return str(value).strip()
    return None


def source_from_event(event: object, scope: ResponsePreferenceScope) -> ResponsePreferenceSource | None:
    """Return a source reference only when the platform supplied a message id."""

    message_id = _message_id_from_event(event)
    if message_id is None:
        return None
    return ResponsePreferenceSource(
        source_kind=SOURCE_KIND,
        source_event_id=f"{scope.platform_id}:{message_id}",
    )


def source_from_response_length_feedback_aggregate(
    aggregate: object,
) -> ResponsePreferenceSource | None:
    """Create a deterministic source reference for one eligible L09 aggregate.

    The aggregate remains review-only until an administrator approves the
    resulting candidate.  Only its exact scope and four-part feedback-chain
    references enter the digest; raw private message text is never copied to
    the preference store.
    """

    from iris_memory.cognitive.response_preference_feedback import (
        ResponseLengthFeedbackAggregateV1,
    )

    if type(aggregate) is not ResponseLengthFeedbackAggregateV1:
        return None
    if not aggregate.eligible:
        return None
    if type(aggregate.scope) is not ResponsePreferenceScope:
        return None
    if aggregate.parameter != RESPONSE_LENGTH_PARAMETER or aggregate.value != SHORT:
        return None
    refs: list[list[str]] = []
    for reference in aggregate.feedback_refs:
        if type(reference) is not tuple or len(reference) != 4:
            return None
        if any(type(part) is not str or not part.strip() for part in reference):
            return None
        refs.append([part.strip() for part in reference])
    if (
        len(refs) < 2
        or len({reference[0] for reference in refs}) < 2
        or len({reference[3] for reference in refs}) < 2
        or aggregate.distinct_source_event_count != len({reference[0] for reference in refs})
        or aggregate.distinct_host_output_count != len({reference[3] for reference in refs})
    ):
        return None
    payload = {
        "schema_version": RESPONSE_PREFERENCE_SCHEMA_VERSION,
        "scope": aggregate.scope.to_dict(),
        "parameter": aggregate.parameter,
        "value": aggregate.value,
        "feedback_refs": refs,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ResponsePreferenceSource(
        source_kind=RESPONSE_LENGTH_FEEDBACK_AGGREGATE_SOURCE_KIND,
        source_event_id=f"l09:{digest}",
    )


def candidate_id_for(
    scope: ResponsePreferenceScope,
    source: ResponsePreferenceSource,
    value: str,
    parameter: str = RESPONSE_EXPANSION_PARAMETER,
) -> str:
    normalized = normalize_response_preference_value(parameter, value)
    payload = {
        "schema_version": RESPONSE_PREFERENCE_SCHEMA_VERSION,
        "scope": scope.to_dict(),
        "parameter": parameter,
        "value": normalized,
        "source": source.to_dict(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"rspref:{digest}"


def explicit_detail_request(text: object) -> bool:
    """Recognize only the narrow per-turn override; it never changes storage."""

    return type(text) is str and bool(_DETAIL_REQUEST_PATTERN.fullmatch(text))


def format_response_preference(record: ResponsePreferenceRecord | None) -> str:
    """Render one record through the multi-parameter formatter."""

    return format_response_preferences((record,)) if record is not None else ""


def format_response_preferences(records: tuple[ResponsePreferenceRecord, ...] | list[ResponsePreferenceRecord]) -> str:
    """Render approved expression values without changing response authority."""

    by_parameter = {
        record.parameter: record.value
        for record in records
        if record.status == APPROVED
    }
    if not any(
        value == CONCLUSION_FIRST
        for parameter, value in by_parameter.items()
        if parameter == RESPONSE_EXPANSION_PARAMETER
    ) and not any(
        value == SHORT
        for parameter, value in by_parameter.items()
        if parameter == RESPONSE_LENGTH_PARAMETER
    ) and not any(
        value == FAMILIAR
        for parameter, value in by_parameter.items()
        if parameter == RELATIONSHIP_FAMILIARITY_PARAMETER
    ):
        return ""
    lines = [
        RESPONSE_PREFERENCE_MARKER,
        "这是用户在当前这一处私聊中明确提出、并经维护者人工批准的表达偏好。",
    ]
    if by_parameter.get(RESPONSE_EXPANSION_PARAMETER) == CONCLUSION_FIRST:
        lines.append("表达顺序：先给直接结论，再按当前问题需要补充说明。")
    if by_parameter.get(RESPONSE_LENGTH_PARAMETER) == SHORT:
        lines.append(
            "表达长度：默认减少非必要展开，不机械截断；保留必要依据、执行结果和错误信息。"
        )
    if by_parameter.get(RELATIONSHIP_FAMILIARITY_PARAMETER) == FAMILIAR:
        lines.append(
            "互动语气：可使用自然、熟悉的日常语气；不得假定共同经历，"
            "不得声称亲属、恋爱或其他未明确的关系。"
        )
    lines.extend(
        [
            "若用户本轮明确要求详细或完整展开，必须完整展开。",
            "不得因此改变是否回复、工具选择、发送时机、检索量、权限、情绪或角色设定。",
            "这是受控的表达建议，不对模型输出构成强制保证。",
            "</iris:response_style_preference>",
        ]
    )
    return (
        "\n".join(lines)
    )


def format_tool_preference(record: ResponsePreferenceRecord | None) -> str:
    """Render the approved tool hint without granting a new capability."""

    if (
        record is None
        or record.status != APPROVED
        or record.parameter != MEMORY_RETRIEVAL_PARAMETER
        or record.value != MEMORY_RETRIEVAL_ON
    ):
        return ""
    return "\n".join(
        (
            TOOL_PREFERENCE_MARKER,
            "这是当前这一处私聊经维护者批准的工具偏好，仅作当前请求的辅助建议。",
            "若当前请求明确要求回忆历史信息，可优先使用已有 search_memory 只读记忆检索。",
            "不得因此新增工具权限、调用网络工具、发送消息、付费、删除数据或跳过必要操作。",
            "若用户本轮明确要求不联网、不调用工具或不检索，以本轮要求为准。",
            "</iris:tool_preference>",
        )
    )


def scope_matches(left: ResponsePreferenceScope, right: ResponsePreferenceScope) -> bool:
    return left == right
