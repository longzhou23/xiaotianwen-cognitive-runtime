"""P2b Shadow Candidate V1 tests with entirely fictional identifiers."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import datetime, timedelta, timezone

import pytest

import iris_memory.cognitive.behavior_candidate as module
from iris_memory.cognitive.behavior_candidate import (
    AppendOnlyBehaviorCandidateStore,
    BehaviorCandidate,
    BehaviorCandidateIntegrityError,
    BehaviorCandidateStateError,
    BehaviorCandidateStorageError,
    BehaviorCandidateValidationError,
    BehaviorParameter,
    CandidateEvidence,
    CandidateStatus,
    PermissionEffect,
    PrivateUIDScope,
    ShadowCandidateEvaluator,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _scope(user: str = "user-a") -> PrivateUIDScope:
    return PrivateUIDScope(
        platform_id="fictional-platform",
        account_id="fictional-bot",
        user_id=user,
        conversation_id=user,
    )


def _evidence(
    prefix: str = "a",
    *,
    scope: PrivateUIDScope | None = None,
    parameter: BehaviorParameter = BehaviorParameter.RESPONSE_LENGTH,
    value: str = "BRIEF",
) -> tuple[CandidateEvidence, CandidateEvidence]:
    bound_scope = scope or _scope()
    return (
        CandidateEvidence(
            f"episode-{prefix}-one",
            f"evidence-{prefix}-one",
            bound_scope,
            parameter,
            value,
        ),
        CandidateEvidence(
            f"episode-{prefix}-two",
            f"evidence-{prefix}-two",
            bound_scope,
            parameter,
            value,
        ),
    )


def _candidate(
    *,
    user: str = "user-a",
    parameter: BehaviorParameter = BehaviorParameter.RESPONSE_LENGTH,
    value: str = "BRIEF",
    expires_at: datetime | None = NOW + timedelta(days=30),
) -> BehaviorCandidate:
    return ShadowCandidateEvaluator().evaluate(
        scope=_scope(user),
        parameter=parameter,
        proposed_value=value,
        evidence=_evidence(
            user, scope=_scope(user), parameter=parameter, value=value
        ),
        now=NOW,
        expires_at=expires_at,
    )


def test_frozen_contracts_and_closed_parameter_allow_list():
    candidate = _candidate()
    assert is_dataclass(candidate)
    assert candidate.permission_effect is PermissionEffect.NONE
    assert candidate.__slots__
    assert {item.value for item in BehaviorParameter} == {
        "response_length",
        "answer_structure",
        "format_density",
        "relationship_familiarity",
        "memory_retrieval_style",
    }
    assert {item.value for item in CandidateStatus} == {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "REVOKED",
        "CONFLICTED",
        "EXPIRED",
    }
    with pytest.raises(FrozenInstanceError):
        candidate.proposed_value = "DETAILED"  # type: ignore[misc]

    with pytest.raises(BehaviorCandidateValidationError, match="allow-list"):
        ShadowCandidateEvaluator().evaluate(
            scope=_scope(),
            parameter="persona_name",
            proposed_value="IRIS",
            evidence=_evidence(),
            now=NOW,
        )


def test_scope_is_private_uid_only_and_evidence_needs_two_episodes():
    with pytest.raises(BehaviorCandidateValidationError):
        PrivateUIDScope("platform", "bot", "user-a", "private:user-a", scope_kind="GROUP")
    assert PrivateUIDScope("platform", "bot", "user-a", "private:user-a").conversation_id == "private:user-a"
    with pytest.raises(BehaviorCandidateValidationError, match="two distinct"):
        ShadowCandidateEvaluator().evaluate(
            scope=_scope(),
            parameter=BehaviorParameter.FORMAT_DENSITY,
            proposed_value="STRUCTURED",
            evidence=(
                CandidateEvidence("episode-one", "evidence-one", _scope(), BehaviorParameter.FORMAT_DENSITY, "STRUCTURED"),
                CandidateEvidence("episode-one", "evidence-two", _scope(), BehaviorParameter.FORMAT_DENSITY, "STRUCTURED"),
            ),
            now=NOW,
        )


def test_shadow_evaluator_only_generates_pending_candidate_without_writing():
    candidate = _candidate(parameter=BehaviorParameter.ANSWER_STRUCTURE, value="CONCLUSION_FIRST")
    assert candidate.status is CandidateStatus.PENDING
    assert candidate.expires_at == NOW + timedelta(days=30)
    assert candidate.parameter is BehaviorParameter.ANSWER_STRUCTURE
    assert candidate.permission_effect.value == "none"
    assert not hasattr(candidate, "message")


def test_shadow_evaluator_generates_conflicted_candidate_from_competing_values():
    scope = _scope()
    evidence = (
        CandidateEvidence(
            "episode-one", "evidence-one", scope,
            BehaviorParameter.RESPONSE_LENGTH, "BRIEF",
        ),
        CandidateEvidence(
            "episode-two", "evidence-two", scope,
            BehaviorParameter.RESPONSE_LENGTH, "DETAILED",
        ),
    )
    candidate = ShadowCandidateEvaluator().evaluate(
        scope=scope,
        parameter=BehaviorParameter.RESPONSE_LENGTH,
        evidence=evidence,
        now=NOW,
    )
    assert candidate.status is CandidateStatus.CONFLICTED
    assert candidate.proposed_value == "UNRESOLVED"
    assert candidate.permission_effect is PermissionEffect.NONE


@pytest.mark.parametrize("mismatch", ["scope", "parameter"])
def test_shadow_evaluator_rejects_cross_scope_or_parameter_evidence(mismatch):
    scope = _scope()
    evidence = list(_evidence(scope=scope))
    if mismatch == "scope":
        evidence[1] = CandidateEvidence(
            "episode-a-two", "evidence-a-two", _scope("user-b"),
            BehaviorParameter.RESPONSE_LENGTH, "BRIEF",
        )
    else:
        evidence[1] = CandidateEvidence(
            "episode-a-two", "evidence-a-two", scope,
            BehaviorParameter.ANSWER_STRUCTURE, "CONCLUSION_FIRST",
        )
    with pytest.raises(BehaviorCandidateValidationError, match="crosses"):
        ShadowCandidateEvaluator().evaluate(
            scope=scope,
            parameter=BehaviorParameter.RESPONSE_LENGTH,
            evidence=evidence,
            now=NOW,
        )


def test_append_replay_and_idempotent_create(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    candidate = _candidate()
    store = AppendOnlyBehaviorCandidateStore(path)
    assert store.append_candidate(candidate) == candidate
    assert store.append_candidate(candidate) == candidate
    assert len(path.read_bytes().splitlines()) == 1

    restarted = AppendOnlyBehaviorCandidateStore(path)
    assert restarted.get(candidate.candidate_id) == candidate
    assert restarted.all_candidates() == (candidate,)


def test_approve_changes_only_candidate_journal_and_never_publishes(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    candidate = _candidate(parameter=BehaviorParameter.RELATIONSHIP_FAMILIARITY, value="FAMILIAR")
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(candidate)
    approved = store.approve(candidate.candidate_id, actor="admin:fictional", now=NOW)

    assert approved.status is CandidateStatus.APPROVED
    assert approved.permission_effect is PermissionEffect.NONE
    text = path.read_text(encoding="utf-8")
    assert "ProfileStorage" not in text
    assert "profile" not in text.lower()
    assert not (tmp_path / "profile-storage.json").exists()

    restarted = AppendOnlyBehaviorCandidateStore(path)
    assert restarted.get(candidate.candidate_id).status is CandidateStatus.APPROVED  # type: ignore[union-attr]


def test_cross_scope_candidates_are_kept_separate(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    first = _candidate(user="user-a")
    second = _candidate(user="user-b")
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(first)
    store.append_candidate(second)

    assert store.get(first.candidate_id).scope == _scope("user-a")  # type: ignore[union-attr]
    assert store.get(second.candidate_id).scope == _scope("user-b")  # type: ignore[union-attr]
    assert {item.scope.user_id for item in store.all_candidates()} == {"user-a", "user-b"}


def test_reject_revoke_conflict_and_invalid_transition(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    rejected = _candidate(user="user-reject")
    revoked = _candidate(user="user-revoke")
    conflict_scope = _scope("user-conflict")
    conflicted = ShadowCandidateEvaluator().evaluate(
        scope=conflict_scope,
        parameter=BehaviorParameter.RESPONSE_LENGTH,
        evidence=(
            CandidateEvidence("episode-conflict-one", "evidence-conflict-one", conflict_scope, BehaviorParameter.RESPONSE_LENGTH, "BRIEF"),
            CandidateEvidence("episode-conflict-two", "evidence-conflict-two", conflict_scope, BehaviorParameter.RESPONSE_LENGTH, "DETAILED"),
        ),
        now=NOW,
    )
    store = AppendOnlyBehaviorCandidateStore(path)
    for item in (rejected, revoked, conflicted):
        store.append_candidate(item)

    assert store.reject(rejected.candidate_id, actor="admin:fictional").status is CandidateStatus.REJECTED
    assert store.approve(revoked.candidate_id, actor="admin:fictional").status is CandidateStatus.APPROVED
    assert store.revoke(revoked.candidate_id, actor="admin:fictional").status is CandidateStatus.REVOKED
    assert store.get(conflicted.candidate_id).status is CandidateStatus.CONFLICTED  # type: ignore[union-attr]
    assert store.reject(conflicted.candidate_id, actor="admin:fictional").status is CandidateStatus.REJECTED
    with pytest.raises(BehaviorCandidateStateError):
        store.approve(rejected.candidate_id, actor="admin:fictional")


def test_state_transitions_are_idempotent_and_pending_cannot_be_revoked(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    pending = _candidate()
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(pending)
    with pytest.raises(BehaviorCandidateStateError):
        store.revoke(pending.candidate_id, actor="admin:fictional")
    approved = store.approve(pending.candidate_id, actor="admin:fictional")
    size = path.stat().st_size
    assert store.approve(pending.candidate_id, actor="admin:fictional") == approved
    assert path.stat().st_size == size
    revoked = store.revoke(pending.candidate_id, actor="admin:fictional")
    size = path.stat().st_size
    assert store.revoke(pending.candidate_id, actor="admin:fictional") == revoked
    assert path.stat().st_size == size


def test_expiration_is_durable_and_blocks_later_approval(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    candidate = _candidate(expires_at=NOW + timedelta(hours=1))
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(candidate)

    expired = store.expire_due(now=NOW + timedelta(hours=2))
    assert expired[0].status is CandidateStatus.EXPIRED
    with pytest.raises(BehaviorCandidateStateError):
        store.approve(candidate.candidate_id, actor="admin:fictional", now=NOW + timedelta(hours=2))
    assert AppendOnlyBehaviorCandidateStore(path).get(candidate.candidate_id).status is CandidateStatus.EXPIRED  # type: ignore[union-attr]


def test_checksum_and_hash_chain_tampering_fails_closed(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(_candidate())
    raw = path.read_text(encoding="utf-8")
    tampered = raw.replace('"proposed_value":"BRIEF"', '"proposed_value":"DETAILED"')
    path.write_text(tampered, encoding="utf-8", newline="\n")
    with pytest.raises(BehaviorCandidateIntegrityError):
        AppendOnlyBehaviorCandidateStore(path)


def test_truncated_tail_fails_closed_instead_of_replaying_partial_state(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    store = AppendOnlyBehaviorCandidateStore(path)
    store.append_candidate(_candidate())
    with path.open("ab") as handle:
        handle.write(b'{"schema_version":1')
    with pytest.raises(BehaviorCandidateIntegrityError):
        AppendOnlyBehaviorCandidateStore(path)


def test_file_lock_unavailable_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    store = AppendOnlyBehaviorCandidateStore(path)

    def unavailable(_path):
        raise BehaviorCandidateStorageError("simulated lock failure")

    monkeypatch.setattr(module, "_exclusive_file_lock", unavailable)
    with pytest.raises(BehaviorCandidateStorageError, match="lock failure"):
        store.all_candidates()


def test_journal_contains_only_contract_fields_and_no_message_body(tmp_path):
    path = tmp_path / "behavior-candidates.jsonl"
    candidate = _candidate(parameter=BehaviorParameter.MEMORY_RETRIEVAL_STYLE, value="DEFAULT")
    AppendOnlyBehaviorCandidateStore(path).append_candidate(candidate)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(record["payload"]) == {
        "schema_version",
        "candidate_id",
        "scope",
        "parameter",
        "proposed_value",
        "evidence",
        "created_at",
        "expires_at",
        "status",
        "permission_effect",
    }
    assert "message" not in json.dumps(record, ensure_ascii=False).lower()
    assert "text" not in json.dumps(record, ensure_ascii=False).lower()


def test_candidate_payload_rejects_extra_message_field():
    candidate = _candidate()
    payload = candidate.to_payload()
    payload["message"] = "fictional message body must never be stored"
    with pytest.raises(BehaviorCandidateIntegrityError):
        BehaviorCandidate.from_payload(payload)
