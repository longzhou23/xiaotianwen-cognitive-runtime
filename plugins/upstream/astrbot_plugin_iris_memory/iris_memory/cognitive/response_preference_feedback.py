"""Pure, non-publishing feedback evaluation for response preferences.

The existing P2r.0 reply-link authority is the only accepted join between an
inbound correction and a Host output.  This module records no ReviewEvidence,
does not write the response-preference store, and never falls back to the
most recent output.  It only creates an explanatory candidate when the
utterance and the exact inbound/reply-link chain agree.
"""

from __future__ import annotations

import math
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from .reply_link_authority import (
    ExactHostReplyLinkStatus,
    ExactHostReplyLinkV1,
    InboundReplyReferenceFactV1,
    P2r0IntegrityError,
    P2r0Store,
    P2rReplyLinkFactArchiveV1,
)

RESPONSE_LENGTH_FEEDBACK_SCHEMA = "response-length-feedback.v1"
RESPONSE_LENGTH_FEEDBACK_KIND = "RESPONSE_LENGTH_TOO_LONG"
FEEDBACK_EVIDENCE_ACTIVE = "ACTIVE"
FEEDBACK_EVIDENCE_REVOKED = "REVOKED"
FEEDBACK_EVIDENCE_CONFLICTED = "CONFLICTED"
FEEDBACK_EVIDENCE_STATES = frozenset(
    {
        FEEDBACK_EVIDENCE_ACTIVE,
        FEEDBACK_EVIDENCE_REVOKED,
        FEEDBACK_EVIDENCE_CONFLICTED,
    }
)
RESPONSE_LENGTH_FEEDBACK_AGGREGATION_BLOCKED_REASON = "d02_threshold_not_frozen"
RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON = (
    "d02_insufficient_independent_evidence"
)
RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON = (
    "d02_threshold_met_review_only"
)
RESPONSE_LENGTH_FEEDBACK_MIN_INDEPENDENT_EVIDENCE = 2
RESPONSE_LENGTH_FEEDBACK_WINDOW_SECONDS = 30 * 24 * 60 * 60
_TOO_LONG_PATTERN = re.compile(r"^\s*这段太长\s*[。.!！?？]?\s*$")


