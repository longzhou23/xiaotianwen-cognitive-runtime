"""P2x.1 passive interaction trace regression fixtures."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from iris_memory.cognitive.interaction_trace import (
    CandidateTurnTraceV1,
    ConversationKeyV1,
    InteractionTraceObservatoryProjectionV1,
    PassiveInteractionTraceV1,
    RawEventEnvelopeV1,
    ScopeKind,
    conversation_key_from_event,
)


class _Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _Image:
    def __init__(self, url: str) -> None:
        self.url = url


class _Reply:
    def __init__(self, message_id: str) -> None:
        self.id = message_id


class _Event:
    def __init__(
        self,
        message_id: str,
        *,
        private: bool = True,
        sender_id: str = "user-1",
        group_id: str = "group-1",
        platform_id: str = "napcat-instance-1",
        account_id: str = "bot-1",
        umo: str = "aiocqhttp:private:user-1",
        components: tuple[object, ...] = (),
    ) -> None:
        self.message_obj = SimpleNamespace(message_id=message_id)
        self._private = private
        self._sender_id = sender_id
        self._group_id = group_id
        self._platform_id = platform_id
        self._account_id = account_id
        self.unified_msg_origin = umo
        self._components = components
        self.stop_calls = 0
        self.send_calls = 0

    def is_private_chat(self) -> bool:
        return self._private

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_group_id(self) -> str:
        return self._group_id

    def get_platform_id(self) -> str:
        return self._platform_id

    def get_self_id(self) -> str:
        return self._account_id

    def get_messages(self) -> tuple[object, ...]:
        return self._components


def _receipt(*statuses: str) -> object:
    operations = tuple(
        SimpleNamespace(
            operation_kind=SimpleNamespace(value="MESSAGE"),
            status=SimpleNamespace(value=status),
        )
        for status in statuses
    )
    return SimpleNamespace(schema_version="astrbot.host-send-result.v1", operations=operations)


def _candidate(
    key: ConversationKeyV1,
    observed_order: int,
    umo: str | None,
    *,
    raw_event_count: int = 1,
    logical_host_results: int = 1,
    actual_send_count: int = 1,
) -> CandidateTurnTraceV1:
    events = tuple(
        RawEventEnvelopeV1(
            conversation_key=key,
            legacy_umo=umo,
            source_event_id=f"event-{observed_order}-{index}",
            message_chain=({"type": "Plain"},),
            reply_metadata={"has_reply": False},
            observed_order=observed_order + index,
            received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        for index in range(raw_event_count)
    )
    return CandidateTurnTraceV1(
        turn_id=f"turn-{observed_order}",
        conversation_key=key,
        raw_events=events,
        logical_host_results=logical_host_results,
        actual_send_count=actual_send_count,
    )


def test_conversation_key_uses_explicit_scope_and_preserves_umo() -> None:
    private = _Event("p-1")
    group = _Event("g-1", private=False, umo="aiocqhttp:group:group-1")
    assert conversation_key_from_event(private) == ConversationKeyV1(
        "napcat-instance-1", "bot-1", ScopeKind.PRIVATE, "user-1"
    )
    assert conversation_key_from_event(group) == ConversationKeyV1(
        "napcat-instance-1", "bot-1", ScopeKind.GROUP, "group-1"
    )


def test_two_rapid_private_messages_form_one_candidate_without_event_mutation() -> None:
    tracer = PassiveInteractionTraceV1()
    first_event = _Event("p-1", components=(_Plain("hello"),))
    second_event = _Event("p-2", components=(_Plain("world"),))
    first = tracer.observe_inbound(first_event, now=0.0)
    second = tracer.observe_inbound(second_event, now=2.0)
    assert isinstance(first, CandidateTurnTraceV1)
    assert second is not None
    assert second.turn_id != first.turn_id
    assert len(second.raw_events) == 2
    assert tracer.snapshot(now=2.0).candidate_turns == 1
    assert first_event.stop_calls == second_event.stop_calls == 0
    assert first_event.send_calls == second_event.send_calls == 0


def test_quiet_window_starts_a_new_candidate_and_three_turns_keep_umo() -> None:
    tracer = PassiveInteractionTraceV1()
    for index, now in enumerate((0.0, 1.0, 5.0), 1):
        tracer.observe_inbound(_Event(f"m-{index}"), now=now)
    metrics = tracer.snapshot(now=5.0)
    assert metrics.raw_events == 3
    assert metrics.candidate_turns == 2
    assert metrics.legacy_umo_continuity == 2


def test_group_burst_is_trace_only_and_bounded() -> None:
    tracer = PassiveInteractionTraceV1(max_conversations=1, max_pending_events=2)
    first = tracer.observe_inbound(_Event("g-1", private=False), now=0.0)
    second = tracer.observe_inbound(_Event("g-2", private=False), now=1.0)
    third = tracer.observe_inbound(_Event("g-3", private=False), now=2.0)
    assert first is not None and second is not None and third is not None
    assert len(third.raw_events) == 1  # max_pending_events closes the prior trace
    assert tracer.snapshot(now=2.0).active_candidate_turns == 1


def test_native_reply_and_chain_metadata_are_detached() -> None:
    tracer = PassiveInteractionTraceV1()
    event = _Event(
        "reply-1",
        components=(_Reply("host-1"), _Image("https://example.invalid/image"), _Plain("why")),
    )
    trace = tracer.observe_inbound(event, now=0.0)
    assert trace is not None
    envelope = trace.raw_events[0]
    assert envelope.reply_metadata["has_reply"] is True
    assert envelope.reply_metadata["target_message_id"] == "host-1"
    assert [item["type"] for item in envelope.message_chain] == ["_Reply", "_Image", "_Plain"]
    assert "url" not in envelope.message_chain[1]


def test_host_result_and_h0_receipts_are_observed_without_send_calls() -> None:
    tracer = PassiveInteractionTraceV1()
    event = _Event("multi-1")
    tracer.observe_inbound(event, now=0.0)
    tracer.observe_host_execution(event, now=0.5)
    tracer.observe_logical_response(event, SimpleNamespace(completion_text="a\nb"), now=0.5)
    tracer.observe_send_receipt(
        event,
        _receipt("SEND_SUCCEEDED_WITH_IDENTITY", "SEND_SUCCEEDED_WITH_IDENTITY"),
        now=0.5,
    )
    metrics = tracer.snapshot(now=0.5)
    assert metrics.actual_host_executions == 1
    assert metrics.logical_host_results == 1
    assert metrics.actual_send_count == 2
    assert metrics.h0_receipt_count == 1
    assert event.send_calls == 0


def test_turn_id_is_stable_for_same_canonical_key_and_raw_identities() -> None:
    first = PassiveInteractionTraceV1().observe_inbound(_Event("same"), now=0.0)
    second = PassiveInteractionTraceV1().observe_inbound(_Event("same"), now=0.0)
    assert first is not None and second is not None
    assert first.turn_id == second.turn_id


def test_unsupported_scope_or_identity_fails_closed() -> None:
    class MissingScope:
        pass

    assert conversation_key_from_event(MissingScope()) is None


def test_public_envelope_rejects_nested_mutable_state() -> None:
    key = ConversationKeyV1("platform", "bot", ScopeKind.PRIVATE, "user")
    nested = {"parts": ["one"]}
    envelope = RawEventEnvelopeV1(
        conversation_key=key,
        legacy_umo="umo",
        source_event_id="event",
        message_chain=(nested,),
        reply_metadata={},
        observed_order=1,
        received_at=datetime.now(timezone.utc),
    )
    nested["parts"].append("two")
    assert envelope.message_chain[0]["parts"] == ("one",)
    with pytest.raises(TypeError):
        envelope.message_chain[0]["parts"] = ("changed",)


def test_lazy_sweep_completes_quiet_candidate_without_next_inbound() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(_Event("quiet"), now=0.0)

    metrics = tracer.snapshot(now=30.0)

    assert metrics.active_candidate_turns == 0
    assert len(tracer.completed_candidates(now=30.0)) == 1


def test_candidate_read_surfaces_sweep_quiet_and_ttl_state() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(_Event("read"), now=0.0)

    assert tracer.active_candidates(now=30.0) == ()
    assert len(tracer.completed_candidates(now=30.0)) == 1


def test_late_host_and_receipt_observation_cannot_attach_to_stale_candidate() -> None:
    tracer = PassiveInteractionTraceV1()
    event = _Event("late")
    tracer.observe_inbound(event, now=0.0)

    tracer.observe_host_execution(event, now=30.0)
    tracer.observe_send_receipt(event, _receipt("SEND_SUCCEEDED_WITH_IDENTITY"), now=30.0)

    completed = tracer.completed_candidates(now=30.0)
    assert len(completed) == 1
    assert completed[0].actual_host_executions == 0
    assert completed[0].actual_send_count == 0
    assert tracer.snapshot(now=30.0).active_candidate_turns == 0


def test_last_umo_is_bounded_by_conversation_limit() -> None:
    tracer = PassiveInteractionTraceV1(
        max_conversations=1,
        max_completed_traces=2,
    )
    for index in range(1000):
        tracer.observe_inbound(
            _Event(
                f"bounded-{index}",
                sender_id=f"user-{index}",
                umo=f"umo-{index}",
            ),
            now=index * 0.01,
        )

    assert len(tracer._last_umo) <= 1


def test_ttl_expiration_removes_continuity_state() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(_Event("ttl-1"), now=0.0)
    tracer.observe_inbound(_Event("ttl-2"), now=1.0)
    assert tracer.snapshot(now=1.0).legacy_umo_continuity == 1

    tracer.snapshot(now=61.0)
    tracer.observe_inbound(_Event("ttl-3"), now=62.0)

    assert tracer.snapshot(now=62.0).legacy_umo_continuity == 1
    assert len(tracer._last_umo) == 1


def test_observatory_projection_is_sanitized_and_reads_one_live_tracer() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(
        _Event("private-source-id", components=(_Plain("private raw text"), _Reply("host-id"))),
        now=0.0,
    )
    summary = InteractionTraceObservatoryProjectionV1(tracer).read_summary()
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert summary["available"] is True
    assert summary["schema_version"] == "p2x.interaction-observatory.v1"
    assert "private-source-id" not in encoded
    assert "private raw text" not in encoded
    assert "host-id" not in encoded
    assert "aiocqhttp:private:user-1" not in encoded
    assert len(tracer.completed_candidates(now=30.0)) == 1


def test_observatory_projection_does_not_observe_or_mutate_trace() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(_Event("projection-read"), now=0.0)
    before = tracer.snapshot(now=0.0)
    summary = InteractionTraceObservatoryProjectionV1(tracer).read_summary()
    after = tracer.snapshot(now=0.0)
    assert summary["mode"] == "PASSIVE"
    assert after.raw_events == before.raw_events
    assert after.candidate_turns == before.candidate_turns
    assert after.actual_host_executions == before.actual_host_executions


def test_projection_context_signal_checks_all_pairs_and_exposes_sanitized_turns() -> None:
    key = ConversationKeyV1("platform", "bot", ScopeKind.PRIVATE, "user")
    candidates = (
        _candidate(key, 3, "umo-b"),
        _candidate(key, 2, "umo-a"),
        _candidate(key, 1, "umo-a"),
    )
    projection = InteractionTraceObservatoryProjectionV1(PassiveInteractionTraceV1())

    assert projection._context_signal(candidates) == "YES"
    sample = projection._context_sample(candidates)
    assert sample is not None
    assert sample["conversation_label"] == "C1"
    assert [turn["legacy_umo_same_as_previous"] for turn in sample["turns"]] == [
        "UNKNOWN",
        "YES",
        "NO",
    ]
    assert "umo-a" not in json.dumps(sample)
    assert "umo-b" not in json.dumps(sample)


def test_projection_context_signal_stable_and_missing_umo_are_conservative() -> None:
    key = ConversationKeyV1("platform", "bot", ScopeKind.PRIVATE, "user")
    projection = InteractionTraceObservatoryProjectionV1(PassiveInteractionTraceV1())
    stable = tuple(_candidate(key, index, "stable") for index in (3, 2, 1))
    missing = stable[:2] + (_candidate(key, 1, None),)

    assert projection._context_signal(stable) == "NO"
    assert projection._context_signal(missing) == "INCONCLUSIVE"
    stable_sample = projection._context_sample(stable)
    assert stable_sample is not None
    assert [turn["legacy_umo_same_as_previous"] for turn in stable_sample["turns"]] == [
        "UNKNOWN",
        "YES",
        "YES",
    ]


def test_projection_sampling_keeps_single_debounce_control_and_output_classes() -> None:
    key = ConversationKeyV1("platform", "bot", ScopeKind.PRIVATE, "user")
    projection = InteractionTraceObservatoryProjectionV1(PassiveInteractionTraceV1())
    candidates = (
        _candidate(key, 4, "u4", raw_event_count=1, logical_host_results=1, actual_send_count=1),
        _candidate(key, 3, "u3", raw_event_count=2, logical_host_results=2, actual_send_count=3),
        _candidate(key, 2, "u2", raw_event_count=2, logical_host_results=1, actual_send_count=2),
    )

    debounce = projection._debounce_samples(candidates)
    assert len(debounce) == 3
    assert sum(item["raw_event_count"] == 1 for item in debounce) == 1
    output = projection._output_samples(candidates)
    assert len(output) == 3
    assert output[0]["logical_host_results"] == 1
    assert output[0]["actual_send_count"] == 2
    assert any(
        item["logical_host_results"] == 1 and item["actual_send_count"] == 1
        for item in output
    )
    assert not (
        output[1]["logical_host_results"] == 2
        and output[1]["actual_send_count"] == 3
    )


def test_projection_summary_reports_determinate_traffic_only() -> None:
    tracer = PassiveInteractionTraceV1()
    tracer.observe_inbound(_Event("summary"), now=0.0)
    projection = InteractionTraceObservatoryProjectionV1(tracer)
    summary = projection.read_summary()

    assert summary["signals"]["natural_traffic_sufficient"] is False
    assert "legacy_umo_continuity" in summary["aggregate"]
