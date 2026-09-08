"""L06 exact-link response-length feedback tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from iris_memory.cognitive.reply_link_authority import (
    FACT_CAPTURE_BINDING_SCHEMA,
    TX_PREFIX,
    FactCaptureAuthorityBindingV1,
    HostOutputMessageIdentityFactV1,
    InboundReplyReferenceFactV1,
    P2rReplyLinkFactArchiveV1,
    PlatformMessageIdentityV1,
)
from iris_memory.cognitive.response_preference_feedback import (
    FEEDBACK_EVIDENCE_ACTIVE,
    FEEDBACK_EVIDENCE_CONFLICTED,
    FEEDBACK_EVIDENCE_REVOKED,
    RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON,
    RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON,
    ResponseLengthFeedbackAggregationInputV1,
    ResponseLengthFeedbackCandidateV1,
    ResponseLengthFeedbackReviewObserverV1,
    aggregate_response_length_feedback,
    consolidate_response_length_feedback,
    evaluate_response_length_feedback,
    is_explicit_length_feedback,
)
from iris_memory.profile.response_preferences import ResponsePreferenceScope


def _exact_chain():
    target = PlatformMessageIdentityV1("napcat-instance-1", "bot-1", "user-1", "host-1")
    inbound_identity = PlatformMessageIdentityV1(
        "napcat-instance-1", "bot-1", "user-1", "feedback-1"
    )
    host = HostOutputMessageIdentityFactV1.create(
        platform_message_identity=target,
        operation_index=0,
        host_send_result_schema_version="astrbot.host-send-result.v1",
        platform_send_receipt_schema_version="astrbot.platform-send-receipt.v1",
        source_event_id="event:host-1",
        trace_id="trace:host-1",
        host_output_event_ref_id="HOST_OUTPUT:event:host-1",
    )
    inbound = InboundReplyReferenceFactV1.create(
        source_event_id="event:feedback-1",
        source_platform_message_identity=inbound_identity,
        reply_target_platform_message_identity=target,
    )
    binding = FactCaptureAuthorityBindingV1(
        schema_version=FACT_CAPTURE_BINDING_SCHEMA,
        fact_id=host.fact_id,
        transaction_id=TX_PREFIX + "a" * 64,
    )
    inbound_binding = FactCaptureAuthorityBindingV1(
        schema_version=FACT_CAPTURE_BINDING_SCHEMA,
        fact_id=inbound.fact_id,
        transaction_id=TX_PREFIX + "b" * 64,
    )
    archive = P2rReplyLinkFactArchiveV1.create(
        review_run_id="review:feedback-1",
        episode_id="episode:feedback-1",
        input_snapshot_hash="sha256:" + "0" * 64,
        p2_run_snapshot_logical_commit_hash="sha256:" + "1" * 64,
        p2r0_encoding_profile_hash="sha256:" + "2" * 64,
        host_output_facts=(host,),
        inbound_reply_facts=(inbound,),
        fact_capture_authority=(binding, inbound_binding),
    )
    return inbound, archive.derive_exact_reply_link(inbound.fact_id, host), archive


def test_l06_exact_phrase_requires_exact_reply_link_and_keeps_other_corrections_unknown():
    inbound, link, _archive = _exact_chain()
    assert is_explicit_length_feedback("这段太长") is True
    exact = evaluate_response_length_feedback(
        "这段太长", inbound_fact=inbound, reply_link=link
    )
    assert exact.reason == "exact_reply_link"
    assert exact.candidate is not None
    assert exact.candidate.source_event_id == "event:feedback-1"
    assert exact.candidate.host_output_fact_id == link.host_output_fact_id

    factual = evaluate_response_length_feedback(
        "你说错了", inbound_fact=inbound, reply_link=link
    )
    assert factual.candidate is None
    assert factual.reason == "not_explicit_length_feedback"


def test_l06_missing_or_non_exact_link_stops_without_nearest_output_fallback():
    inbound, _link, archive = _exact_chain()
    missing = evaluate_response_length_feedback(
        "这段太长", inbound_fact=inbound, reply_link=None
    )
    assert missing.candidate is None
    assert missing.reason == "missing_exact_reply_link"

    empty_archive = P2rReplyLinkFactArchiveV1.create(
        review_run_id=archive.review_run_id,
        episode_id=archive.episode_id,
        input_snapshot_hash=archive.input_snapshot_hash,
        p2_run_snapshot_logical_commit_hash=archive.p2_run_snapshot_logical_commit_hash,
        p2r0_encoding_profile_hash=archive.p2r0_encoding_profile_hash,
        inbound_reply_facts=archive.inbound_reply_facts,
        fact_capture_authority=(FactCaptureAuthorityBindingV1(
            schema_version=FACT_CAPTURE_BINDING_SCHEMA,
            fact_id=inbound.fact_id,
            transaction_id=TX_PREFIX + "c" * 64,
        ),),
    )
    unavailable_link = empty_archive.derive_exact_reply_link(inbound.fact_id)
    unavailable = evaluate_response_length_feedback(
        "这段太长", inbound_fact=inbound, reply_link=unavailable_link
    )
    assert unavailable.candidate is None
    assert unavailable.reason == "reply_link_not_exact"


@pytest.mark.asyncio
async def test_l11_observer_consolidator_submits_only_eligible_aggregate_to_existing_owner():
    scope = ResponsePreferenceScope("napcat", "bot-1", "user-1", "user-1")
    observer = ResponseLengthFeedbackReviewObserverV1()
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    for index in range(2):
        candidate = ResponseLengthFeedbackCandidateV1(
            schema_version="response-length-feedback.v1",
            kind="RESPONSE_LENGTH_TOO_LONG",
            source_event_id=f"feedback-{index}",
            inbound_reply_fact_id=f"inbound-{index}",
            exact_reply_link_id=f"link-{index}",
            host_output_fact_id=f"host-{index}",
        )
        item = ResponseLengthFeedbackAggregationInputV1(
            candidate=candidate,
            scope=scope,
            occurred_at=now - timedelta(minutes=index),
        )
        observer._observations[(item.feedback_identity, scope, item.occurred_at, item.evidence_state)] = item

    class _Owner:
        def __init__(self):
            self.calls = []

        async def request_response_length_preference_from_aggregate(self, aggregate, *, now=None):
            self.calls.append((aggregate, now))
            return "pending-result"

    owner = _Owner()
    results = await observer.consolidate_eligible(owner, now=now)
    assert results == ("pending-result",)
    assert len(owner.calls) == 1
    assert owner.calls[0][0].eligible is True
    assert owner.calls[0][1] == now.timestamp()

    unavailable = await consolidate_response_length_feedback(object(), object())
    assert getattr(unavailable, "code", None) == "storage_unavailable"


class _PrivateFeedbackEvent:
    message_str = "这段太长"

    def __init__(self, timestamp):
        self.message_obj = type("Message", (), {"raw_message": {"time": timestamp}})()

    def get_platform_id(self):
        return "napcat-instance-1"

    def get_self_id(self):
        return "bot-1"

    def get_sender_id(self):
        return "user-1"

    def get_group_id(self):
        return ""

    def is_private_chat(self):
        return True


def test_l09_runtime_observer_uses_private_event_time_and_waits_for_archive():
    inbound, _link, archive = _exact_chain()
    observer = ResponseLengthFeedbackReviewObserverV1()
    event = _PrivateFeedbackEvent(BASE_TIME.timestamp())

    assert observer.observe_inbound_event(event, inbound) == "pending_archive"
    assert observer.observations == ()

    observer.observe_archive(archive)
    aggregates = observer.aggregates(now=BASE_TIME)
    assert len(aggregates) == 1
    assert aggregates[0].distinct_feedback_count == 1
    assert aggregates[0].reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON


def test_l09_runtime_observer_rejects_adapter_fallback_time():
    inbound, _link, _archive = _exact_chain()
    observer = ResponseLengthFeedbackReviewObserverV1()
    event = _PrivateFeedbackEvent(None)
    event.message_obj.raw_message = {}

    assert observer.observe_inbound_event(event, inbound) == "missing_authoritative_event_time"
    assert observer.observations == ()


BASE_TIME = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _aggregate_input(
    scope,
    source_id,
    inbound_id,
    link_id,
    host_id,
    state=FEEDBACK_EVIDENCE_ACTIVE,
    occurred_at=None,
):
    candidate = ResponseLengthFeedbackCandidateV1(
        schema_version="response-length-feedback.v1",
        kind="RESPONSE_LENGTH_TOO_LONG",
        source_event_id=source_id,
        inbound_reply_fact_id=inbound_id,
        exact_reply_link_id=link_id,
        host_output_fact_id=host_id,
    )
    return ResponseLengthFeedbackAggregationInputV1(
        candidate,
        scope,
        occurred_at or BASE_TIME - timedelta(days=1),
        state,
    )


def test_d02_threshold_counts_independent_replays_once_and_keeps_scopes_separate():
    scope_a = ResponsePreferenceScope("napcat-1", "bot-1", "user-a", "user-a")
    scope_b = ResponsePreferenceScope("napcat-1", "bot-1", "user-b", "user-b")
    replay = _aggregate_input(
        scope_a,
        "event-1",
        "inbound-1",
        "link-1",
        "host-1",
        occurred_at=BASE_TIME - timedelta(days=1),
    )
    observations = [replay] * 10 + [
        _aggregate_input(
            scope_a,
            "event-2",
            "inbound-2",
            "link-2",
            "host-2",
            occurred_at=BASE_TIME - timedelta(days=2),
        ),
        _aggregate_input(scope_b, "event-1", "inbound-1", "link-1", "host-1"),
    ]

    aggregates = aggregate_response_length_feedback(observations, now=BASE_TIME)

    assert len(aggregates) == 2
    by_scope = {aggregate.scope.user_id: aggregate for aggregate in aggregates}
    assert by_scope["user-a"].distinct_feedback_count == 2
    assert by_scope["user-a"].distinct_source_event_count == 2
    assert by_scope["user-a"].distinct_host_output_count == 2
    assert by_scope["user-a"].eligible is True
    assert by_scope["user-a"].reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON
    assert by_scope["user-b"].distinct_feedback_count == 1
    assert by_scope["user-b"].eligible is False
    assert by_scope["user-b"].reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON
    assert all(
        aggregate.parameter == "response_length" and aggregate.value == "SHORT"
        for aggregate in aggregates
    )


def test_l09_revoked_or_conflicted_feedback_is_removed_on_re_evaluation():
    scope = ResponsePreferenceScope("napcat-1", "bot-1", "user-a", "user-a")
    revoked = _aggregate_input(
        scope, "event-1", "inbound-1", "link-1", "host-1", FEEDBACK_EVIDENCE_REVOKED
    )
    conflict = _aggregate_input(
        scope, "event-2", "inbound-2", "link-2", "host-2", FEEDBACK_EVIDENCE_CONFLICTED
    )
    active = _aggregate_input(scope, "event-3", "inbound-3", "link-3", "host-3")

    aggregate = aggregate_response_length_feedback(
        [
            _aggregate_input(scope, "event-1", "inbound-1", "link-1", "host-1"),
            revoked,
            _aggregate_input(scope, "event-2", "inbound-2", "link-2", "host-2"),
            conflict,
            active,
        ],
        now=BASE_TIME,
    )[0]

    assert aggregate.distinct_feedback_count == 1
    assert aggregate.feedback_refs == (("event-3", "inbound-3", "link-3", "host-3"),)
    assert len(aggregate.invalidated_feedback_refs) == 2
    assert aggregate.eligible is False
    assert aggregate.reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON


def test_d02_requires_two_distinct_sources_and_host_outputs_inside_30_days():
    scope = ResponsePreferenceScope("napcat-1", "bot-1", "user-a", "user-a")
    same_source = [
        _aggregate_input(scope, "event-1", "inbound-1", "link-1", "host-1"),
        _aggregate_input(scope, "event-1", "inbound-2", "link-2", "host-2"),
    ]
    same_host = [
        _aggregate_input(scope, "event-3", "inbound-3", "link-3", "host-3"),
        _aggregate_input(scope, "event-4", "inbound-4", "link-4", "host-3"),
    ]
    old = _aggregate_input(
        scope,
        "event-old",
        "inbound-old",
        "link-old",
        "host-old",
        occurred_at=BASE_TIME - timedelta(days=31),
    )
    future = _aggregate_input(
        scope,
        "event-future",
        "inbound-future",
        "link-future",
        "host-future",
        occurred_at=BASE_TIME + timedelta(seconds=1),
    )

    for observations in (same_source, same_host, [old, future]):
        aggregate = aggregate_response_length_feedback(observations, now=BASE_TIME)[0]
        assert aggregate.eligible is False
        assert aggregate.reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON

    aggregate = aggregate_response_length_feedback([old, future], now=BASE_TIME)[0]
    assert len(aggregate.out_of_window_feedback_refs) == 2
    assert aggregate.feedback_refs == ()


def test_d02_rejects_missing_or_naive_event_time_and_conflicting_replay_time():
    scope = ResponsePreferenceScope("napcat-1", "bot-1", "user-a", "user-a")
    with pytest.raises(ValueError, match="aware authoritative event time"):
        _aggregate_input(
            scope,
            "event-naive",
            "inbound-naive",
            "link-naive",
            "host-naive",
            occurred_at=(BASE_TIME - timedelta(days=1)).replace(tzinfo=None),
        )

    first = _aggregate_input(
        scope,
        "event-1",
        "inbound-1",
        "link-1",
        "host-1",
        occurred_at=BASE_TIME - timedelta(days=1),
    )
    inconsistent_replay = _aggregate_input(
        scope,
        "event-1",
        "inbound-1",
        "link-1",
        "host-1",
        occurred_at=BASE_TIME - timedelta(days=2),
    )
    aggregate = aggregate_response_length_feedback(
        [first, inconsistent_replay], now=BASE_TIME
    )[0]
    assert aggregate.feedback_refs == ()
    assert aggregate.invalidated_feedback_refs == (first.feedback_identity,)
    assert aggregate.reason == RESPONSE_LENGTH_FEEDBACK_AGGREGATION_INSUFFICIENT_REASON


def test_l09_malformed_or_untrusted_scope_fails_closed_without_an_aggregate():
    scope = ResponsePreferenceScope("napcat-1", "bot-1", "user-a", "user-a")
    valid = _aggregate_input(scope, "event-1", "inbound-1", "link-1", "host-1")

    assert aggregate_response_length_feedback([valid, object()]) == ()
    with pytest.raises(ValueError, match="existing private response scope"):
        _aggregate_input(object(), "event-1", "inbound-1", "link-1", "host-1")


def test_r04_pending_feedback_survives_restart_without_persisting_text(tmp_path):
    inbound, _link, archive = _exact_chain()
    scope = ResponsePreferenceScope("napcat-instance-1", "bot-1", "user-1", "user-1")
    now = datetime(2026, 9, 8, tzinfo=timezone.utc)
    path = tmp_path / "observations.jsonl"
    first = ResponseLengthFeedbackReviewObserverV1(path)
    assert first.observe_inbound(text="这段太长", scope=scope, occurred_at=now,
                                 inbound_fact=inbound) == "pending_archive"
    assert first.observations == ()
    saved = path.read_bytes()
    assert "这段太长".encode() not in saved
    second = ResponseLengthFeedbackReviewObserverV1(path)
    second.observe_archive(archive)
    assert len(second.observations) == 1
    assert second.observations[0].scope == scope
    assert second.observations[0].occurred_at == now
    second.observe_inbound(text="这段太长", scope=scope, occurred_at=now, inbound_fact=inbound)
    assert path.read_bytes() == saved


def test_r04_damaged_journal_never_releases_partial_observations(tmp_path):
    inbound, _link, archive = _exact_chain()
    scope = ResponsePreferenceScope("napcat-instance-1", "bot-1", "user-1", "user-1")
    now = datetime(2026, 9, 8, tzinfo=timezone.utc)
    path = tmp_path / "observations.jsonl"
    observer = ResponseLengthFeedbackReviewObserverV1(path)
    observer.observe_inbound(text="这段太长", scope=scope, occurred_at=now, inbound_fact=inbound)
    with path.open("ab") as handle:
        handle.write(b'{"incomplete":')
    damaged = path.read_bytes()
    restarted = ResponseLengthFeedbackReviewObserverV1(path)
    restarted.observe_archive(archive)
    assert restarted.observations == ()
    assert restarted.observe_inbound(text="这段太长", scope=scope, occurred_at=now,
                                     inbound_fact=inbound) == "observation_storage_unavailable"
    assert path.read_bytes() == damaged


def test_r04_busy_journal_fails_closed_without_memory_only_success(tmp_path):
    inbound, _link, archive = _exact_chain()
    scope = ResponsePreferenceScope("napcat-instance-1", "bot-1", "user-1", "user-1")
    path = tmp_path / "observations.jsonl"
    observer = ResponseLengthFeedbackReviewObserverV1(path)
    path.with_suffix(".jsonl.lock").mkdir()
    assert observer.observe_inbound(text="这段太长", scope=scope,
                                    occurred_at=datetime.now(timezone.utc),
                                    inbound_fact=inbound) == "observation_storage_unavailable"
    observer.observe_archive(archive)
    assert observer.observations == ()
    assert not path.exists()
