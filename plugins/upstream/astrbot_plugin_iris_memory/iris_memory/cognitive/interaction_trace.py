"""Passive, bounded interaction tracing for the P2x migration baseline.

This module deliberately has no execution authority.  It snapshots only small,
JSON-safe facts from an AstrBot event and observes the existing Host lifecycle;
it never stops, re-dispatches, edits, delays, or sends anything.  The shadow
quiet window is evaluated lazily when another event or read/observation surface
is used, so no timer or await is introduced into the production message path.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType

TRACE_SCHEMA_VERSION = "p2x.interaction-trace.v1"
DEFAULT_SHADOW_QUIET_WINDOW_SECONDS = 3.0
DEFAULT_STATE_TTL_SECONDS = 60.0
DEFAULT_MAX_CONVERSATIONS = 256
DEFAULT_MAX_PENDING_EVENTS = 32
DEFAULT_MAX_COMPLETED_TRACES = 512


class ScopeKind(str, Enum):
    """Closed scope values used by ``ConversationKeyV1``."""

    PRIVATE = "PRIVATE"
    GROUP = "GROUP"


def _text(value: object) -> str | None:
    if type(value) is str:
        value = value.strip()
        return value or None
    if type(value) is int:
        return str(value)
    return None


def _scalar(value: object) -> str | int | float | bool | None:
    if value is None or type(value) in (str, int, float, bool):
        return value
    candidate = getattr(value, "value", None)
    if candidate is not None and type(candidate) in (str, int, float, bool):
        return candidate
    return None


def _call(event: object, method_name: str) -> object | None:
    method = getattr(event, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:  # noqa: BLE001 - passive tracing must never affect Host
        return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _freeze_trace_value(value: object) -> object:
    """Detach the small trace schema from caller-owned containers."""

    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Enum):
        return _freeze_trace_value(value.value)
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("trace mapping keys must be strings")
            frozen[key] = _freeze_trace_value(item)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(_freeze_trace_value(item) for item in value)
    raise TypeError(f"unsupported mutable trace value: {type(value).__name__}")


def _component_metadata(component: object) -> Mapping[str, object]:
    """Return a detached, deliberately small description of one chain item.

    Unknown component types are represented by their type name only.  We never
    retain a component, call ``repr``, or traverse ``__dict__``.
    """

    type_name = type(component).__name__
    fields: dict[str, object] = {"type": type_name}
    for name in ("text", "id", "message_id", "user_id", "name"):
        value = _scalar(getattr(component, name, None))
        if value is None:
            continue
        if name == "text" and type(value) is str:
            fields["text_length"] = len(value)
            fields["text_sha256"] = _sha256_text(value)
        elif name in {"id", "message_id", "user_id"}:
            fields[name] = value
        else:
            fields[name] = value
    # Media components are useful for ordering/correlation, but their URLs or
    # local paths are not needed in a passive trace and must not be persisted.
    if any(token in type_name.casefold() for token in ("image", "file", "record", "video")):
        fields["media"] = True
    return MappingProxyType(fields)


def _reply_metadata(components: tuple[object, ...]) -> Mapping[str, object]:
    for component in components:
        type_name = type(component).__name__.casefold()
        if "reply" not in type_name:
            continue
        for name in ("id", "message_id"):
            value = _text(getattr(component, name, None))
            if value is not None:
                return MappingProxyType({"has_reply": True, "target_message_id": value})
        return MappingProxyType({"has_reply": True})
    return MappingProxyType({"has_reply": False})


@dataclass(frozen=True, slots=True)
class ConversationKeyV1:
    """Platform-authoritative conversation identity for the shadow trace."""

    platform_id: str
    account_id: str
    scope_kind: ScopeKind
    conversation_id: str

    def __post_init__(self) -> None:
        try:
            scope_value = ScopeKind(self.scope_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("ConversationKeyV1 scope_kind is not closed") from exc
        object.__setattr__(self, "scope_kind", scope_value)
        for name in ("platform_id", "account_id", "conversation_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"ConversationKeyV1 requires {name}")
        object.__setattr__(self, "platform_id", self.platform_id.strip())
        object.__setattr__(self, "account_id", self.account_id.strip())
        object.__setattr__(self, "conversation_id", self.conversation_id.strip())

    def as_dict(self) -> dict[str, str]:
        return {
            "platform_id": self.platform_id,
            "account_id": self.account_id,
            "scope_kind": self.scope_kind,
            "conversation_id": self.conversation_id,
        }


@dataclass(frozen=True, slots=True)
class RawEventEnvelopeV1:
    """Detached factual input snapshot used only by the passive tracer."""

    conversation_key: ConversationKeyV1
    legacy_umo: str | None
    source_event_id: str | None
    message_chain: tuple[Mapping[str, object], ...]
    reply_metadata: Mapping[str, object]
    observed_order: int
    received_at: datetime
    source_provenance: tuple[str, ...] = ("astrbot_event",)

    def __post_init__(self) -> None:
        if self.legacy_umo is not None and type(self.legacy_umo) is not str:
            raise TypeError("RawEventEnvelopeV1 legacy_umo must be a string")
        if self.source_event_id is not None and type(self.source_event_id) is not str:
            raise TypeError("RawEventEnvelopeV1 source_event_id must be a string")
        if self.observed_order < 1:
            raise ValueError("RawEventEnvelopeV1 observed_order must be positive")
        if self.received_at.tzinfo is None:
            raise ValueError("RawEventEnvelopeV1 received_at must be timezone-aware")
        chain = tuple(_freeze_trace_value(item) for item in self.message_chain)
        if any(not isinstance(item, Mapping) for item in chain):
            raise TypeError("RawEventEnvelopeV1 message_chain must contain mappings")
        reply_metadata = _freeze_trace_value(self.reply_metadata)
        if not isinstance(reply_metadata, Mapping):
            raise TypeError("RawEventEnvelopeV1 reply_metadata must be a mapping")
        provenance = tuple(self.source_provenance)
        if any(type(item) is not str for item in provenance):
            raise TypeError("RawEventEnvelopeV1 source_provenance must contain strings")
        object.__setattr__(self, "message_chain", chain)
        object.__setattr__(self, "reply_metadata", reply_metadata)
        object.__setattr__(self, "source_provenance", provenance)


@dataclass(frozen=True, slots=True)
class CandidateTurnTraceV1:
    """A diagnostic grouping with no Host execution authority."""

    turn_id: str
    conversation_key: ConversationKeyV1
    raw_events: tuple[RawEventEnvelopeV1, ...]
    actual_host_executions: int = 0
    logical_host_results: int = 0
    actual_send_count: int = 0
    h0_receipt_count: int = 0
    legacy_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(type(value) is not str for value in self.legacy_features):
            raise TypeError("CandidateTurnTraceV1 legacy_features must contain strings")
        if min(
            self.actual_host_executions,
            self.logical_host_results,
            self.actual_send_count,
            self.h0_receipt_count,
        ) < 0:
            raise ValueError("CandidateTurnTraceV1 counters cannot be negative")
        object.__setattr__(self, "raw_events", tuple(self.raw_events))
        object.__setattr__(self, "legacy_features", tuple(sorted(set(self.legacy_features))))


@dataclass(frozen=True, slots=True)
class InteractionTraceMetricsV1:
    """Read-only cumulative counters for the passive trace."""

    raw_events: int = 0
    candidate_turns: int = 0
    actual_host_executions: int = 0
    legacy_umo_continuity: int = 0
    logical_host_results: int = 0
    actual_send_count: int = 0
    h0_receipt_count: int = 0
    active_candidate_turns: int = 0

    @property
    def raw_events_per_candidate_turn(self) -> float:
        return self.raw_events / self.candidate_turns if self.candidate_turns else 0.0

    @property
    def host_executions_per_candidate_turn(self) -> float:
        return self.actual_host_executions / self.candidate_turns if self.candidate_turns else 0.0

    @property
    def sends_per_logical_host_result(self) -> float:
        return self.actual_send_count / self.logical_host_results if self.logical_host_results else 0.0


@dataclass(slots=True)
class _Pending:
    envelope: RawEventEnvelopeV1
    trace: CandidateTurnTraceV1
    last_seen: float


def conversation_key_from_event(event: object) -> ConversationKeyV1 | None:
    """Resolve identity from explicit AstrBot/platform accessors only.

    ``is_private_chat()`` is the scope authority.  Group/private IDs are read
    through the platform event accessors; no UMO parsing or ID-shape heuristic
    is used.  Unsupported or incomplete host events are simply untraceable.
    """

    platform_id = _text(_call(event, "get_platform_id"))
    account_id = _text(_call(event, "get_self_id"))
    private = _call(event, "is_private_chat")
    if platform_id is None or account_id is None or type(private) is not bool:
        return None
    if private:
        conversation_id = _text(_call(event, "get_sender_id"))
        scope = ScopeKind.PRIVATE
    else:
        conversation_id = _text(_call(event, "get_group_id"))
        scope = ScopeKind.GROUP
    if conversation_id is None:
        return None
    try:
        return ConversationKeyV1(platform_id, account_id, scope, conversation_id)
    except ValueError:
        return None


def raw_event_from_event(event: object, observed_order: int) -> RawEventEnvelopeV1 | None:
    key = conversation_key_from_event(event)
    if key is None:
        return None
    message_obj = getattr(event, "message_obj", None)
    source_event_id = _text(getattr(message_obj, "message_id", None))
    legacy_umo = _text(getattr(event, "unified_msg_origin", None))
    raw_components = _call(event, "get_messages")
    if type(raw_components) not in (list, tuple):
        raw_components = ()
    components = tuple(raw_components)
    return RawEventEnvelopeV1(
        conversation_key=key,
        legacy_umo=legacy_umo,
        source_event_id=source_event_id,
        message_chain=tuple(_component_metadata(item) for item in components),
        reply_metadata=_reply_metadata(components),
        observed_order=observed_order,
        received_at=datetime.now(timezone.utc),
    )


class PassiveInteractionTraceV1:
    """Bounded shadow grouping and lifecycle correlation with zero authority."""

    owner = "Iris Passive Interaction Trace V1"

    def __init__(
        self,
        *,
        quiet_window_seconds: float = DEFAULT_SHADOW_QUIET_WINDOW_SECONDS,
        state_ttl_seconds: float = DEFAULT_STATE_TTL_SECONDS,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_pending_events: int = DEFAULT_MAX_PENDING_EVENTS,
        max_completed_traces: int = DEFAULT_MAX_COMPLETED_TRACES,
    ) -> None:
        if quiet_window_seconds <= 0 or state_ttl_seconds <= 0:
            raise ValueError("trace windows must be positive")
        if min(max_conversations, max_pending_events, max_completed_traces) < 1:
            raise ValueError("trace bounds must be positive")
        self.quiet_window_seconds = float(quiet_window_seconds)
        self.state_ttl_seconds = float(state_ttl_seconds)
        self.max_conversations = int(max_conversations)
        self.max_pending_events = int(max_pending_events)
        self.max_completed_traces = int(max_completed_traces)
        self._pending: OrderedDict[ConversationKeyV1, _Pending] = OrderedDict()
        self._completed: deque[CandidateTurnTraceV1] = deque(maxlen=self.max_completed_traces)
        self._sequence = 0
        self._closed = False
        self._raw_events = 0
        self._candidate_turns = 0
        self._actual_host_executions = 0
        self._legacy_umo_continuity = 0
        self._logical_host_results = 0
        self._actual_send_count = 0
        self._h0_receipt_count = 0
        # Continuity metadata shares the same bounded conversation lifecycle as
        # pending traces.  The timestamp is the last inbound observation used
        # for TTL eviction; quiet-window completion intentionally retains it so
        # a subsequent turn can still report UMO continuity within the TTL.
        self._last_umo: OrderedDict[ConversationKeyV1, tuple[str | None, float]] = OrderedDict()

    @property
    def closed(self) -> bool:
        return self._closed

    def observe_inbound(self, event: object, *, now: float | None = None) -> CandidateTurnTraceV1 | None:
        """Snapshot one raw event and update a shadow candidate synchronously."""

        if self._closed:
            return None
        now_value = time.monotonic() if now is None else float(now)
        self._sweep(now_value)
        self._sequence += 1
        envelope = raw_event_from_event(event, self._sequence)
        if envelope is None:
            return None
        self._raw_events += 1
        if envelope.source_event_id is None:
            # Raw events without a stable source identity remain untraceable;
            # passive instrumentation must not invent an object/time identity.
            return None
        prior_state = self._last_umo.get(envelope.conversation_key)
        prior_umo = prior_state[0] if prior_state is not None else None
        if prior_umo is not None and prior_umo == envelope.legacy_umo:
            self._legacy_umo_continuity += 1
        self._last_umo[envelope.conversation_key] = (envelope.legacy_umo, now_value)
        self._last_umo.move_to_end(envelope.conversation_key)

        pending = self._pending.get(envelope.conversation_key)
        if (
            pending is not None
            and now_value - pending.last_seen <= self.quiet_window_seconds
            and len(pending.trace.raw_events) < self.max_pending_events
        ):
            events = pending.trace.raw_events + (envelope,)
            trace = replace(pending.trace, raw_events=events, turn_id=self._turn_id(envelope.conversation_key, events))
            pending.envelope = envelope
            pending.trace = trace
            pending.last_seen = now_value
            self._pending.move_to_end(envelope.conversation_key)
            return trace

        if pending is not None:
            self._completed.append(pending.trace)
            self._pending.pop(envelope.conversation_key, None)
        self._candidate_turns += 1
        trace = CandidateTurnTraceV1(
            turn_id=self._turn_id(envelope.conversation_key, (envelope,)),
            conversation_key=envelope.conversation_key,
            raw_events=(envelope,),
        )
        self._pending[envelope.conversation_key] = _Pending(envelope, trace, now_value)
        self._pending.move_to_end(envelope.conversation_key)
        while len(self._pending) > self.max_conversations:
            _key, evicted = self._pending.popitem(last=False)
            self._completed.append(evicted.trace)
            self._last_umo.pop(_key, None)
        self._enforce_bounds()
        return trace

    def observe_host_execution(self, event: object, *, now: float | None = None) -> None:
        if self._closed:
            return
        self._sweep(time.monotonic() if now is None else float(now))
        self._actual_host_executions += 1
        pending = self._pending_for_event(event)
        if pending is not None:
            pending.trace = replace(
                pending.trace,
                actual_host_executions=pending.trace.actual_host_executions + 1,
            )

    def observe_logical_response(
        self,
        event: object,
        response: object,
        *,
        now: float | None = None,
    ) -> None:
        del response  # The tracer records lifecycle cardinality, not raw output.
        if self._closed:
            return
        self._sweep(time.monotonic() if now is None else float(now))
        self._logical_host_results += 1
        pending = self._pending_for_event(event)
        if pending is not None:
            pending.trace = replace(
                pending.trace,
                logical_host_results=pending.trace.logical_host_results + 1,
            )

    def observe_send_receipt(
        self,
        event: object,
        result: object,
        *,
        now: float | None = None,
    ) -> None:
        if self._closed:
            return
        self._sweep(time.monotonic() if now is None else float(now))
        operations = getattr(result, "operations", None)
        if type(operations) not in (tuple, list):
            return
        schema_version = getattr(result, "schema_version", None)
        if schema_version != "astrbot.host-send-result.v1":
            return
        successful = 0
        for operation in operations:
            status = getattr(getattr(operation, "status", None), "value", getattr(operation, "status", None))
            kind = getattr(getattr(operation, "operation_kind", None), "value", getattr(operation, "operation_kind", None))
            if status == "SEND_SUCCEEDED_WITH_IDENTITY" and kind == "MESSAGE":
                successful += 1
        self._h0_receipt_count += 1
        pending = self._pending_for_event(event)
        if pending is not None:
            pending.trace = replace(
                pending.trace,
                actual_send_count=pending.trace.actual_send_count + successful,
                h0_receipt_count=pending.trace.h0_receipt_count + 1,
            )
        if successful:
            self._actual_send_count += successful

    def mark_legacy_feature(
        self,
        event: object,
        feature: str,
        *,
        now: float | None = None,
    ) -> None:
        """Record an explicitly supplied legacy marker without inspecting plugins."""

        if self._closed or type(feature) is not str or not feature.strip():
            return
        self._sweep(time.monotonic() if now is None else float(now))
        pending = self._pending_for_event(event)
        if pending is None:
            return
        pending.trace = replace(
            pending.trace,
            legacy_features=tuple(sorted(set(pending.trace.legacy_features) | {feature.strip()})),
        )

    def snapshot(self, *, now: float | None = None) -> InteractionTraceMetricsV1:
        if not self._closed:
            self._sweep(time.monotonic() if now is None else float(now))
        return InteractionTraceMetricsV1(
            raw_events=self._raw_events,
            candidate_turns=self._candidate_turns,
            actual_host_executions=self._actual_host_executions,
            legacy_umo_continuity=self._legacy_umo_continuity,
            logical_host_results=self._logical_host_results,
            actual_send_count=self._actual_send_count,
            h0_receipt_count=self._h0_receipt_count,
            active_candidate_turns=len(self._pending),
        )

    def active_candidates(self, *, now: float | None = None) -> tuple[CandidateTurnTraceV1, ...]:
        if not self._closed:
            self._sweep(time.monotonic() if now is None else float(now))
        return tuple(pending.trace for pending in self._pending.values())

    def completed_candidates(self, *, now: float | None = None) -> tuple[CandidateTurnTraceV1, ...]:
        if not self._closed:
            self._sweep(time.monotonic() if now is None else float(now))
        return tuple(self._completed)

    def close(self) -> None:
        if self._closed:
            return
        for pending in self._pending.values():
            self._completed.append(pending.trace)
        self._pending.clear()
        self._closed = True

    def _pending_for_event(self, event: object) -> _Pending | None:
        key = conversation_key_from_event(event)
        return self._pending.get(key) if key is not None else None

    def _sweep(self, now: float) -> None:
        """Lazily finalize quiet candidates and evict expired trace state."""

        quiet_or_expired = [
            key
            for key, pending in self._pending.items()
            if now - pending.last_seen > self.quiet_window_seconds
            or now - pending.last_seen > self.state_ttl_seconds
        ]
        for key in quiet_or_expired:
            pending = self._pending.pop(key, None)
            if pending is not None:
                self._completed.append(pending.trace)

        expired_umo = [
            key
            for key, (_umo, last_seen) in self._last_umo.items()
            if now - last_seen > self.state_ttl_seconds
        ]
        for key in expired_umo:
            self._last_umo.pop(key, None)
            pending = self._pending.pop(key, None)
            if pending is not None:
                self._completed.append(pending.trace)

        self._enforce_bounds()

    def _enforce_bounds(self) -> None:
        while len(self._pending) > self.max_conversations:
            key, evicted = self._pending.popitem(last=False)
            self._last_umo.pop(key, None)
            self._completed.append(evicted.trace)
        while len(self._last_umo) > self.max_conversations:
            key, _state = self._last_umo.popitem(last=False)
            pending = self._pending.pop(key, None)
            if pending is not None:
                self._completed.append(pending.trace)

    def _evict(self, now: float) -> None:
        """Backward-compatible internal alias for the lazy sweep."""

        self._sweep(now)

    @staticmethod
    def _turn_id(key: ConversationKeyV1, events: tuple[RawEventEnvelopeV1, ...]) -> str:
        payload = {
            "schema": TRACE_SCHEMA_VERSION,
            "conversation_key": key.as_dict(),
            "raw_source_ids": [event.source_event_id for event in events],
        }
        return f"turn:v1:{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


__all__ = [
    "CandidateTurnTraceV1",
    "ConversationKeyV1",
    "InteractionTraceMetricsV1",
    "PassiveInteractionTraceV1",
    "RawEventEnvelopeV1",
    "ScopeKind",
    "conversation_key_from_event",
    "raw_event_from_event",
]
