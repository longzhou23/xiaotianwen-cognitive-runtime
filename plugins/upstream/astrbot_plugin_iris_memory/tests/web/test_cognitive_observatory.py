"""P1 Cognitive Observatory read-only/API regression tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from quart import Quart

from iris_memory.cognitive.contracts import (
    BehaviorExecutionRecord, BehaviorTrace, DivergenceType, GroundingEnforcement,
    CanonicalEntity, HostResult, IdentityClaim, IdentityClaimStatus, OutputProducer, OutputState,
    ShadowComparison, TraceStage, TriggerDecision,
)
from iris_memory.cognitive.identity import EntityRegistry
from iris_memory.cognitive.episode import Episode, EpisodeEventKind, EpisodeEventRef, EpisodeState
from iris_memory.cognitive.episode_store import InMemoryEpisodeStore
from iris_memory.cognitive.outcome import OutcomeExplicitness, OutcomeKind, OutcomeObservation
from iris_memory.cognitive.review_store import InMemoryReviewStore
from iris_memory.cognitive.review_service import review_episode
from iris_memory.cognitive.review import EvidenceSourceType
from iris_memory.web.routes import observatory as routes
from iris_memory.web.services.observatory_service import P1ObservatoryService


NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def _record(event_id: str = "event:1") -> BehaviorExecutionRecord:
    trace = BehaviorTrace(event_id, TriggerDecision(True, "test", 1), None, None, None, None)
    return BehaviorExecutionRecord(
        trace,
        HostResult(True, True, True, False, OutputState.OUTPUT_READY, OutputProducer.LEGACY_HOST, GroundingEnforcement.NOT_APPLIED),
        ShadowComparison(True, True, None, True, True, DivergenceType.MATCH_REPLY),
        TraceStage.HOST_OUTPUT,
        1,
        NOW,
    )


def _fixture(
    *,
    outcome_kind: OutcomeKind | None = OutcomeKind.EXPLICIT_CORRECTION,
    late: bool = False,
    episode_id: str = "episode:test:1",
    state: EpisodeState = EpisodeState.FINALIZED,
):
    record = _record()
    host_ref = EpisodeEventRef(
        f"HOST_OUTPUT:event:1:{record.trace.trace_id}", EpisodeEventKind.HOST_OUTPUT,
        "event:1", record.trace.trace_id, f"{record.trace.trace_id}:1", NOW,
    )
    episode = Episode(
        episode_id,
        "test",
        state,
        "event:1",
        NOW,
        NOW,
        event_refs=(host_ref,),
        finalized_at=NOW if state is EpisodeState.FINALIZED else None,
    )
    store = InMemoryEpisodeStore(); store.create_episode(episode)
    outcomes = ()
    if outcome_kind:
        outcome = OutcomeObservation("outcome:test:1", episode.episode_id, outcome_kind, NOW + timedelta(minutes=2) if late else NOW, source_event_id="event:new" if late else "event:2", explicitness=OutcomeExplicitness.EXPLICIT)
        store.record_outcome(outcome); outcomes = (outcome,)
    return store, episode, outcomes, {host_ref.ref_id: record}


def _four_turn_fixture(*, state: EpisodeState = EpisodeState.OPEN, include_extra_event: bool = False):
    refs: list[EpisodeEventRef] = []
    records: dict[str, BehaviorExecutionRecord] = {}
    for number in range(1, 5):
        event_id = f"event:{number}"
        record = _record(event_id)
        refs.extend((
            EpisodeEventRef(f"EXPERIENCE:{event_id}", EpisodeEventKind.EXPERIENCE, event_id, observed_at=NOW),
            EpisodeEventRef(f"NO_INTENT:{event_id}:{record.trace.trace_id}", EpisodeEventKind.NO_INTENT, event_id, record.trace.trace_id, observed_at=NOW),
            EpisodeEventRef(f"HOST_OUTPUT:{event_id}:{record.trace.trace_id}", EpisodeEventKind.HOST_OUTPUT, event_id, record.trace.trace_id, f"{record.trace.trace_id}:1", NOW),
            EpisodeEventRef(f"DISPATCH:{event_id}:{record.trace.trace_id}", EpisodeEventKind.DISPATCH, event_id, record.trace.trace_id, f"{record.trace.trace_id}:2", NOW),
        ))
        records[refs[-2].ref_id] = record
    if include_extra_event:
        refs.append(EpisodeEventRef("TOOL_RESULT:event:extra", EpisodeEventKind.TOOL_RESULT, "event:extra", observed_at=NOW))
    episode = Episode(
        "episode:four-turns",
        "private:test",
        state,
        "event:1",
        NOW,
        NOW,
        event_refs=tuple(refs),
        finalized_at=NOW if state is EpisodeState.FINALIZED else None,
    )
    store = InMemoryEpisodeStore(); store.create_episode(episode)
    outcomes = tuple(
        OutcomeObservation(
            f"outcome:four-turns:{number}", episode.episode_id, OutcomeKind.DISPATCH_OBSERVED,
            NOW, source_event_id=f"event:{number}", explicitness=OutcomeExplicitness.STRUCTURAL,
        )
        for number in range(1, 5)
    )
    for outcome in outcomes:
        store.record_outcome(outcome)
    return store, episode, outcomes, records


def test_listing_detail_snapshot_and_late_outcome_are_read_only():
    store, episode, outcomes, records = _fixture(late=True)
    service = P1ObservatoryService(store, execution_records=records)
    before = store.get_episode(episode.episode_id)
    listing = service.list_episodes(state="FINALIZED", query="event:1")
    detail = service.episode_detail(episode.episode_id)
    assert listing["total"] == 1
    assert detail["outcomes"][0]["late_feedback"] is True
    assert detail["attachments"][0]["status"] == "ATTACHED"
    assert detail["snapshot"]["fact_payload_hashed"] is True
    assert detail["snapshot"]["fact_deep_snapshotted"] is True
    assert store.get_episode(episode.episode_id) == before
    json.dumps(detail, ensure_ascii=False)


def test_preview_is_nonpersistent_and_correction_ack_remain_findings_only():
    for kind in (OutcomeKind.EXPLICIT_CORRECTION, OutcomeKind.EXPLICIT_ACKNOWLEDGEMENT):
        store, episode, _outcomes, records = _fixture(outcome_kind=kind)
        production_store = InMemoryReviewStore()
        service = P1ObservatoryService(store, production_store, records)
        preview = service.preview_review(episode.episode_id)
        assert preview["persisted"] is False
        assert preview["evidence_count"] == 0
        assert preview["run"]["status"] == "COMPLETED"
        assert preview["run"]["findings"]
        assert production_store.list_review_runs_for_episode(episode.episode_id) == ()
        assert production_store.list_evidence_for_episode(episode.episode_id) == ()


def test_persisted_review_is_projected_only_when_a_store_is_explicitly_available():
    store, episode, outcomes, records = _fixture()
    review_store = InMemoryReviewStore()
    fact_envelopes = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(episode, outcomes, review_store, fact_envelopes=fact_envelopes)
    service = P1ObservatoryService(store, review_store, records)
    persisted = service.persisted_review(episode.episode_id)
    assert run is not None
    assert persisted["status"] == "AVAILABLE"
    assert persisted["runs"][0]["review_run_id"] == run.review_run_id
    assert persisted["evidence"] == []


def test_persisted_review_explains_run_finding_refs_and_zero_evidence_reason():
    store, episode, outcomes, records = _fixture(outcome_kind=OutcomeKind.EXPLICIT_CORRECTION)
    review_store = InMemoryReviewStore()
    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(episode, outcomes, review_store, fact_envelopes=facts)
    before_runs = review_store.list_review_runs_for_episode(episode.episode_id)
    before_evidence = review_store.list_evidence_for_episode(episode.episode_id)

    persisted = P1ObservatoryService(
        store,
        review_store,
        records,
        runtime_state={"promotion_enabled": True},
    ).persisted_review(episode.episode_id)

    assert run is not None
    assert persisted["result_code"] == "FINDINGS_NOT_PROMOTABLE"
    assert persisted["run_count"] == 1
    assert persisted["finding_count"] == 1
    assert persisted["evidence_count"] == 0
    projected_run = persisted["runs"][0]
    assert projected_run["episode_id"] == episode.episode_id
    assert projected_run["status"] == "COMPLETED"
    assert projected_run["created_at"]
    assert projected_run["no_evidence_reason"]
    projected_finding = projected_run["findings"][0]
    assert projected_finding["claim"]
    assert projected_finding["created_at"]
    assert projected_finding["evidence_refs"]
    assert projected_finding["evidence_refs"][0]["ref_id"]
    assert review_store.list_review_runs_for_episode(episode.episode_id) == before_runs
    assert review_store.list_evidence_for_episode(episode.episode_id) == before_evidence


def test_unattached_typed_execution_is_rejected_and_missing_execution_is_not_fabricated():
    store, episode, _outcomes, records = _fixture()
    wrong = _record("event:other")
    host_ref = episode.event_refs[0]
    rejected = P1ObservatoryService(store, execution_records={host_ref.ref_id: wrong})
    assert rejected.episode_detail(episode.episode_id)["attachments"][0]["status"] == "REJECTED"
    unavailable = P1ObservatoryService(store)
    preview = unavailable.preview_review(episode.episode_id)
    assert preview["unavailable_reason"] == "execution_records_not_wired"
    assert preview["evidence_count"] == 0


def test_empty_and_unavailable_sources_do_not_raise():
    empty = P1ObservatoryService(InMemoryEpisodeStore())
    assert empty.summary()["episodes"] == 0
    assert empty.list_episodes()["episodes"] == []
    unavailable = P1ObservatoryService()
    assert unavailable.summary()["available"] is False
    assert unavailable.list_episodes()["available"] is False


def test_human_view_counts_actual_structural_refs_without_event_division():
    store, episode, _outcomes, records = _four_turn_fixture(include_extra_event=True)
    service = P1ObservatoryService(store, execution_records=records)
    detail = service.episode_detail(episode.episode_id)
    human = detail["human"]
    assert len(episode.event_refs) == 17
    assert human["interaction_turns"] == 4
    assert human["host_outputs"] == 4
    assert human["dispatches"] == 4
    assert human["outcomes"] == 4
    assert human["no_intent"] == 4
    assert human["host_fact_integrity"] == "COMPLETE"
    assert human["verified_host_facts"] == 4
    assert service.list_episodes()["episodes"][0]["human"]["interaction_turns"] == 4


def test_human_view_reports_unavailable_records_and_p1_review_gate_conservatively():
    store, episode, _outcomes, _records = _four_turn_fixture(state=EpisodeState.INTERRUPTED)
    human = P1ObservatoryService(store).episode_detail(episode.episode_id)["human"]
    assert human["lifecycle_label"] == "运行中断"
    assert human["host_fact_integrity"] == "PARTIAL"
    assert human["verified_host_facts"] == 0
    assert human["unavailable_host_facts"] == 4
    assert human["review_storage"] == "NOT_WIRED"
    assert human["promotion_enabled"] is False


def test_human_view_keeps_engineering_raw_details_available_to_the_frontend():
    store, episode, _outcomes, records = _four_turn_fixture()
    detail = P1ObservatoryService(store, execution_records=records).episode_detail(episode.episode_id)
    assert detail["raw"]["episode"]["event_refs"]
    assert detail["snapshot"]["hash"]
    view = Path(__file__).parents[2] / "iris_memory" / "web" / "frontend" / "src" / "views" / "CognitiveObservatoryView.vue"
    source = view.read_text(encoding="utf-8")
    assert "viewMode" in source
    assert "工程视图" in source
    assert "Raw JSON · read-only" in source


def test_route_service_provider_reuses_current_runtime_episode_store(monkeypatch):
    store, episode, _outcomes, _records = _fixture(state=EpisodeState.OPEN)
    review_store = InMemoryReviewStore()
    runtime = SimpleNamespace(
        episode_observer=SimpleNamespace(store=store),
        observatory_review_store=review_store,
        execution_observatory=None,
    )
    monkeypatch.setattr(routes, "get_cognitive_runtime", lambda: runtime)

    list_service = routes.get_observatory_service()
    detail_service = routes.get_observatory_service()

    assert list_service._episode_store is store
    assert detail_service._episode_store is store
    assert list_service._review_store is review_store
    assert detail_service._review_store is review_store
    assert list_service.list_episodes()["episodes"][0]["episode_id"] == episode.episode_id
    assert detail_service.episode_detail(episode.episode_id)["episode"]["episode_id"] == episode.episode_id


def test_demo_cases_are_memory_only_and_cover_rejected_unattached_fact():
    service = P1ObservatoryService()
    correction = service.demo_case("correction")
    acknowledgement = service.demo_case("acknowledgement")
    late = service.demo_case("late-feedback")
    silence = service.demo_case("silence")
    unattached = service.demo_case("unattached")
    assert correction["demo"] is True and correction["preview"]["evidence_count"] == 0
    assert acknowledgement["preview"]["run"]["findings"]
    assert late["detail"]["outcomes"][0]["late_feedback"] is True
    assert silence["preview"]["run"] is None
    assert unattached["detail"]["rejection"]["status"] == "REJECTED"


def test_summary_projects_authoritative_review_store_and_effective_runtime_state():
    store, episode, outcomes, records = _fixture()
    review_store = InMemoryReviewStore()
    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(episode, outcomes, review_store, fact_envelopes=facts)
    class P2bStore:
        available = True

        @staticmethod
        def all_candidates():
            return (SimpleNamespace(status=SimpleNamespace(value="PENDING")),)

    service = P1ObservatoryService(
        store,
        review_store,
        records,
        p2r0_store=SimpleNamespace(archives=()),
        runtime_state={
            "lifecycle_enabled": True,
            "review_enabled": True,
            "promotion_enabled": True,
            "promotion_rules": ("EXPLICIT_CORRECTION_OF_EXACT_HOST_OUTPUT_V1",),
            "semantic_evaluator": "EXPLICIT_CORRECTION_V1",
            "p2b_enabled": False,
            "host_cas_available": True,
            "feedback_available": True,
            "feedback_observations": 3,
            "identity_available": True,
            "identity_entities": 2,
            "identity_claims": 4,
            "projection_counts": {"events": 9, "relationship": 2, "behavioral_prior": 5, "affect": 1},
            "last_projection_at": 1788796800.0,
            "p2b_shadow_store": P2bStore(),
            "p2b_shadow_last_evaluation_at": 1788796800.0,
        },
    )

    summary = service.summary()
    assert run is not None
    assert summary["phase"] == "P2l.1"
    assert summary["review_runs"] == 1
    assert summary["review_findings"] == len(run.findings)
    assert summary["review_evidence"] == 0
    assert summary["review_run_count_source"] == "runtime_owned_persisted_review_store"
    assert summary["finding_count_source"] == "runtime_owned_persisted_review_store"
    assert summary["evidence_count_source"] == "runtime_owned_persisted_review_store"
    assert summary["review"]["status"] == "ENABLED"
    assert summary["promotion"]["enabled"] is True
    assert summary["promotion"]["rules"] == ["EXPLICIT_CORRECTION_OF_EXACT_HOST_OUTPUT_V1"]
    assert summary["semantic_evaluator"] == "EXPLICIT_CORRECTION_V1"
    adaptive = summary["adaptive_runtime"]
    assert adaptive["host_cas"] == {"available": True, "scope": "response_style_preference:v1"}
    assert adaptive["feedback_replay"]["observations"] == 3
    assert adaptive["identity"]["entities"] == 2
    assert adaptive["situation"]["events"] == 9
    assert adaptive["relationship"]["observed"] == 2
    assert adaptive["behavioral_prior"]["permission_effect"] == "none"
    assert adaptive["affect"] == {"available": True, "observed": 1, "owner": "astrbot_plugin_affection", "ttl_seconds": 60}
    assert adaptive["history_write"]["status"] == "LOCKED"
    assert summary["p2b_shadow"]["enabled"] is True
    assert summary["p2b_shadow"]["mode"] == "SHADOW"
    assert summary["p2b_shadow"]["auto_approve"] is False
    assert summary["p2b_shadow"]["auto_publish"] is False
    assert summary["p2b_shadow"]["candidate_status_counts"]["PENDING"] == 1
    assert summary["p2b_shadow"]["allowed_parameters"] == ["response_length"]


def test_summary_reports_unavailable_review_store_without_false_zero_counts():
    store, _episode, _outcomes, _records = _fixture()

    class BrokenReviewStore:
        def list_review_runs_for_episode(self, _episode_id):
            raise OSError("journal unavailable")

        def list_evidence_for_episode(self, _episode_id):
            raise OSError("journal unavailable")

    summary = P1ObservatoryService(
        store,
        BrokenReviewStore(),
        runtime_state={"review_enabled": True, "promotion_enabled": True},
    ).summary()
    assert summary["review_store"] == "UNAVAILABLE"
    assert summary["review_runs"] == "Unavailable"
    assert summary["review_findings"] == "Unavailable"
    assert summary["review_evidence"] == "Unavailable"
    assert summary["review_run_count_source"] == "Unavailable"
    assert summary["review"]["status"] == "UNAVAILABLE"


def test_episode_detail_projects_review_status_and_runtime_archive_presence():
    store, episode, outcomes, records = _fixture()
    review_store = InMemoryReviewStore()
    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(episode, outcomes, review_store, fact_envelopes=facts)
    service = P1ObservatoryService(
        store,
        review_store,
        records,
        p2r0_store=SimpleNamespace(archives=()),
        runtime_state={"review_enabled": True, "promotion_enabled": True},
    )
    detail = service.episode_detail(episode.episode_id)
    assert run is not None
    assert detail["review"]["status"] == "AVAILABLE"
    assert len(detail["review"]["runs"]) == 1
    assert detail["review"]["runs"][0]["review_run_id"] == run.review_run_id
    assert detail["archive"] == {"available": True, "status": "AVAILABLE", "count": 0, "archives": []}
    assert detail["human"]["review_storage"] == "AVAILABLE"


def test_promotion_enabled_with_zero_evidence_is_not_projected_as_disabled():
    store, _episode, _outcomes, _records = _fixture(outcome_kind=None)
    summary = P1ObservatoryService(
        store,
        InMemoryReviewStore(),
        runtime_state={
            "review_enabled": True,
            "promotion_enabled": True,
            "promotion_rules": ("EXPLICIT_CORRECTION_OF_EXACT_HOST_OUTPUT_V1",),
        },
    ).summary()
    assert summary["review_evidence"] == 0
    assert summary["promotion"]["enabled"] is True
    assert summary["promotion"]["status"] == "ENABLED"
    assert summary["promotion"]["rule_count"] == 1


def test_observatory_never_claims_p2b_behavioral_learning_enabled():
    store, _episode, _outcomes, _records = _fixture(outcome_kind=None)
    summary = P1ObservatoryService(store, runtime_state={"p2b_enabled": False}).summary()
    assert summary["behavioral_learning"] == {
        "enabled": False,
        "status": "DISABLED",
        "label": "P2b 尚未启用",
    }


def test_runtime_detail_redacts_identity_affect_and_preference_payloads() -> None:
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity(
            "person:qq:private-user-9988",
            aliases=("私人别名",),
            platform_ids={"QQ": "9988"},
        ),
        source="admin:secret-admin",
    )
    registry.add_claim(
        IdentityClaim(
            mention="私人别名",
            candidate_entity="person:qq:private-user-9988",
            evidence=("SECRET EVIDENCE TEXT",),
            confidence=0.75,
            source="admin:secret-admin",
            status=IdentityClaimStatus.CONFIRMED,
        )
    )
    preference = SimpleNamespace(
        parameter="response_length",
        value="SECRET PREFERENCE VALUE",
        candidate_id="secret-candidate-id",
        scope={"user_id": "private-user-9988", "conversation_id": "private-chat"},
        status="APPROVED",
        requested_at=900.0,
        approved_at=901.0,
        expires_at=1200.0,
        revoked_at=None,
        suspended_reason=None,
        source=SimpleNamespace(source_kind="EXPLICIT_CONTROLLED_REQUEST", source_event_id="secret-event"),
    )
    detail = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={
            "identity_available": True,
            "identity_registry": registry,
            "response_preference_records": [preference],
            "affect_snapshot": {
                "schema": "iris.affect-view.v1",
                "owner": "astrbot_plugin_affection",
                "user_id": "private-user-9988",
                "scope": "private-chat",
                "generated_at": 900.0,
                "expires_at": 1100.0,
                "affection": 62.5,
                "towards_user": "warm",
                "prompt": "SECRET PROMPT",
            },
            "projection_counts": {"relationship": 1, "behavioral_prior": 1, "affect": 1},
        },
    ).runtime_detail(now=1000.0)
    encoded = json.dumps(detail, ensure_ascii=False)

    assert detail["schema_version"] == "iris.observatory-runtime-detail.v1"
    identity = detail["details"]["identity"]
    assert identity["status"] == "AVAILABLE"
    assert identity["entities"][1]["alias_count"] == 1
    assert any(claim["source_kind"] == "admin" for claim in identity["claims"])
    assert all(claim["candidate_ref"].startswith(("SELF", "entity#")) for claim in identity["claims"])
    affect = detail["details"]["affect"]
    assert affect["status"] == "AVAILABLE"
    assert affect["metrics"] == [{"name": "affection", "value": 62.5, "maximum": 100.0}]
    assert affect["labels"] == {"towards_user": "warm"}
    preference_detail = detail["details"]["response_preferences"]
    assert preference_detail["status"] == "AVAILABLE"
    assert preference_detail["records"][0]["parameter"] == "response_length"
    for secret in ("private-user-9988", "9988", "私人别名", "SECRET EVIDENCE TEXT", "SECRET PREFERENCE VALUE", "secret-candidate-id", "SECRET PROMPT"):
        assert secret not in encoded


def test_admin_record_views_project_contract_fields_paging_content_and_redaction() -> None:
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity(
            "person:qq:admin-record-user",
            aliases=("管理员可见别名",),
            platform_ids={"qq": "admin-record-uid"},
        ),
        source="admin:operator",
    )
    registry.add_claim(
        IdentityClaim(
            mention="审计别名",
            candidate_entity="person:qq:admin-record-user",
            evidence=("evidence:alias-review-1",),
            confidence=0.75,
            source="admin:operator",
            status=IdentityClaimStatus.CONFIRMED,
        )
    )
    store = InMemoryEpisodeStore()
    episodes = []
    for number in range(2):
        content = ("persisted audit content " + ("x" * 300)) if number == 0 else "short content"
        episode = Episode(
            f"episode:admin:{number}",
            "private:admin-audit",
            EpisodeState.FINALIZED,
            f"event:admin:{number}",
            NOW,
            NOW + timedelta(minutes=number),
            event_refs=(EpisodeEventRef(
                f"EXPERIENCE:event:admin:{number}",
                EpisodeEventKind.EXPERIENCE,
                f"event:admin:{number}",
                observed_at=NOW,
            ),),
            topic_hint=content,
            finalized_at=NOW,
            provenance=("episode_shadow_observer",),
        )
        store.create_episode(episode)
        outcome = OutcomeObservation(
            f"outcome:admin:{number}",
            episode.episode_id,
            OutcomeKind.ANSWER_OBSERVED,
            NOW,
            source_event_id=f"event:admin:{number}",
            source_ref_id=f"EXPERIENCE:event:admin:{number}",
            explicitness=OutcomeExplicitness.STRUCTURAL,
            confidence=0.5,
            evidence=("answer_observed",),
            provenance=("outcome_collector",),
        )
        store.record_outcome(outcome)
        episodes.append(episode)

    service = P1ObservatoryService(
        store,
        runtime_state={"identity_available": True, "identity_registry": registry},
    )
    identity_page = service.admin_identity(limit=1, offset=1)
    assert identity_page["schema"] == "iris.observatory-admin-identity.v1"
    assert identity_page["pagination"] == {
        "limit": 1,
        "offset": 1,
        "entities_total": 2,
        "claims_total": 3,
    }
    assert len(identity_page["entities"]) == 1
    entity = identity_page["entities"][0]
    assert entity["id"] == "person:qq:admin-record-user"
    assert entity["type"] == "person"
    assert entity["platform_ids"] == {"qq": "admin-record-uid"}
    assert entity["aliases"] == ["管理员可见别名"]
    assert entity["self"] is False
    claim_page = service.admin_identity(limit=1, offset=2)
    claim = claim_page["claims"][0]
    assert set(claim) >= {"claim_id", "mention", "candidate_entity", "evidence", "source", "status", "confidence", "created_at"}

    listing = service.admin_episodes(limit=1, offset=1)
    assert listing["schema"] == "iris.observatory-admin-episode.v1"
    assert listing["total"] == 2
    assert len(listing["episodes"]) == 1
    assert "topic_hint" not in listing["episodes"][0]
    assert listing["episodes"][0]["content_snapshot"]["truncated"] is True
    assert len(listing["episodes"][0]["content_snapshot"]["text"]) == 240

    before = store.get_episode(episodes[0].episode_id), store.get_outcomes()
    detail = service.admin_episode_detail(episodes[0].episode_id)
    assert detail["read_only"] is True
    assert detail["episode"]["scope_id"] == "private:admin-audit"
    assert "topic_hint" not in detail["episode"]
    assert detail["episode"]["event_refs"][0]["source_event_id"] == "event:admin:0"
    assert detail["outcomes"][0]["evidence"] == ["answer_observed"]
    assert detail["episode"]["content_snapshot"]["truncated"] is True
    assert detail["snapshot"]["fact_deep_snapshotted"] is True
    assert (store.get_episode(episodes[0].episode_id), store.get_outcomes()) == before

    outcomes = service.admin_outcomes(limit=1, offset=1)
    assert outcomes["schema"] == "iris.observatory-admin-outcome.v1"
    assert outcomes["total"] == 2
    assert len(outcomes["outcomes"]) == 1
    assert outcomes["outcomes"][0]["target_episode_id"].startswith("episode:admin:")


def test_admin_identity_human_projection_prefers_alias_and_explains_claim_state() -> None:
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity(
            "person:qq:human-user",
            aliases=("小林",),
            platform_ids={"qq": "human-uid"},
        ),
        source="system:platform_binding",
    )
    registry.add_claim(
        IdentityClaim(
            mention="小林",
            candidate_entity="agent:xiaotianwen",
            evidence=("evidence:conflict",),
            confidence=0.5,
            source="system:ambiguous",
            status=IdentityClaimStatus.POSSIBLE,
        )
    )
    registry.add_claim(
        IdentityClaim(
            mention="旧名字",
            candidate_entity="person:qq:human-user",
            evidence=("evidence:revoked",),
            confidence=1.0,
            source="admin:operator",
            status=IdentityClaimStatus.REVOKED,
        )
    )
    projection = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={"identity_available": True, "identity_registry": registry},
    ).admin_identity()

    human = projection["human"]
    user = next(item for item in human["entities"] if item["name"] == "小林")
    self_view = next(item for item in human["entities"] if item["name"] == "小天文")
    assert user["summary"].startswith("这是一个用户身份；已绑定 1 个平台账号；")
    assert "确认别名" in user["summary"]
    assert user["platforms"][0]["platform"] == "QQ"
    assert user["aliases"][0]["name"] == "小林"
    assert self_view["name"] == "小天文"
    assert any("当前冲突" in claim["summary"] for claim in human["claims"])
    assert any("当前已撤销" in claim["summary"] for claim in human["claims"])


def test_admin_episode_human_projection_has_four_stage_timeline_and_no_body_fallback() -> None:
    store, episode, _outcomes, _records = _four_turn_fixture(state=EpisodeState.FINALIZED)
    detail = P1ObservatoryService(store).admin_episode_detail(episode.episode_id)
    human = detail["human"]
    labels = [item["label"] for item in human["timeline"]]
    assert {"用户发来消息", "小天文形成判断", "生成回复", "成功发送", "互动封存"} <= set(labels)
    assert human["interaction_turns"] == 4
    assert human["actual_replies"] == 4
    assert human["successful_sends"] == 4
    assert human["result_count"] == 4
    assert human["content"]["explanation"] == "系统只保存了结构记录，没有可读正文。"
    assert all("source_event_id" not in item for item in human["timeline"])


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (OutcomeKind.EXPLICIT_CORRECTION, "用户明确纠正了此前的回复"),
        (OutcomeKind.EXPLICIT_ACKNOWLEDGEMENT, "用户明确确认或回应了此前的回复"),
        (OutcomeKind.FOLLOWUP_QUESTION, "用户继续提出了问题"),
        (OutcomeKind.DELIVERY_FAILED, "系统观察到回复发送失败"),
    ],
)
def test_admin_outcome_human_projection_maps_kinds_and_closed_impact_rules(kind, expected) -> None:
    store, episode, _outcomes, _records = _fixture(outcome_kind=kind)
    outcome = P1ObservatoryService(store).admin_outcomes()["outcomes"][0]["human"]
    assert outcome["what_happened"] == expected
    assert outcome["target_interaction"] == "未命名互动"
    assert outcome["direct_expression"] == "是，用户直接表达"
    assert "不会自动" in outcome["current_impact"]
    assert "人格" in outcome["current_impact"] or "未来行为" in outcome["current_impact"]


def test_admin_human_review_explains_no_run_no_finding_and_promotion_gate() -> None:
    store, episode, outcomes, records = _fixture(outcome_kind=None)
    review_store = InMemoryReviewStore()
    service = P1ObservatoryService(store, review_store, records)
    no_run = service.admin_episode_detail(episode.episode_id)["human"]["review"]
    assert no_run["completion"].startswith("尚未完成复盘")
    assert "没有可报告" in no_run["what_was_found"]
    assert "不会自动修改长期记忆或行为" in no_run["long_term_impact"]

    class EmptyEngine:
        def generate_findings(self, _episode, _outcomes, *, review_run_id):
            return ()

    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(
        episode,
        outcomes,
        review_store,
        fact_envelopes=facts,
        deterministic_engine=EmptyEngine(),
    )
    assert run is not None
    no_findings = service.admin_episode_detail(episode.episode_id)["human"]["review"]
    assert no_findings["completion"] == "复盘已完成。"
    assert "没有发现需要记录" in no_findings["what_was_found"]

    with_findings_store = InMemoryReviewStore()
    correction_store, correction_episode, correction_outcomes, correction_records = _fixture()
    correction_facts = {
        (EvidenceSourceType.HOST_RESULT, ref_id): record
        for ref_id, record in correction_records.items()
    }
    run = review_episode(
        correction_episode,
        correction_outcomes,
        with_findings_store,
        fact_envelopes=correction_facts,
    )
    assert run is not None
    gated = P1ObservatoryService(
        correction_store,
        with_findings_store,
        correction_records,
        runtime_state={"promotion_enabled": False},
    ).admin_episode_detail(correction_episode.episode_id)["human"]["review"]
    assert "复盘记录了" in gated["what_was_found"]
    assert "没有生成 Evidence" in gated["evidence_explanation"]
    assert "不会自动修改" in gated["long_term_impact"]


def test_admin_human_projection_unknown_enum_or_missing_field_fails_closed() -> None:
    unknown = SimpleNamespace(
        kind=SimpleNamespace(value="FUTURE_KIND"),
        explicitness=SimpleNamespace(value="FUTURE_EXPLICITNESS"),
        evidence=(),
        target_episode_id="episode:unknown",
    )
    human = P1ObservatoryService._outcome_human(unknown)
    assert human["what_happened"] == "未知类型，查看工程详情"
    assert human["direct_expression"] == "未知是否直接表达，查看工程详情"
    assert human["known"] is False
    assert "不会据此推断奖励" in human["current_impact"]
    missing = P1ObservatoryService._event_human(SimpleNamespace())
    assert missing["label"] == "未知事件，查看工程详情"
    assert missing["known"] is False


def test_admin_record_views_redact_sensitive_keys_and_values_fail_closed() -> None:
    pem_header = "-----BEGIN RSA PRIVATE KEY-----"
    bearer = "Bearer abcdefghijklmnop123456"
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature12345678"
    openai_key = "sk-proj-abcdefghijklmnop1234567890"
    cookie = "Cookie: sessionid=abcdefghijklmnop123456"
    long_alias = "long-alias-" + ("y" * 600)
    registry = EntityRegistry()
    registry.register_entity(
        CanonicalEntity(
            "person:qq:safe-admin",
            aliases=("token-user-1", pem_header, bearer, jwt, openai_key, cookie, long_alias),
        ),
        source="admin:operator",
    )
    registry.add_claim(
        IdentityClaim(
            mention="safe mention",
            candidate_entity="person:qq:safe-admin",
            evidence=("SECRET EVIDENCE TEXT", pem_header, bearer, jwt, openai_key, cookie),
            confidence=1.0,
            source=bearer,
        )
    )
    store = InMemoryEpisodeStore()
    episode = Episode(
        "episode:admin:redaction",
        "private:admin-audit",
        EpisodeState.FINALIZED,
        "event:redaction",
        NOW,
        NOW,
        topic_hint=f"ordinary persisted content {openai_key}",
        finalized_at=NOW,
    )
    store.create_episode(episode)
    store.record_outcome(OutcomeObservation(
        "outcome:admin:redaction",
        episode.episode_id,
        OutcomeKind.ANSWER_OBSERVED,
        NOW,
        evidence=("token=SECRET_VALUE",),
    ))
    service = P1ObservatoryService(
        store,
        runtime_state={"identity_available": True, "identity_registry": registry},
    )
    encoded = json.dumps(
        {
            "identity": service.admin_identity(),
            "episodes": service.admin_episodes(),
            "episode": service.admin_episode_detail(episode.episode_id),
            "outcomes": service.admin_outcomes(),
        },
        ensure_ascii=False,
    )
    assert "SECRET EVIDENCE TEXT" not in encoded
    for secret in (pem_header, bearer, jwt, openai_key, cookie):
        assert secret not in encoded
    assert "SECRET_VALUE" not in encoded
    assert "[REDACTED]" in encoded
    assert "token-user-1" in encoded
    assert "topic_hint" not in json.dumps(service.admin_episodes(), ensure_ascii=False)
    assert "...[TRUNCATED]" in encoded
    safe_entity = next(
        entity for entity in service.admin_identity()["entities"]
        if entity["id"] == "person:qq:safe-admin"
    )
    assert len(safe_entity["aliases"][-1]) <= 512


def test_runtime_detail_distinguishes_empty_expired_and_unavailable_sources() -> None:
    empty = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={"identity_available": True, "identity_entities": 0, "identity_claims": 0},
    ).runtime_detail(now=1000.0)
    assert empty["details"]["identity"]["status"] == "SUMMARY_ONLY"
    assert empty["details"]["response_preferences"]["status"] == "UNAVAILABLE"
    assert empty["details"]["affect"]["status"] == "UNAVAILABLE"

    expired = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={
            "affect_snapshot": {
                "schema": "iris.affect-view.v1",
                "owner": "astrbot_plugin_affection",
                "generated_at": 100.0,
                "expires_at": 200.0,
                "affection": 50.0,
            }
        },
    ).runtime_detail(now=1000.0)
    assert expired["details"]["affect"]["status"] == "EXPIRED"
    assert expired["details"]["affect"]["reason"] == "affect_snapshot_ttl_elapsed"

    corrupted = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={
            "affect_snapshot": {
                "schema": "iris.affect-view.v1",
                "owner": "astrbot_plugin_affection",
                "generated_at": 900.0,
                "expires_at": 1100.0,
                "affection": "not-a-number",
            }
        },
    ).runtime_detail(now=1000.0)
    assert corrupted["details"]["affect"]["status"] == "CORRUPTED"
    assert corrupted["details"]["affect"]["metrics"] == []

    malformed_preference = P1ObservatoryService(
        InMemoryEpisodeStore(),
        runtime_state={"response_preference_records": [{"parameter": "unapproved_private_parameter"}]},
    ).runtime_detail(now=1000.0)
    assert malformed_preference["details"]["response_preferences"]["status"] == "CORRUPTED"

    class BrokenEpisodeStore(InMemoryEpisodeStore):
        def all_episodes(self):
            raise RuntimeError("fictional read failure")

    broken_store = P1ObservatoryService(BrokenEpisodeStore()).runtime_detail(now=1000.0)
    assert broken_store["details"]["episodes"]["status"] == "UNAVAILABLE"
    assert broken_store["details"]["outcomes"]["status"] == "UNAVAILABLE"


def test_insufficient_review_run_is_visible_as_completed_review_artifact():
    store, episode, outcomes, records = _fixture(outcome_kind=None)
    review_store = InMemoryReviewStore()
    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}

    class EmptyEngine:
        def generate_findings(self, _episode, _outcomes, *, review_run_id):
            return ()

    run = review_episode(
        episode,
        outcomes,
        review_store,
        fact_envelopes=facts,
        deterministic_engine=EmptyEngine(),
    )
    summary = P1ObservatoryService(
        store,
        review_store,
        runtime_state={"review_enabled": True},
    ).summary()
    assert run is not None
    assert run.status.value == "INSUFFICIENT_EVIDENCE"
    assert summary["review_runs"] == 1
    assert summary["review_status_counts"] == {"INSUFFICIENT_EVIDENCE": 1}
    assert summary["review_evidence"] == 0


def test_persisted_review_distinguishes_no_run_from_run_without_findings():
    store, episode, outcomes, records = _fixture(outcome_kind=None)
    review_store = InMemoryReviewStore()
    service = P1ObservatoryService(store, review_store)
    assert service.persisted_review(episode.episode_id)["result_code"] == "NO_RUN"

    class EmptyEngine:
        def generate_findings(self, _episode, _outcomes, *, review_run_id):
            return ()

    facts = {(EvidenceSourceType.HOST_RESULT, ref_id): record for ref_id, record in records.items()}
    run = review_episode(
        episode,
        outcomes,
        review_store,
        fact_envelopes=facts,
        deterministic_engine=EmptyEngine(),
    )
    projected = service.persisted_review(episode.episode_id)
    assert run is not None
    assert projected["result_code"] == "NO_FINDINGS"
    assert projected["run_count"] == 1
    assert projected["finding_count"] == 0
    assert projected["evidence_count"] == 0


def test_frontend_projects_runtime_status_and_does_not_show_stale_p1_gate_copy():
    view = Path(__file__).parents[2] / "iris_memory" / "web" / "frontend" / "src" / "views" / "CognitiveObservatoryView.vue"
    source = view.read_text(encoding="utf-8")
    assert "phaseTitle" in source
    assert "Production Cognitive Runtime" in source
    assert "受控长期适应 · ENABLED" in source
    assert "p2bHeaderLabel" in source
    assert "P1 Experience &amp; Review Foundation" not in source
    assert "P1 FOUNDATION · ACCEPTED" not in source
    assert "长期适应运行态" in source
    assert "Host 原子写" in source
    assert "BehavioralPrior" in source
    assert "L28 历史数据写入仍锁定" in source
    assert "Unavailable" in source
    assert "Finding 已记录，但当前不可 promotion" in source
    assert "引用：" in source
    assert "no_evidence_reason" in source


def test_frontend_admin_records_default_to_human_view_and_keep_engineering_toggle():
    view = Path(__file__).parents[2] / "iris_memory" / "web" / "frontend" / "src" / "views" / "CognitiveObservatoryView.vue"
    source = view.read_text(encoding="utf-8")
    assert "adminViewMode" in source
    assert "易懂视图（默认）" in source
    assert "工程详情" in source
    assert "发生了什么" in source
    assert "系统保存了什么" in source
    assert "当前影响" in source
    assert "系统只保存了结构记录，没有可读正文。" in source
    assert "source_event_id" in source


def test_frontend_exposes_p2b_shadow_contract_without_sensitive_fields():
    view = Path(__file__).parents[2] / "iris_memory" / "web" / "frontend" / "src" / "views" / "CognitiveObservatoryView.vue"
    source = view.read_text(encoding="utf-8")
    panel_start = source.index('class="panel pa-4 mb-3 p2b-shadow-panel"')
    panel_end = source.index('<v-card v-if="!summary?.available"', panel_start)
    panel = source[panel_start:panel_end]

    assert "summary.p2b_shadow" in panel
    assert "模式 ·" in panel and "p2bShadow?.mode" in panel
    assert "auto_approve" in panel
    assert "auto_publish" in panel
    assert "candidate_status_counts" in source
    assert "last_evaluation_at" in source
    assert "allowed_parameters" in source
    assert "permission_effect" in source
    assert "当前为 SHADOW" in panel
    assert "未经人工批准不会进入回复偏好" in panel
    assert "candidate_id" not in panel
    assert "candidateId" not in panel
    assert "p2bShadow?.user" not in panel
    assert "p2bShadow?.scope" not in panel
    assert "p2bShadow?.message" not in panel


class _Context:
    def __init__(self): self.routes = []
    def register_web_api(self, path, handler, methods, desc): self.routes.append((path, handler, methods))


@pytest.mark.asyncio
async def test_routes_return_json_and_error_statuses(monkeypatch):
    store, episode, _outcomes, records = _fixture()
    service = P1ObservatoryService(store, execution_records=records)
    monkeypatch.setattr(routes, "get_observatory_service", lambda: service)
    context = _Context(); routes.register_observatory_routes(context)
    app = Quart(__name__)
    for path, handler, methods in context.routes:
        app.add_url_rule(path, endpoint=path, view_func=handler, methods=methods)
    client = app.test_client()
    assert (await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/summary")).get_json())["success"] is True
    runtime_detail = await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/runtime-detail")).get_json()
    assert runtime_detail["success"] is True
    assert runtime_detail["detail"]["schema_version"] == "iris.observatory-runtime-detail.v1"
    admin_identity = await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/admin/identity?limit=1")).get_json()
    assert admin_identity["success"] is True
    assert admin_identity["schema"] == "iris.observatory-admin-identity.v1"
    admin_episodes = await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/admin/episodes?limit=1")).get_json()
    assert admin_episodes["success"] is True
    assert admin_episodes["schema"] == "iris.observatory-admin-episode.v1"
    admin_outcomes = await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/admin/outcomes?limit=1")).get_json()
    assert admin_outcomes["success"] is True
    assert admin_outcomes["schema"] == "iris.observatory-admin-outcome.v1"
    admin_detail = await (await client.get(f"/astrbot_plugin_iris_memory/cognitive-observatory/admin/episodes/{episode.episode_id}")).get_json()
    assert admin_detail["success"] is True
    assert admin_detail["read_only"] is True
    assert (await (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/episodes?state=BAD")).get_json())["success"] is False
    assert (await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/episodes/missing")).status_code == 404
    preview = await (await client.post(f"/astrbot_plugin_iris_memory/cognitive-observatory/episodes/{episode.episode_id}/preview")).get_json()
    assert preview["success"] is True and preview["evidence_count"] == 0


@pytest.mark.asyncio
async def test_listed_open_episode_id_round_trips_through_encoded_route(monkeypatch):
    episode_id = "episode:private:2986500364:runtime:136336110833632:标记 100%"
    store, episode, _outcomes, records = _fixture(
        episode_id=episode_id,
        state=EpisodeState.OPEN,
    )
    service = P1ObservatoryService(store, execution_records=records)
    episode_before = store.get_episode(episode_id)
    outcomes_before = store.get_outcomes(episode_id)
    monkeypatch.setattr(routes, "get_observatory_service", lambda: service)
    context = _Context()
    routes.register_observatory_routes(context)
    app = Quart(__name__)
    for path, handler, methods in context.routes:
        app.add_url_rule(path, endpoint=path, view_func=handler, methods=methods)
    client = app.test_client()

    listing = await (
        await client.get("/astrbot_plugin_iris_memory/cognitive-observatory/episodes")
    ).get_json()
    listed_id = listing["episodes"][0]["episode_id"]
    assert listed_id == episode_id

    encoded_id = quote(listed_id, safe="")
    response = await client.get(
        f"/astrbot_plugin_iris_memory/cognitive-observatory/episodes/{encoded_id}"
    )
    detail = await response.get_json()
    assert response.status_code == 200
    assert detail["episode"]["episode_id"] == listed_id
    assert detail["episode"]["state"] == "OPEN"
    assert detail["outcomes"][0]["target_episode_id"] == listed_id
    assert detail["review"]["runs"] == []

    preview_response = await client.post(
        f"/astrbot_plugin_iris_memory/cognitive-observatory/episodes/{encoded_id}/preview"
    )
    preview = await preview_response.get_json()
    assert preview_response.status_code == 200
    assert preview["eligibility"]["decision"] == "DEFER"
    assert preview["run"] is None
    assert preview["evidence_count"] == 0
    assert store.get_episode(episode_id) == episode_before
    assert store.get_outcomes(episode_id) == outcomes_before


def test_summary_projects_sanitized_interaction_trace_reader() -> None:
    from iris_memory.cognitive.interaction_trace import (
        InteractionTraceObservatoryProjectionV1,
        PassiveInteractionTraceV1,
    )

    store, _episode, _outcomes, _records = _fixture(outcome_kind=None)
    tracer = PassiveInteractionTraceV1()
    reader = InteractionTraceObservatoryProjectionV1(tracer)
    summary = P1ObservatoryService(
        store,
        interaction_trace_reader=reader,
    ).summary()
    assert summary["interaction_trace"]["available"] is True
    assert summary["interaction_trace"]["schema_version"] == "p2x.interaction-observatory.v1"


def test_summary_reports_unbound_or_failed_interaction_trace_reader() -> None:
    store, _episode, _outcomes, _records = _fixture(outcome_kind=None)
    unbound = P1ObservatoryService(store).summary()
    assert unbound["interaction_trace"] == {
        "schema_version": "p2x.interaction-observatory.v1",
        "available": False,
        "reason": "interaction_trace_not_bound",
    }

    class BrokenReader:
        def read_summary(self):
            raise RuntimeError("must not leak")

    failed = P1ObservatoryService(store, interaction_trace_reader=BrokenReader()).summary()
    assert failed["interaction_trace"] == {
        "schema_version": "p2x.interaction-observatory.v1",
        "available": False,
        "reason": "interaction_trace_read_failed",
    }