@dataclass(frozen=True, slots=True)
class ResponseLengthFeedbackCandidateV1:
    """A review-only explanation candidate, never a published preference."""

    schema_version: str
    kind: str
    source_event_id: str
    inbound_reply_fact_id: str
    exact_reply_link_id: str
    host_output_fact_id: str

    def __post_init__(self) -> None:
        if self.schema_version != RESPONSE_LENGTH_FEEDBACK_SCHEMA:
            raise ValueError("unknown response-length feedback schema")
        if self.kind != RESPONSE_LENGTH_FEEDBACK_KIND:
            raise ValueError("unknown response-length feedback kind")
        for name in (
            "source_event_id",
            "inbound_reply_fact_id",
            "exact_reply_link_id",
            "host_output_fact_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ResponseLengthFeedbackEvaluationV1:
    candidate: ResponseLengthFeedbackCandidateV1 | None
    reason: str


def _is_response_preference_scope(value: object) -> bool:
    """Check the existing response-preference scope owner without a module cycle."""

    from iris_memory.profile.response_preferences import ResponsePreferenceScope

    return type(value) is ResponsePreferenceScope


def _as_utc_datetime(value: object) -> datetime | None:
    """Accept only an aware event clock; never invent a timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ResponseLengthFeedbackAggregationInputV1:
    """One exact feedback candidate and its current authoritative lifecycle state.

    This is an in-memory review input.  The scope is the existing
    ``ResponsePreferenceScope`` object; this module does not define another
    identity or storage owner.
    """

    candidate: ResponseLengthFeedbackCandidateV1
    scope: object
    occurred_at: datetime
    evidence_state: str = FEEDBACK_EVIDENCE_ACTIVE

    def __post_init__(self) -> None:
        if type(self.candidate) is not ResponseLengthFeedbackCandidateV1:
            raise ValueError("aggregation input requires an exact feedback candidate")
        if not _is_response_preference_scope(self.scope):
            raise ValueError("aggregation input requires the existing private response scope")
        occurred_at = _as_utc_datetime(self.occurred_at)
        if occurred_at is None:
            raise ValueError("aggregation input requires an aware authoritative event time")
        object.__setattr__(self, "occurred_at", occurred_at)
        if self.evidence_state not in FEEDBACK_EVIDENCE_STATES:
            raise ValueError("unknown feedback evidence state")

    @property
    def feedback_identity(self) -> tuple[str, str, str, str]:
        """Return the immutable exact chain identity used for replay de-duplication."""

        candidate = self.candidate
        return (
            candidate.source_event_id,
            candidate.inbound_reply_fact_id,
            candidate.exact_reply_link_id,
            candidate.host_output_fact_id,
        )


@dataclass(frozen=True, slots=True)
class ResponseLengthFeedbackAggregateV1:
    """Read-only aggregate for one exact private scope.

    ``eligible`` means the frozen D02 observation threshold is met for a
    review-only candidate.  It never creates a preference record or affects a
    request; the existing manual approval path remains a later step.
    """

    scope: object
    parameter: str
    value: str
    feedback_refs: tuple[tuple[str, str, str, str], ...]
    invalidated_feedback_refs: tuple[tuple[str, str, str, str], ...]
    out_of_window_feedback_refs: tuple[tuple[str, str, str, str], ...]
    distinct_source_event_count: int
    distinct_reply_link_count: int
    distinct_host_output_count: int
    eligible: bool
    reason: str

    def __post_init__(self) -> None:
        if not _is_response_preference_scope(self.scope):
            raise ValueError("aggregate requires the existing private response scope")
        if self.parameter != "response_length" or self.value != "SHORT":
            raise ValueError("aggregate must use the closed response-length parameter")
        if type(self.eligible) is not bool:
            raise ValueError("aggregate eligibility must be a boolean")
        if self.reason not in {
            RESPONSE_LENGTH_FEEDBACK_AGGREGATION_BLOCKED_REASON,
            RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON,
            RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON,
        }:
            raise ValueError("feedback aggregate has an unexpected eligibility reason")
        if self.eligible != (
            self.reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON
        ):
            raise ValueError("aggregate eligibility and reason disagree")
        object.__setattr__(self, "feedback_refs", tuple(self.feedback_refs))
        object.__setattr__(self, "invalidated_feedback_refs", tuple(self.invalidated_feedback_refs))
        object.__setattr__(self, "out_of_window_feedback_refs", tuple(self.out_of_window_feedback_refs))

    @property
    def distinct_feedback_count(self) -> int:
        """Return active exact chains after replay and invalidation handling."""

        return len(self.feedback_refs)


def is_explicit_length_feedback(text: object) -> bool:
    """Recognize only the exact single-output length evaluation."""

    return type(text) is str and bool(_TOO_LONG_PATTERN.fullmatch(text))


def evaluate_response_length_feedback(
    text: object,
    *,
    inbound_fact: InboundReplyReferenceFactV1 | None,
    reply_link: ExactHostReplyLinkV1 | None,
) -> ResponseLengthFeedbackEvaluationV1:
    """Evaluate one feedback message against one authoritative link.

    Every failed join returns a stable reason and no candidate.  A factual
    correction such as ``你说错了`` therefore remains outside this length
    feedback path.
    """

    if not is_explicit_length_feedback(text):
        return ResponseLengthFeedbackEvaluationV1(None, "not_explicit_length_feedback")
    if type(inbound_fact) is not InboundReplyReferenceFactV1:
        return ResponseLengthFeedbackEvaluationV1(None, "missing_inbound_reply_fact")
    if type(reply_link) is not ExactHostReplyLinkV1:
        return ResponseLengthFeedbackEvaluationV1(None, "missing_exact_reply_link")
    if reply_link.status != ExactHostReplyLinkStatus.EXACT_REPLY_LINK.value:
        return ResponseLengthFeedbackEvaluationV1(None, "reply_link_not_exact")
    if reply_link.inbound_reply_fact_id != inbound_fact.fact_id:
        return ResponseLengthFeedbackEvaluationV1(None, "reply_link_inbound_mismatch")
    if reply_link.host_output_fact_id is None:
        return ResponseLengthFeedbackEvaluationV1(None, "reply_link_host_output_missing")
    candidate = ResponseLengthFeedbackCandidateV1(
        schema_version=RESPONSE_LENGTH_FEEDBACK_SCHEMA,
        kind=RESPONSE_LENGTH_FEEDBACK_KIND,
        source_event_id=inbound_fact.source_event_id,
        inbound_reply_fact_id=inbound_fact.fact_id,
        exact_reply_link_id=reply_link.link_id,
        host_output_fact_id=reply_link.host_output_fact_id,
    )
    return ResponseLengthFeedbackEvaluationV1(candidate, "exact_reply_link")


def _authoritative_event_time(event: object) -> datetime | None:
    """Read only the platform timestamp used by the existing pre-adapter.

    The pre-adapter has a runtime fallback for general cognitive processing.
    L09 cannot use that fallback because a feedback window must be based on an
    authoritative event clock.  Missing, malformed, or non-finite raw time is
    therefore rejected here.
    """

    message_obj = getattr(event, "message_obj", None)
    raw = getattr(message_obj, "raw_message", None)
    if not isinstance(raw, Mapping):
        return None
    raw_time = raw.get("time")
    if raw_time is None:
        raw_time = raw.get("timestamp")
    if type(raw_time) not in (int, float) or type(raw_time) is bool:
        return None
    if not math.isfinite(raw_time):
        return None
    try:
        return datetime.fromtimestamp(float(raw_time), timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class ResponseLengthFeedbackReviewObserverV1:
    """Adapt existing P2r0 capture/archive callbacks into L09 review input.

    The optional append-only observation journal stores no message text.
    Pending observations are rejoined to the authoritative archive after
    restart; the journal cannot manufacture a Host output or publish a
    preference. Existing callers without a path remain memory-only.
    """

    owner = "L09 Response Length Feedback Review Observer"

    def __init__(self, journal_path: str | Path | None = None) -> None:
        self._archive_store: P2r0Store | None = None
        self._pending: dict[str, list[tuple[object, datetime]]] = {}
        self._observations: dict[
            tuple[tuple[str, str, str, str], object, datetime, str],
            ResponseLengthFeedbackAggregationInputV1,
        ] = {}
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._journal_failed = False
        self._pending_sources: dict[str, str] = {}
        self._invalidations: dict[tuple[str, ...], str] = {}
        if self._journal_path is not None:
            try:
                self._replay_journal()
            except (OSError, ValueError, TypeError, KeyError):
                self._journal_failed = True
                logger.error("Feedback observation replay unavailable; consolidation disabled")

    @staticmethod
    def _journal_hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()

    def _read_journal(self) -> list[dict]:
        from iris_memory.profile.response_preferences import ResponsePreferenceScope

        path = self._journal_path
        if path is None or not path.exists():
            return []
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("incomplete feedback journal; manual recovery required")
        records = []
        for line in raw.splitlines():
            envelope = json.loads(line)
            if set(envelope) != {"payload", "sha256"}:
                raise ValueError("invalid feedback envelope")
            row = envelope["payload"]
            if self._journal_hash(row) != envelope["sha256"]:
                raise ValueError("feedback journal checksum mismatch")
            if set(row) != {"schema", "chain", "scope", "occurred_at", "state"}:
                raise ValueError("unknown feedback fields")
            if row["schema"] != "response_length_feedback_observation:v1":
                raise ValueError("unknown feedback observation schema")
            chain = row["chain"]
            if type(chain) is not list or len(chain) not in (2, 4):
                raise ValueError("invalid exact feedback chain")
            if any(type(ref) is not str or not ref.strip() for ref in chain):
                raise ValueError("empty feedback reference")
            ResponsePreferenceScope.from_dict(row["scope"])
            if _as_utc_datetime(datetime.fromisoformat(row["occurred_at"])) is None:
                raise ValueError("missing authoritative feedback time")
            if row["state"] not in FEEDBACK_EVIDENCE_STATES:
                raise ValueError("unknown feedback lifecycle")
            if len(chain) == 2 and row["state"] != FEEDBACK_EVIDENCE_ACTIVE:
                raise ValueError("invalidation requires a complete exact chain")
            records.append(row)
        return records

    def _replay_journal(self, *, owned_lock: bool = False) -> None:
        from iris_memory.profile.response_preferences import ResponsePreferenceScope

        if (self._journal_path is not None and not owned_lock
                and self._journal_path.with_suffix(self._journal_path.suffix + ".lock").exists()):
            raise OSError("feedback journal is locked; explicit recovery may be required")
        rows = self._read_journal()
        pending: dict[str, list[tuple[object, datetime]]] = {}
        sources: dict[str, str] = {}
        invalidations: dict[tuple[str, ...], str] = {}
        for row in rows:
            chain = row["chain"]
            scope = ResponsePreferenceScope.from_dict(row["scope"])
            occurred_at = datetime.fromisoformat(row["occurred_at"])
            if len(chain) == 2:
                previous = sources.setdefault(chain[1], chain[0])
                entries = pending.setdefault(chain[1], [])
                if previous != chain[0] or any(s != scope for s, _ in entries):
                    raise ValueError("conflicting feedback source identity")
                if (scope, occurred_at) not in entries:
                    entries.append((scope, occurred_at))
            elif row["state"] != FEEDBACK_EVIDENCE_ACTIVE:
                key = tuple(chain)
                if invalidations.get(key) != FEEDBACK_EVIDENCE_CONFLICTED:
                    invalidations[key] = row["state"]
        self._pending = pending
        self._pending_sources = sources
        self._invalidations = invalidations
        self._observations.clear()

    def _append_observation(self, chain: tuple[str, ...], scope: object,
                            occurred_at: datetime, state: str) -> bool:
        if self._journal_failed:
            return False
        path = self._journal_path
        if path is None:
            return True
        row = {"schema": "response_length_feedback_observation:v1",
               "chain": list(chain), "scope": scope.to_dict(),
               "occurred_at": occurred_at.isoformat(), "state": state}
        lock = path.with_suffix(path.suffix + ".lock")
        acquired = False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive directory acquisition is cross-process and fail-fast.
            # A crash leaves the lock for explicit operator recovery.
            lock.mkdir()
            acquired = True
            rows = self._read_journal()
            if row not in rows:
                encoded = (json.dumps({"payload": row, "sha256": self._journal_hash(row)},
                                      ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "ab") as handle:
                    if handle.write(encoded) != len(encoded):
                        raise OSError("short feedback journal write")
                    handle.flush()
                    os.fsync(handle.fileno())
                if os.name == "posix":
                    directory = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            self._replay_journal(owned_lock=True)
            return True
        except (OSError, ValueError, TypeError, KeyError):
            self._journal_failed = True
            self._observations.clear()
            logger.error("Feedback observation append unavailable; consolidation disabled")
            return False
        finally:
            if acquired:
                try:
                    lock.rmdir()
                except OSError:
                    self._journal_failed = True

    def invalidate_observation(self, item: ResponseLengthFeedbackAggregationInputV1,
                               state: str) -> bool:
        """Explicit owner API; cannot revoke by text, nickname or recent output."""
        if state not in {FEEDBACK_EVIDENCE_REVOKED, FEEDBACK_EVIDENCE_CONFLICTED}:
            return False
        if self._archive_store is None:
            return False
        self.refresh_archives()
        if item not in self.observations:
            return False
        if not self._append_observation(item.feedback_identity, item.scope, item.occurred_at, state):
            return False
        key = item.feedback_identity
        if self._invalidations.get(key) != FEEDBACK_EVIDENCE_CONFLICTED:
            self._invalidations[key] = state
        self._observations.clear()
        self.refresh_archives()
        return True

    @property
    def observations(self) -> tuple[ResponseLengthFeedbackAggregationInputV1, ...]:
        """Expose the current in-memory review inputs for read-only review/tests."""

        return () if self._journal_failed else tuple(self._observations.values())

    def bind_archive_store(self, store: P2r0Store) -> None:
        """Bind the existing authoritative P2r0 store without taking ownership."""

        if type(store) is not P2r0Store:
            raise TypeError("feedback observer requires the authoritative P2r0Store")
        self._archive_store = store
        self.refresh_archives()

    def observe_inbound_event(
        self, event: object, inbound_fact: InboundReplyReferenceFactV1 | None
    ) -> str:
        """Observe the existing inbound capture hook with strict raw time."""

        from iris_memory.profile.response_preferences import scope_from_event

        text = getattr(event, "message_str", None)
        try:
            scope = scope_from_event(event)
        except Exception:  # noqa: BLE001 - an absent platform scope fails closed
            scope = None
        return self.observe_inbound(
            text=text,
            scope=scope,
            occurred_at=_authoritative_event_time(event),
            inbound_fact=inbound_fact,
        )

    def observe_inbound(
        self,
        *,
        text: object,
        scope: object,
        occurred_at: object,
        inbound_fact: InboundReplyReferenceFactV1 | None,
    ) -> str:
        """Queue one exact correction until Review/archive exposes its link."""

        if self._journal_failed:
            return "observation_storage_unavailable"
        if not is_explicit_length_feedback(text):
            return "not_explicit_length_feedback"
        if type(inbound_fact) is not InboundReplyReferenceFactV1:
            return "missing_inbound_reply_fact"
        if not _is_response_preference_scope(scope):
            return "missing_private_response_scope"
        normalized_time = _as_utc_datetime(occurred_at)
        if normalized_time is None:
            return "missing_authoritative_event_time"
        source = inbound_fact.source_platform_message_identity
        if (
            scope.platform_id,
            scope.account_id,
            scope.user_id,
            scope.conversation_id,
        ) != (
            source.platform_id,
            source.account_id,
            source.conversation_id,
            source.conversation_id,
        ):
            return "scope_inbound_identity_mismatch"

        pending = self._pending.setdefault(inbound_fact.fact_id, [])
        if pending and any(existing_scope != scope for existing_scope, _ in pending):
            return "scope_inbound_identity_conflict"
        if (scope, normalized_time) not in pending:
            # A replay at the same time is de-duplicated here.  A different
            # authoritative time is retained so the pure aggregator can mark
            # the exact chain conflicted instead of silently choosing one.
            if not self._append_observation(
                (inbound_fact.source_event_id, inbound_fact.fact_id),
                scope, normalized_time, FEEDBACK_EVIDENCE_ACTIVE,
            ):
                return "observation_storage_unavailable"
            pending = self._pending.setdefault(inbound_fact.fact_id, [])
            if (scope, normalized_time) not in pending:
                pending.append((scope, normalized_time))
            self._pending_sources[inbound_fact.fact_id] = inbound_fact.source_event_id
        self.refresh_archives()
        return "pending_archive"

    def observe_archive(self, archive: P2rReplyLinkFactArchiveV1) -> None:
        """Join queued inbound facts to one committed exact archive."""

        if type(archive) is not P2rReplyLinkFactArchiveV1:
            return
        if self._journal_failed:
            return
        for inbound_fact in archive.inbound_reply_facts:
            pending = self._pending.get(inbound_fact.fact_id)
            if not pending:
                continue
            if self._pending_sources.get(inbound_fact.fact_id) != inbound_fact.source_event_id:
                continue
            try:
                reply_link = archive.derive_exact_reply_link(inbound_fact.fact_id)
            except P2r0IntegrityError:
                continue
            evaluation = evaluate_response_length_feedback(
                "这段太长", inbound_fact=inbound_fact, reply_link=reply_link
            )
            candidate = evaluation.candidate
            if candidate is None:
                continue
            for scope, occurred_at in pending:
                source = inbound_fact.source_platform_message_identity
                if (scope.platform_id, scope.account_id, scope.user_id, scope.conversation_id) != (
                    source.platform_id, source.account_id, source.conversation_id, source.conversation_id
                ):
                    continue
                item = ResponseLengthFeedbackAggregationInputV1(
                    candidate=candidate,
                    scope=scope,
                    occurred_at=occurred_at,
                    evidence_state=self._invalidations.get((
                        candidate.source_event_id, candidate.inbound_reply_fact_id,
                        candidate.exact_reply_link_id, candidate.host_output_fact_id,
                    ), FEEDBACK_EVIDENCE_ACTIVE),
                )
                key = (
                    item.feedback_identity,
                    item.scope,
                    item.occurred_at,
                    item.evidence_state,
                )
                self._observations[key] = item

    def refresh_archives(self) -> None:
        """Replay only the existing authoritative archive view into memory."""

        if self._archive_store is None:
            return
        if self._journal_path is not None and not self._journal_failed:
            try:
                self._replay_journal()
            except (OSError, ValueError, TypeError, KeyError):
                self._journal_failed = True
                self._observations.clear()
                logger.error("Feedback observation refresh unavailable; consolidation disabled")
        for archive in self._archive_store.archives:
            self.observe_archive(archive)

    def aggregates(
        self, *, now: datetime | None = None
    ) -> tuple[ResponseLengthFeedbackAggregateV1, ...]:
        """Return the current review-only aggregate using the frozen D02 rule."""

        self.refresh_archives()
        return aggregate_response_length_feedback(self.observations, now=now)

    async def consolidate_eligible(
        self,
        storage: object,
        *,
        now: datetime | None = None,
        scope: object | None = None,
    ) -> tuple[object, ...]:
        """Submit eligible aggregates to the existing ProfileStorage owner.

        This method is deliberately explicit: an administrator invokes the
        existing preference command, the result is still PENDING, and no
        request-time behavior changes until the normal approval operation.
        """

        storage_now = None if now is None else now.timestamp()
        results = []
        aggregates = self.aggregates(now=now)
        if self._journal_failed:
            raise OSError("feedback observation storage unavailable; no consolidation performed")
        for aggregate in aggregates:
            if not aggregate.eligible:
                continue
            if scope is not None and aggregate.scope != scope:
                continue
            results.append(
                await consolidate_response_length_feedback(
                    aggregate,
                    storage,
                    now=storage_now,
                )
            )
        return tuple(results)


async def consolidate_response_length_feedback(
    aggregate: object,
    storage: object,
    *,
    now: float | None = None,
) -> object:
    """Use the existing ProfileStorage as the sole L11 candidate owner."""

    from iris_memory.profile.response_preferences import PreferenceOperationResult

    request = getattr(storage, "request_response_length_preference_from_aggregate", None)
    if not callable(request):
        return PreferenceOperationResult(False, "storage_unavailable")
    try:
        return await request(aggregate, now=now)
    except Exception:  # noqa: BLE001 - consolidation fails closed
        return PreferenceOperationResult(False, "consolidate_failed")


def aggregate_response_length_feedback(
    observations: Iterable[ResponseLengthFeedbackAggregationInputV1],
    *,
    now: datetime | None = None,
) -> tuple[ResponseLengthFeedbackAggregateV1, ...]:
    """Group exact length feedback and evaluate the frozen D02 threshold.

    Replayed candidates use the same four-part exact chain identity and count
    once.  A revoked or conflicted observation dominates an active replay of
    that identity.  Scope is never inferred from a candidate or from nearby
    messages; callers must provide the existing trusted private scope and the
    authoritative time of the feedback event.  Meeting the threshold remains
    review-only and never publishes a preference.
    """

    current_time = _as_utc_datetime(now if now is not None else datetime.now(timezone.utc))
    if current_time is None:
        return ()
    window_start = current_time - timedelta(seconds=RESPONSE_LENGTH_FEEDBACK_WINDOW_SECONDS)

    try:
        inputs = tuple(observations)
    except TypeError:
        return ()
    if any(type(item) is not ResponseLengthFeedbackAggregationInputV1 for item in inputs):
        return ()

    by_scope: dict[
        object,
        dict[tuple[str, str, str, str], tuple[str, datetime]],
    ] = {}
    for item in inputs:
        identities = by_scope.setdefault(item.scope, {})
        previous = identities.get(item.feedback_identity)
        if previous is None:
            identities[item.feedback_identity] = (item.evidence_state, item.occurred_at)
            continue
        previous_state, previous_occurred_at = previous
        if previous_occurred_at != item.occurred_at:
            identities[item.feedback_identity] = (
                FEEDBACK_EVIDENCE_CONFLICTED,
                previous_occurred_at,
            )
            continue
        elif previous_state == FEEDBACK_EVIDENCE_CONFLICTED:
            continue
        if item.evidence_state == FEEDBACK_EVIDENCE_CONFLICTED:
            identities[item.feedback_identity] = (
                FEEDBACK_EVIDENCE_CONFLICTED,
                previous_occurred_at,
            )
        elif item.evidence_state == FEEDBACK_EVIDENCE_REVOKED:
            identities[item.feedback_identity] = (
                FEEDBACK_EVIDENCE_REVOKED,
                previous_occurred_at,
            )

    aggregates: list[ResponseLengthFeedbackAggregateV1] = []
    for scope, identities in by_scope.items():
        active = tuple(
            sorted(
                identity
                for identity, (state, occurred_at) in identities.items()
                if state == FEEDBACK_EVIDENCE_ACTIVE
                and window_start <= occurred_at <= current_time
            )
        )
        invalidated = tuple(
            sorted(
                identity
                for identity, (state, _occurred_at) in identities.items()
                if state != FEEDBACK_EVIDENCE_ACTIVE
            )
        )
        out_of_window = tuple(
            sorted(
                identity
                for identity, (state, occurred_at) in identities.items()
                if state == FEEDBACK_EVIDENCE_ACTIVE
                and not (window_start <= occurred_at <= current_time)
            )
        )
        distinct_source_event_count = len({ref[0] for ref in active})
        distinct_reply_link_count = len({ref[2] for ref in active})
        distinct_host_output_count = len({ref[3] for ref in active})
        eligible = (
            len(active) >= RESPONSE_LENGTH_FEEDBACK_MIN_INDEPENDENT_EVIDENCE
            and distinct_source_event_count >= RESPONSE_LENGTH_FEEDBACK_MIN_INDEPENDENT_EVIDENCE
            and distinct_host_output_count >= RESPONSE_LENGTH_FEEDBACK_MIN_INDEPENDENT_EVIDENCE
        )
        aggregates.append(
            ResponseLengthFeedbackAggregateV1(
                scope=scope,
                parameter="response_length",
                value="SHORT",
                feedback_refs=active,
                invalidated_feedback_refs=invalidated,
                out_of_window_feedback_refs=out_of_window,
                distinct_source_event_count=distinct_source_event_count,
                distinct_reply_link_count=distinct_reply_link_count,
                distinct_host_output_count=distinct_host_output_count,
                eligible=eligible,
                reason=(
                    RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON
                    if eligible
                    else RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON
                ),
            )
        )
    return tuple(
        sorted(
            aggregates,
            key=lambda aggregate: (
                aggregate.scope.platform_id,
                aggregate.scope.account_id,
                aggregate.scope.user_id,
                aggregate.scope.conversation_id,
            ),
        )
    )


__all__ = [
    "FEEDBACK_EVIDENCE_ACTIVE",
    "FEEDBACK_EVIDENCE_CONFLICTED",
    "FEEDBACK_EVIDENCE_REVOKED",
    "RESPONSE_LENGTH_FEEDBACK_AGGREGATION_BLOCKED_REASON",
    "RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON",
    "RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON",
    "RESPONSE_LENGTH_FEEDBACK_KIND",
    "RESPONSE_LENGTH_FEEDBACK_MIN_INDEPENDENT_EVIDENCE",
    "RESPONSE_LENGTH_FEEDBACK_SCHEMA",
    "RESPONSE_LENGTH_FEEDBACK_WINDOW_SECONDS",
    "ResponseLengthFeedbackAggregateV1",
    "ResponseLengthFeedbackAggregationInputV1",
    "ResponseLengthFeedbackCandidateV1",
    "ResponseLengthFeedbackEvaluationV1",
    "aggregate_response_length_feedback",
    "consolidate_response_length_feedback",
    "evaluate_response_length_feedback",
    "is_explicit_length_feedback",
]
