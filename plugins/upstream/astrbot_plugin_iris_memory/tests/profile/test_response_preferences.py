"""T10-T15 bounded response-expression preference regression tests."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from iris_memory.cognitive.behavior_candidate import (
    AppendOnlyBehaviorCandidateStore,
    BehaviorParameter,
    CandidateEvidence,
    CandidateStatus,
    PrivateUIDScope,
    ShadowCandidateEvaluator,
)
from iris_memory.commands.base import ParsedArgs
from iris_memory.cognitive.response_preference_feedback import (
    RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON,
    ResponseLengthFeedbackAggregateV1,
)
from iris_memory.commands.executor import execute_command
from iris_memory.commands.registry import get_registry
from iris_memory.commands.response_preference_handler import (
    ResponsePreferenceCommandHandler,
)
from iris_memory.core.llm_request_hook import (
    _collect_tool_preference,
    _inject_to_extra_user_content_parts,
    preprocess_llm_request,
)
from iris_memory.profile.response_preferences import (
    APPROVED,
    CONCLUSION_FIRST,
    FAMILIAR,
    MEMORY_RETRIEVAL_ON,
    MEMORY_RETRIEVAL_PARAMETER,
    PENDING,
    RELATIONSHIP_FAMILIARITY_PARAMETER,
    RESPONSE_EXPANSION_PARAMETER,
    RESPONSE_LENGTH_FEEDBACK_AGGREGATE_SOURCE_KIND,
    RESPONSE_LENGTH_PARAMETER,
    RESPONSE_PREFERENCE_KV_KEY,
    RESPONSE_PREFERENCE_MARKER,
    P2B_EXPLICIT_PUBLISH_SOURCE_KIND,
    REVOKED,
    SHORT,
    SUSPENDED,
    TOOL_PREFERENCE_MARKER,
    event_contains_indirect_content,
    explicit_relationship_familiarity_value,
    explicit_response_preference_value,
    format_response_preferences,
    scope_from_event,
)
from iris_memory.profile.storage import ProfileStorage


class _KV:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.fail_put = False
        self.fail_compare_and_swap = False
        self.put_calls = 0

    async def get_kv_data(self, key: str, default: object) -> object:
        return self.values.get(key, default)

    async def put_kv_data(self, key: str, value: object) -> None:
        self.put_calls += 1
        if self.fail_put:
            raise OSError("fixture write failure")
        self.values[key] = value

    async def compare_and_swap_kv_data(
        self, key: str, expected: object, value: object
    ) -> bool:
        """Replace a value only when the fixture still holds the expected payload."""

        self.put_calls += 1
        if self.fail_put:
            raise OSError("fixture write failure")
        if self.fail_compare_and_swap or self.values.get(key) != expected:
            return False
        self.values[key] = value
        return True

    async def delete_kv_data(self, key: str) -> None:
        self.values.pop(key, None)


class _Event:
    def __init__(
        self,
        message_id: str = "msg-1",
        *,
        private: bool = True,
        sender_id: str = "user-1",
        group_id: str = "",
        platform_id: str = "napcat-instance-1",
        account_id: str = "bot-1",
        message: str = "普通问题",
        messages=None,
    ) -> None:
        self.message_obj = SimpleNamespace(message_id=message_id)
        self._private = private
        self._sender_id = sender_id
        self._group_id = group_id
        self._platform_id = platform_id
        self._account_id = account_id
        self.message_str = message
        self.message_outline = message
        self._messages = list(messages or [])

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

    def get_message_outline(self) -> str:
        return self.message_outline

    def get_messages(self):
        return self._messages


class _Forward:
    pass


class _Reply:
    pass


class _Manager:
    def __init__(self, profile: ProfileStorage) -> None:
        self.profile = profile

    def get_available_component(self, name: str, expected_type: type | None = None):
        if name != "profile":
            return None
        return self.profile

    def get_component(self, name: str, expected_type: type | None = None):
        if name != "profile":
            return None
        return self.profile


FEEDBACK_FIXTURES = (
    {
        "name": "explicit_continuous_private_request",
        "message": "以后这个私聊先给结论",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-explicit-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "response_order",
        "persistence": "scoped_candidate_after_approval",
        "candidate_allowed": True,
        "existing_command_value": "CONCLUSION_FIRST",
        "rejection_reason": None,
    },
    {
        "name": "one_turn_short_request",
        "message": "这次简短点",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-one-turn-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "current_turn_length",
        "persistence": "current_turn_only",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "缺少持续性，只能作为本轮明确要求",
    },
    {
        "name": "unlinked_length_correction",
        "message": "太长了",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-length-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "unknown_output_without_reply_link",
        "persistence": "review_only_until_precise_link",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "没有可信的被评价输出关联，不能推导长期偏好",
    },
    {
        "name": "ordinary_factual_correction",
        "message": "你说错了",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-correction-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "factual_correctness",
        "persistence": "correction_history_only",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "纠正事实不等于回答长度或表达偏好",
    },
    {
        "name": "ambiguous_challenge",
        "message": "不是吧",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-ambiguous-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "unknown",
        "persistence": "unknown_until_clarified",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "表达可能是质疑、确认或玩笑，不能猜测偏好",
    },
    {
        "name": "third_party_preference_claim",
        "message": "他喜欢简短",
        "content_origin": "direct_user_message_about_third_party",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-third-party-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "third_party_preference",
        "persistence": "none",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "目标用户不是当前发言者，不能替第三方创建偏好",
    },
    {
        "name": "explicit_revoke_request",
        "message": "不要记住这个偏好",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-revoke-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "existing_response_preference",
        "persistence": "revoke_only",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "这是撤销意图，不能创建新的长期候选",
    },
    {
        "name": "same_name_user_a",
        "message": "以后这个私聊先给结论",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-a",
        "display_name": "同名用户",
        "event_id": "feedback-same-name-a",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-a",
        "conversation_id": "user-a",
        "expression_target": "response_order",
        "persistence": "scoped_candidate_after_approval",
        "candidate_allowed": True,
        "existing_command_value": "CONCLUSION_FIRST",
        "rejection_reason": None,
    },
    {
        "name": "same_name_user_b",
        "message": "以后这个私聊先给结论",
        "content_origin": "direct_user_message",
        "identity": "trusted_uid:user-b",
        "display_name": "同名用户",
        "event_id": "feedback-same-name-b",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-b",
        "conversation_id": "user-b",
        "expression_target": "response_order",
        "persistence": "scoped_candidate_after_approval",
        "candidate_allowed": True,
        "existing_command_value": "CONCLUSION_FIRST",
        "rejection_reason": None,
    },
    {
        "name": "quoted_or_forwarded_claim",
        "message": "转发：以后这个私聊先给结论",
        "content_origin": "quoted_or_forwarded_third_party_content",
        "identity": "trusted_uid:user-1",
        "display_name": "同名用户",
        "event_id": "feedback-forward-1",
        "platform_id": "napcat-instance-1",
        "account_id": "bot-1",
        "user_id": "user-1",
        "conversation_id": "user-1",
        "expression_target": "unknown_third_party_target",
        "persistence": "none",
        "candidate_allowed": False,
        "existing_command_value": None,
        "rejection_reason": "引用或转发内容不是当前用户的直接持续要求",
    },
)


def _storage() -> tuple[ProfileStorage, _KV]:
    backend = _KV()
    storage = ProfileStorage(backend)
    storage._is_available = True
    return storage, backend


def _p2b_candidate(
    *,
    user_id: str = "p2b-user-a",
    parameter: BehaviorParameter = BehaviorParameter.RESPONSE_LENGTH,
    value: str = SHORT,
    status: CandidateStatus = CandidateStatus.APPROVED,
    expires_at: datetime | None = None,
):
    if expires_at is None:
        expires_at = datetime.fromtimestamp(200.0, timezone.utc)
    scope = PrivateUIDScope(
        platform_id="napcat-instance-1",
        account_id="bot-1",
        user_id=user_id,
        conversation_id=user_id,
    )
    candidate = ShadowCandidateEvaluator().evaluate(
        scope=scope,
        parameter=parameter,
        proposed_value=value,
        evidence=(
            CandidateEvidence(
                "episode-p2b-one",
                "evidence-p2b-one",
                scope,
                parameter,
                value,
            ),
            CandidateEvidence(
                "episode-p2b-two",
                "evidence-p2b-two",
                scope,
                parameter,
                value,
            ),
        ),
        now=datetime.fromtimestamp(100.0, timezone.utc),
        expires_at=expires_at,
    )
    return replace(candidate, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FEEDBACK_FIXTURES, ids=lambda item: item["name"])
async def test_feedback_fixture_preserves_candidate_boundary(fixture):
    """Freeze L03 facts without adding a natural-language classifier."""

    required = {
        "name",
        "message",
        "content_origin",
        "identity",
        "display_name",
        "event_id",
        "platform_id",
        "account_id",
        "user_id",
        "conversation_id",
        "expression_target",
        "persistence",
        "candidate_allowed",
        "existing_command_value",
        "rejection_reason",
    }
    assert set(fixture) == required
    event = _Event(
        message_id=fixture["event_id"],
        sender_id=fixture["user_id"],
        platform_id=fixture["platform_id"],
        account_id=fixture["account_id"],
        message=fixture["message"],
    )
    scope = scope_from_event(event)
    assert scope is not None
    assert scope.user_id == fixture["user_id"]
    assert scope.conversation_id == fixture["conversation_id"]
    assert fixture["identity"] == f"trusted_uid:{scope.user_id}"

    storage, _ = _storage()
    if not fixture["candidate_allowed"]:
        assert fixture["existing_command_value"] is None
        assert fixture["rejection_reason"]
        # L03 deliberately has no natural-language extraction path.  A raw
        # feedback sentence must not be passed to the explicit command API.
        assert await storage.list_response_preferences() == []
        return

    assert fixture["existing_command_value"] == "CONCLUSION_FIRST"
    result = await storage.request_response_preference(
        event, fixture["existing_command_value"], now=10.0
    )
    assert result.success is True
    assert result.code == "pending"
    assert result.record is not None
    assert result.record.source.source_event_id == (
        f"{fixture['platform_id']}:{fixture['event_id']}"
    )
    assert result.record.scope == scope


@pytest.mark.asyncio
async def test_l04_exact_continuous_phrase_is_pending_only_and_idempotent():
    storage, _ = _storage()
    event = _Event(message_id="natural-order", message="以后这里先给结论")

    assert explicit_response_preference_value(event.message_str) == CONCLUSION_FIRST
    first = await storage.request_explicit_response_preference(event, now=10.0)
    repeated = await storage.request_explicit_response_preference(event, now=20.0)

    assert first.success is True and first.code == "pending"
    assert first.record is not None and first.record.status == PENDING
    assert repeated.code == "duplicate"
    assert repeated.record is not None
    assert repeated.record.candidate_id == first.record.candidate_id
    assert await storage.get_response_preference_for_event(event, now=21.0) is None


@pytest.mark.asyncio
async def test_l04_rejects_non_direct_or_unknown_scope_without_candidate():
    storage, _ = _storage()
    forwarded = _Event(
        message_id="natural-forward",
        message="以后这里先给结论",
        messages=[_Forward()],
    )
    quoted = _Event(
        message_id="natural-quote",
        message="以后这个私聊先给结论",
        messages=[_Reply()],
    )

    assert event_contains_indirect_content(forwarded) is True
    assert event_contains_indirect_content(quoted) is True
    assert (await storage.request_explicit_response_preference(forwarded)).code == "indirect_source"
    assert (await storage.request_explicit_response_preference(quoted)).code == "indirect_source"
    assert (
        await storage.request_explicit_response_preference(
            _Event(message_id="natural-group", private=False, group_id="group-1", message="以后这里先给结论")
        )
    ).code == "invalid_scope"
    assert await storage.list_response_preferences() == []


@pytest.mark.asyncio
async def test_l05_order_and_short_are_independent_approved_parameters():
    storage, _ = _storage()
    event = _Event(message_id="two-parameters")
    order = await storage.request_response_preference(
        event,
        CONCLUSION_FIRST,
        parameter=RESPONSE_EXPANSION_PARAMETER,
        now=10.0,
    )
    length = await storage.request_response_preference(
        event,
        SHORT,
        parameter=RESPONSE_LENGTH_PARAMETER,
        now=11.0,
    )
    assert order.record is not None and length.record is not None
    assert order.record.candidate_id != length.record.candidate_id
    assert (
        await storage.approve_response_preference(order.record.candidate_id, "admin", now=20.0)
    ).success is True
    assert (
        await storage.approve_response_preference(length.record.candidate_id, "admin", now=21.0)
    ).success is True

    active = await storage.active_response_preference_records_for_event(event, now=22.0)
    assert active is not None
    assert {(record.parameter, record.value) for record in active} == {
        (RESPONSE_EXPANSION_PARAMETER, CONCLUSION_FIRST),
        (RESPONSE_LENGTH_PARAMETER, SHORT),
    }


def test_same_display_name_does_not_merge_trusted_uid_scopes():
    same_name = [
        item for item in FEEDBACK_FIXTURES if item["name"].startswith("same_name_")
    ]
    scopes = {
        scope_from_event(
            _Event(
                message_id=item["event_id"],
                sender_id=item["user_id"],
                platform_id=item["platform_id"],
                account_id=item["account_id"],
                message=item["message"],
            )
        )
        for item in same_name
    }
    assert len(scopes) == 2
    assert {scope.user_id for scope in scopes if scope is not None} == {
        "user-a",
        "user-b",
    }


@pytest.mark.asyncio
async def test_candidate_is_pending_until_manual_approval_and_survives_restart():
    storage, backend = _storage()
    event = _Event()

    pending = await storage.request_response_preference(
        event, "conclusion_first", now=100.0
    )
    assert pending.success is True
    assert pending.code == "pending"
    assert pending.record is not None
    assert pending.record.status == PENDING
    assert await storage.get_response_preference_for_event(event, now=101.0) is None

    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer-1", now=200.0
    )
    assert approved.success is True
    assert approved.record is not None
    assert approved.record.status == APPROVED
    assert approved.record.expires_at == 200.0 + 7 * 24 * 60 * 60

    restarted = ProfileStorage(backend)
    restarted._is_available = True
    active = await restarted.get_response_preference_for_event(event, now=201.0)
    assert active is not None
    assert active.value == "CONCLUSION_FIRST"


@pytest.mark.asyncio
async def test_l22_familiarity_is_explicit_scoped_approved_revocable_and_expires():
    """L22 has one source-bound fact; it is never a trust or permission fact."""

    storage, backend = _storage()
    event = _Event(
        message_id="familiarity-source",
        message="以后这个私聊可以按熟人相处",
    )
    other_scope = _Event(
        message_id="other-private",
        sender_id="user-2",
        message="普通问题",
    )

    assert explicit_relationship_familiarity_value("不是吧") is None
    assert explicit_relationship_familiarity_value("我们聊了很多次") is None
    assert explicit_relationship_familiarity_value(event.message_str) == FAMILIAR
    pending = await storage.request_explicit_relationship_familiarity(event, now=10.0)
    assert pending.success and pending.code == "pending"
    assert pending.record is not None
    assert pending.record.parameter == RELATIONSHIP_FAMILIARITY_PARAMETER
    assert pending.record.value == FAMILIAR
    assert await storage.get_response_preference_for_event(
        event, parameter=RELATIONSHIP_FAMILIARITY_PARAMETER, now=11.0
    ) is None
    assert await storage.get_response_preference_for_event(
        other_scope, parameter=RELATIONSHIP_FAMILIARITY_PARAMETER, now=11.0
    ) is None

    repeated = await storage.request_explicit_relationship_familiarity(event, now=12.0)
    assert repeated.code == "duplicate"
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.success and approved.record is not None
    assert approved.record.expires_at == 20.0 + 7 * 24 * 60 * 60

    restarted = ProfileStorage(backend)
    restarted._is_available = True
    active = await restarted.get_response_preference_for_event(
        event, parameter=RELATIONSHIP_FAMILIARITY_PARAMETER, now=21.0
    )
    assert active is not None and active.value == FAMILIAR
    rendered = format_response_preferences((active,))
    assert "自然、熟悉的日常语气" in rendered
    assert "不得假定共同经历" in rendered
    assert await restarted.get_response_preference_for_event(
        other_scope, parameter=RELATIONSHIP_FAMILIARITY_PARAMETER, now=21.0
    ) is None

    revoked = await restarted.revoke_response_preferences_for_event(event, now=22.0)
    assert revoked.success and revoked.code == "revoked"
    assert await restarted.get_response_preference_for_event(
        event, parameter=RELATIONSHIP_FAMILIARITY_PARAMETER, now=23.0
    ) is None

    fresh = await restarted.request_explicit_relationship_familiarity(
        _Event(message_id="familiarity-new", message="以后这个私聊可以按熟人相处"),
        now=30.0,
    )
    assert fresh.record is not None
    await restarted.approve_response_preference(fresh.record.candidate_id, "maintainer", now=40.0)
    assert await restarted.get_response_preference_for_event(
        event,
        parameter=RELATIONSHIP_FAMILIARITY_PARAMETER,
        now=40.0 + 7 * 24 * 60 * 60 + 1,
    ) is None


def test_l25_muddy_text_and_self_description_do_not_create_a_persistent_preference():
    """Only fixed continuous requests can enter the candidate path."""

    for message in ("太长了", "不是吧", "我是内向的人", "我今天心情不好"):
        assert explicit_response_preference_value(message) is None
        assert explicit_relationship_familiarity_value(message) is None


@pytest.mark.asyncio
async def test_l29_disabling_profile_storage_stops_new_and_saved_adaptation_effects():
    """The existing profile switch fails closed without deleting a record."""

    storage, _ = _storage()
    event = _Event(message_id="l29-disable", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert await storage.get_response_preference_for_event(event, now=21.0) is not None

    storage._is_available = False
    assert await storage.get_response_preference_for_event(event, now=22.0) is None
    assert (await storage.request_explicit_response_preference(event, now=22.0)).code == "unavailable"


@pytest.mark.asyncio
async def test_l27_dry_run_requires_exact_identity_and_never_writes():
    storage, backend = _storage()
    event = _Event(message_id="l27-dry-run", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    writes_before = backend.put_calls

    ready = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=30.0,
    )

    assert ready.success is True
    assert ready.code == "ready"
    assert ready.plan is not None
    assert ready.plan.record_sha256
    assert ready.plan.namespace_payload_sha256
    assert backend.put_calls == writes_before

    mismatch = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        type(approved.record.source)(
            approved.record.source.source_kind, "napcat-instance-1:other-message"
        ),
        now=30.0,
    )
    assert mismatch.code == "source_mismatch"
    assert backend.put_calls == writes_before

    other_scope = type(approved.record.scope)(
        approved.record.scope.platform_id,
        "other-account",
        approved.record.scope.user_id,
        approved.record.scope.conversation_id,
    )
    cross_scope = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        other_scope,
        approved.record.source,
        now=30.0,
    )
    assert cross_scope.code == "scope_mismatch"
    assert backend.put_calls == writes_before


@pytest.mark.asyncio
async def test_l28_conditional_revocation_backs_up_and_restores_virtual_record(tmp_path):
    storage, backend = _storage()
    event = _Event(message_id="l28-revoke", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    dry_run = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=25.0,
    )
    assert dry_run.plan is not None

    backup_dir = tmp_path / "iris-d10" / "l28-virtual-001"
    written = await storage.execute_response_preference_revocation(
        dry_run.plan, "L28-RP-virtual-001", backup_dir, now=30.0
    )

    assert written.success is True
    assert written.code == "revoked"
    assert written.after_payload_sha256 is not None
    assert (backup_dir / "response_style_preference.v1.before.json").is_file()
    assert (backup_dir / "manifest.json").is_file()
    assert (backup_dir / "response_style_preference.v1.after.sha256").is_file()
    changed = await storage.list_response_preferences()
    assert changed[0].status == REVOKED
    assert changed[0].revoked_by == "migration:L28-RP-virtual-001"

    restored = await storage.restore_response_preference_revocation_backup(
        backup_dir, written.after_payload_sha256
    )

    assert restored.success is True
    assert restored.code == "restored"
    restored_records = await storage.list_response_preferences()
    assert restored_records[0].status == APPROVED
    assert restored_records[0].revoked_by is None
    assert backend.put_calls >= 4


@pytest.mark.asyncio
async def test_l28_conflict_skips_without_creating_backup_or_writing(tmp_path):
    storage, backend = _storage()
    event = _Event(message_id="l28-conflict", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    dry_run = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=21.0,
    )
    assert dry_run.plan is not None
    await storage.revoke_response_preference(
        approved.record.candidate_id, "operator", now=25.0
    )
    writes_before = backend.put_calls
    backup_dir = tmp_path / "iris-d10" / "l28-conflict-001"

    conflict = await storage.execute_response_preference_revocation(
        dry_run.plan, "L28-RP-virtual-002", backup_dir, now=30.0
    )

    assert conflict.success is False
    assert conflict.code == "skipped_conflict"
    assert backend.put_calls == writes_before
    assert not backup_dir.exists()


@pytest.mark.asyncio
async def test_l28_reports_committed_unverified_when_final_backup_marker_fails(
    tmp_path, monkeypatch
):
    storage, _ = _storage()
    event = _Event(message_id="l28-marker-failure", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    dry_run = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=25.0,
    )
    assert dry_run.plan is not None

    original_write_text = Path.write_text

    def fail_after_marker(path, data, *args, **kwargs):
        if path.name == "response_style_preference.v1.after.sha256":
            raise OSError("fixture final marker failure")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_marker)
    result = await storage.execute_response_preference_revocation(
        dry_run.plan,
        "L28-RP-marker-failure",
        tmp_path / "iris-d10" / "l28-marker-failure",
        now=30.0,
    )

    assert result.success is False
    assert result.code == "committed_unverified"
    assert result.after_payload_sha256 is not None
    records = await storage.list_response_preferences()
    assert records[0].status == REVOKED


@pytest.mark.asyncio
async def test_l28_rejects_corrupted_backup_without_writing(tmp_path):
    storage, backend = _storage()
    event = _Event(message_id="l28-corrupt-backup", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    dry_run = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=25.0,
    )
    assert dry_run.plan is not None
    backup_dir = tmp_path / "iris-d10" / "l28-corrupt-backup"
    written = await storage.execute_response_preference_revocation(
        dry_run.plan, "L28-RP-corrupt-backup", backup_dir, now=30.0
    )
    assert written.after_payload_sha256 is not None
    (backup_dir / "response_style_preference.v1.before.json").write_text(
        "{}", encoding="utf-8"
    )
    writes_before = backend.put_calls

    result = await storage.restore_response_preference_revocation_backup(
        backup_dir, written.after_payload_sha256
    )

    assert result.success is False
    assert result.code == "invalid_backup"
    assert backend.put_calls == writes_before


@pytest.mark.asyncio
async def test_l28_compare_and_swap_conflict_leaves_record_unchanged(tmp_path):
    storage, backend = _storage()
    event = _Event(message_id="l28-cas-conflict", message="以后这个私聊先给结论")
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.record is not None
    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.record is not None
    dry_run = await storage.dry_run_response_preference_revocation(
        approved.record.candidate_id,
        approved.record.scope,
        approved.record.source,
        now=25.0,
    )
    assert dry_run.plan is not None
    backend.fail_compare_and_swap = True

    result = await storage.execute_response_preference_revocation(
        dry_run.plan,
        "L28-RP-cas-conflict",
        tmp_path / "iris-d10" / "l28-cas-conflict",
        now=30.0,
    )

    assert result.success is False
    assert result.code == "skipped_conflict"
    records = await storage.list_response_preferences()
    assert records[0].status == APPROVED


@pytest.mark.asyncio
async def test_same_source_is_idempotent_and_does_not_extend_expiry():
    storage, _ = _storage()
    event = _Event(message_id="same-source")
    first = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10.0
    )
    duplicate = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=20.0
    )
    assert first.code == "pending"
    assert duplicate.code == "duplicate"
    assert duplicate.record is not None
    assert duplicate.record.candidate_id == first.record.candidate_id

    approved = await storage.approve_response_preference(
        first.record.candidate_id, "maintainer-1", now=30.0
    )
    assert approved.success is True
    repeated = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=40.0
    )
    assert repeated.code == "duplicate"
    assert repeated.record is not None
    assert repeated.record.expires_at == 30.0 + 7 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_duplicate_approval_is_idempotent_and_preserves_expiry():
    storage, _ = _storage()
    event = _Event(message_id="approve-once")
    pending = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10.0
    )
    assert pending.record is not None

    first = await storage.approve_response_preference(
        pending.record.candidate_id, "admin", now=20.0
    )
    repeated = await storage.approve_response_preference(
        pending.record.candidate_id, "admin-again", now=999.0
    )

    assert first.success is True
    assert first.code == "approved"
    assert repeated.success is False
    assert repeated.code == "already_processed"
    assert repeated.record is not None
    assert repeated.record.status == APPROVED
    assert repeated.record.expires_at == 20.0 + 7 * 24 * 60 * 60
    records = await storage.list_response_preferences()
    assert len(records) == 1
    assert records[0].status == APPROVED


@pytest.mark.asyncio
async def test_concurrent_approvals_have_one_winner():
    storage, _ = _storage()
    event = _Event(message_id="concurrent-approve")
    pending = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10.0
    )
    assert pending.record is not None

    results = await asyncio.gather(
        storage.approve_response_preference(
            pending.record.candidate_id, "admin-a", now=20.0
        ),
        storage.approve_response_preference(
            pending.record.candidate_id, "admin-b", now=20.0
        ),
    )

    assert sorted(result.code for result in results) == [
        "already_processed",
        "approved",
    ]
    assert sum(result.success for result in results) == 1
    records = await storage.list_response_preferences()
    assert len(records) == 1
    assert records[0].status == APPROVED
    assert records[0].expires_at == 20.0 + 7 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_concurrent_approve_and_revoke_cannot_resurrect_preference():
    storage, _ = _storage()
    event = _Event(message_id="concurrent-revoke")
    pending = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10.0
    )
    assert pending.record is not None

    approve, revoke = await asyncio.gather(
        storage.approve_response_preference(
            pending.record.candidate_id, "admin", now=20.0
        ),
        storage.revoke_response_preference(
            pending.record.candidate_id, "revoker", now=21.0
        ),
    )

    assert approve.code in {"approved", "already_processed"}
    assert revoke.code in {"revoked", "already_revoked"}
    assert await storage.get_response_preference_for_event(event, now=22.0) is None
    records = await storage.list_response_preferences()
    assert len(records) == 1
    assert records[0].status == REVOKED


@pytest.mark.asyncio
async def test_distinct_profile_storage_instances_share_response_preference_rmw_lock():
    kv = _KV()
    first = ProfileStorage(kv)
    second = ProfileStorage(kv)
    first._is_available = True
    second._is_available = True
    first_event = _Event(message_id="shared-rmw-1", sender_id="user-a")
    second_event = _Event(message_id="shared-rmw-2", sender_id="user-b")

    results = await asyncio.gather(
        first.request_response_preference(first_event, "CONCLUSION_FIRST", now=10),
        second.request_response_preference(second_event, "CONCLUSION_FIRST", now=10),
    )

    assert [result.code for result in results] == ["pending", "pending"]
    records = await first.list_response_preferences()
    assert len(records) == 2
    assert {record.scope.user_id for record in records} == {"user-a", "user-b"}


@pytest.mark.asyncio
async def test_failed_approval_write_stays_pending_after_reopen():
    storage, backend = _storage()
    event = _Event(message_id="approval-write-failure")
    pending = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10.0
    )
    assert pending.record is not None

    backend.fail_put = True
    failed = await storage.approve_response_preference(
        pending.record.candidate_id, "admin", now=20.0
    )
    assert failed.success is False
    assert failed.code == "write_failed"

    restarted = ProfileStorage(backend)
    restarted._is_available = True
    records = await restarted.list_response_preferences()
    assert len(records) == 1
    assert records[0].status == PENDING
    assert await restarted.get_response_preference_for_event(event, now=21.0) is None


@pytest.mark.asyncio
async def test_conflicting_approved_value_suspends_old_value():
    storage, _ = _storage()
    first_event = _Event(message_id="first")
    second_event = _Event(message_id="second")
    first = await storage.request_response_preference(first_event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(first.record.candidate_id, "admin", now=20)
    second = await storage.request_response_preference(second_event, "DEFAULT", now=30)
    approved = await storage.approve_response_preference(second.record.candidate_id, "admin", now=40)
    assert approved.success is True
    records = await storage.list_response_preferences()
    old = next(record for record in records if record.candidate_id == first.record.candidate_id)
    assert old.status == SUSPENDED
    assert (await storage.get_response_preference_for_event(first_event, now=41)).value == "DEFAULT"


@pytest.mark.asyncio
async def test_pending_conflict_suspends_old_value_before_manual_approval():
    storage, _ = _storage()
    first_event = _Event(message_id="pending-first")
    first = await storage.request_response_preference(first_event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(first.record.candidate_id, "admin", now=20)

    second_event = _Event(message_id="pending-opposite")
    second = await storage.request_response_preference(second_event, "DEFAULT", now=30)
    assert second.success is True and second.code == "pending"
    records = await storage.list_response_preferences()
    old = next(record for record in records if record.candidate_id == first.record.candidate_id)
    assert old.status == SUSPENDED
    assert await storage.get_response_preference_for_event(first_event, now=31) is None

    approved = await storage.approve_response_preference(second.record.candidate_id, "admin", now=40)
    assert approved.success is True
    assert (await storage.get_response_preference_for_event(first_event, now=41)).value == "DEFAULT"


@pytest.mark.asyncio
async def test_revoke_and_expiry_restore_default_without_replay():
    storage, backend = _storage()
    event = _Event(message_id="revoke-me")
    pending = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(
        pending.record.candidate_id, "admin", now=time.time()
    )
    assert await storage.get_response_preference_for_event(event, now=21) is not None
    revoked = await storage.revoke_response_preferences_for_event(event, now=22)
    assert revoked.success is True
    assert await storage.get_response_preference_for_event(event, now=23) is None
    replay = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=24)
    assert replay.code == "duplicate"
    assert replay.record is not None and replay.record.status == REVOKED

    # A distinct source can be approved, but the seven-day boundary is strict.
    expiry_event = _Event(message_id="expires")
    expiry_candidate = await storage.request_response_preference(
        expiry_event, "CONCLUSION_FIRST", now=100
    )
    await storage.approve_response_preference(expiry_candidate.record.candidate_id, "admin", now=200)
    assert await storage.get_response_preference_for_event(expiry_event, now=200 + 7 * 24 * 60 * 60) is None
    restarted = ProfileStorage(backend)
    restarted._is_available = True
    assert await restarted.get_response_preference_for_event(expiry_event, now=9999999999) is None


@pytest.mark.asyncio
async def test_scope_and_source_fail_closed_for_group_missing_identity_and_other_user():
    storage, _ = _storage()
    assert (await storage.request_response_preference(_Event(private=False, group_id="g"), "CONCLUSION_FIRST")).code == "invalid_scope"
    missing = _Event()
    missing.get_platform_id = None
    assert (await storage.request_response_preference(missing, "CONCLUSION_FIRST")).code == "invalid_scope"
    no_message_id = _Event()
    no_message_id.message_obj = SimpleNamespace()
    assert (await storage.request_response_preference(no_message_id, "CONCLUSION_FIRST")).code == "missing_source"

    event = _Event(message_id="target")
    candidate = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(candidate.record.candidate_id, "admin", now=20)
    other_user = _Event(message_id="other", sender_id="user-2")
    other_account = _Event(message_id="account", account_id="bot-2")
    other_platform = _Event(message_id="platform", platform_id="other-instance")
    assert await storage.get_response_preference_for_event(other_user, now=21) is None
    assert await storage.get_response_preference_for_event(other_account, now=21) is None
    assert await storage.get_response_preference_for_event(other_platform, now=21) is None


@pytest.mark.asyncio
async def test_corrupt_store_and_write_failure_never_publish_success_or_inject():
    storage, backend = _storage()
    backend.values[RESPONSE_PREFERENCE_KV_KEY] = {"schema_version": "unknown", "records": []}
    event = _Event()
    assert await storage.get_response_preference_for_event(event, now=1) is None
    result = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=1)
    assert result.success is False and result.code == "write_failed"

    clean_storage, clean_backend = _storage()
    clean_backend.fail_put = True
    failed = await clean_storage.request_response_preference(event, "CONCLUSION_FIRST", now=1)
    assert failed.success is False and failed.code == "write_failed"


@pytest.mark.asyncio
async def test_lifecycle_conflict_in_approved_record_fails_closed():
    storage, backend = _storage()
    event = _Event(message_id="lifecycle-conflict")
    candidate = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(candidate.record.candidate_id, "admin", now=20)
    raw_record = backend.values[RESPONSE_PREFERENCE_KV_KEY]["records"][0]
    raw_record["revoked_by"] = "user:user-1"
    raw_record["revoked_at"] = 21
    assert await storage.get_response_preference_for_event(event, now=22) is None


@pytest.mark.asyncio
async def test_final_provider_request_injects_one_controlled_block_and_current_detail_wins():
    storage, _ = _storage()
    event = _Event(message_id="hook", message="普通问题")
    pending = await storage.request_response_preference(event, "CONCLUSION_FIRST", now=10)
    await storage.approve_response_preference(
        pending.record.candidate_id, "admin", now=time.time()
    )
    short = await storage.request_response_preference(
        event,
        "SHORT",
        parameter=RESPONSE_LENGTH_PARAMETER,
        now=11,
    )
    await storage.approve_response_preference(
        short.record.candidate_id, "admin", now=time.time()
    )
    manager = _Manager(storage)
    req = SimpleNamespace(extra_user_content_parts=[], prompt="当前问题", contexts=[])

    async def empty(*args, **kwargs):
        return ""

    async def empty_l2(*args, **kwargs):
        return "", []

    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
    ):
        await preprocess_llm_request(event, req, manager)
        await preprocess_llm_request(event, req, manager)

    text = "\n".join(part.text for part in req.extra_user_content_parts)
    assert text.count(RESPONSE_PREFERENCE_MARKER) == 1
    assert "先给直接结论" in text
    assert "减少非必要展开" in text
    assert "不机械截断" in text
    assert "保留必要依据、执行结果和错误信息" in text

    event.message_str = "这次请详细解释计算过程"
    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
    ):
        await preprocess_llm_request(event, req, manager)
    text = "\n".join(part.text for part in req.extra_user_content_parts)
    assert RESPONSE_PREFERENCE_MARKER not in text


@pytest.mark.asyncio
async def test_l18_memory_retrieval_preference_uses_existing_hook_and_frozen_boundaries():
    """The approved hint reaches the provider request without creating a tool call."""

    storage, _ = _storage()
    manager = _Manager(storage)
    event = _Event(
        message_id="tool-pref-1",
        message="我以前说过什么？",
        sender_id="user-tool",
    )

    pending = await storage.request_memory_retrieval_preference(event, now=time.time())
    assert pending.success and pending.code == "pending"
    assert pending.record is not None
    assert pending.record.parameter == MEMORY_RETRIEVAL_PARAMETER
    assert pending.record.value == MEMORY_RETRIEVAL_ON
    assert await _collect_tool_preference(event, manager) == ""

    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=time.time()
    )
    assert approved.success and approved.record is not None

    # Broad time/history words are valid L2 query inputs, but they are not a
    # direct request to retrieve this user's private chat history.
    for ordinary_request in (
        "解释历史唯物主义",
        "提交之前运行测试",
        "这个项目的记忆占用多少？",
    ):
        event.message_str = ordinary_request
        assert await _collect_tool_preference(event, manager) == ""
    event.message_str = "我以前说过什么？"

    forwarded = _Event(
        message_id="tool-pref-forwarded",
        message="我以前说过什么？",
        sender_id="user-tool",
        messages=[_Forward()],
    )
    assert await _collect_tool_preference(forwarded, manager) == ""

    async def empty(*args, **kwargs):
        return ""

    async def empty_l2(*args, **kwargs):
        return "", []

    req = SimpleNamespace(extra_user_content_parts=[], prompt="当前问题", contexts=[])
    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
    ):
        await preprocess_llm_request(event, req, manager)
        text = "\n".join(part.text for part in req.extra_user_content_parts)
        assert text.count(TOOL_PREFERENCE_MARKER) == 1
        assert "已有 search_memory 只读记忆检索" in text
        assert "不得因此新增工具权限" in text

        # A fixed current-turn no-tool instruction wins over the saved hint.
        event.message_str = "我以前说过什么？不要联网"
        await preprocess_llm_request(event, req, manager)
        text = "\n".join(part.text for part in req.extra_user_content_parts)
        assert TOOL_PREFERENCE_MARKER not in text

        # The same user text in another private scope cannot borrow the hint.
        other = _Event(
            message_id="tool-pref-other",
            message="我以前说过什么？",
            sender_id="different-user",
        )
        await preprocess_llm_request(other, req, manager)
        text = "\n".join(part.text for part in req.extra_user_content_parts)
        assert TOOL_PREFERENCE_MARKER not in text

    revoked = await storage.revoke_response_preference(
        pending.record.candidate_id, "user-tool", now=time.time()
    )
    assert revoked.success and revoked.code == "revoked"
    event.message_str = "我以前说过什么？"
    assert await _collect_tool_preference(event, manager) == ""

    expired_event = _Event(
        message_id="tool-pref-expired",
        message="我以前说过什么？",
        sender_id="expired-user",
    )
    expired_pending = await storage.request_memory_retrieval_preference(
        expired_event, now=time.time() - 100
    )
    assert expired_pending.record is not None
    expired_at = time.time() - 7 * 24 * 60 * 60
    await storage.approve_response_preference(
        expired_pending.record.candidate_id, "maintainer", now=expired_at
    )
    assert await _collect_tool_preference(expired_event, manager) == ""


def test_literal_preference_marker_in_ordinary_context_does_not_delete_the_context():
    req = SimpleNamespace(extra_user_content_parts=[])
    _inject_to_extra_user_content_parts(
        req,
        "历史记忆讨论了 <iris:response_style_preference> 标签本身",
        "画像内容仍然需要保留",
        "",
        "",
        "",
    )
    assert len(req.extra_user_content_parts) == 1
    injected = req.extra_user_content_parts[0].text
    assert "历史记忆讨论了 <iris:response_style_preference> 标签本身" in injected
    assert "画像内容仍然需要保留" in injected


@pytest.mark.asyncio
async def test_admin_command_parser_and_handler_use_only_system_candidate_id():
    storage, _ = _storage()
    event = _Event(message_id="admin-command")
    candidate = await storage.request_response_preference(
        event, "CONCLUSION_FIRST", now=10
    )
    assert candidate.record is not None
    manager = _Manager(storage)
    handler = ResponsePreferenceCommandHandler()
    registry = get_registry()
    original_handlers = registry._handlers.copy()

    try:
        registry.register(handler)
        with patch(
            "iris_memory.commands.response_preference_handler.get_component_manager",
            return_value=manager,
        ):
            event.message_outline = "iris_mem preference pending"
            pending = await execute_command(event)
            assert pending is not None
            assert candidate.record.candidate_id in pending

            event.message_outline = (
                f"iris_mem preference approve {candidate.record.candidate_id}"
            )
            approved = await execute_command(event)
            assert approved is not None
            assert "有效 7 天" in approved

            event.message_outline = "iris_mem preference status"
            before_status_read = repr(storage._storage.values)
            status = await execute_command(event)
            assert status is not None
            assert "已批准" in status
            assert "response_expansion=CONCLUSION_FIRST" in status
            assert "platform=napcat-instance-1 account=bot-1" in status
            assert "source=EXPLICIT_CONTROLLED_REQUEST:napcat-instance-1:admin-command" in status
            assert "expires_at=" in status
            assert "reason=approved_by_manual_review" in status
            assert repr(storage._storage.values) == before_status_read

            event.message_outline = (
                f"iris_mem preference revoke {candidate.record.candidate_id}"
            )
            revoked = await execute_command(event)
            assert revoked is not None
            assert "恢复默认表达" in revoked

            event.message_outline = "iris_mem preference approve forged"
            forged = await execute_command(event)
            assert forged is not None
            assert "系统生成的 rspref" in forged
    finally:
        registry._handlers = original_handlers


@pytest.mark.asyncio
async def test_l11_eligible_feedback_aggregate_creates_one_pending_candidate_and_reuses_profile_kv():
    """L09 review output enters the existing approval path without auto-publishing."""

    storage, backend = _storage()
    event = _Event(message_id="l11-aggregate", message="下一轮问题")
    scope = scope_from_event(event)
    assert scope is not None
    aggregate = ResponseLengthFeedbackAggregateV1(
        scope=scope,
        parameter=RESPONSE_LENGTH_PARAMETER,
        value=SHORT,
        feedback_refs=(
            ("feedback-a", "inbound-a", "link-a", "host-a"),
            ("feedback-b", "inbound-b", "link-b", "host-b"),
        ),
        invalidated_feedback_refs=(),
        out_of_window_feedback_refs=(),
        distinct_source_event_count=2,
        distinct_reply_link_count=2,
        distinct_host_output_count=2,
        eligible=True,
        reason=RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON,
    )

    pending = await storage.request_response_length_preference_from_aggregate(
        aggregate, now=100.0
    )
    assert pending.code == "pending"
    assert pending.record is not None
    assert pending.record.status == PENDING
    assert pending.record.source.source_kind == RESPONSE_LENGTH_FEEDBACK_AGGREGATE_SOURCE_KIND
    assert await storage.get_response_preference_for_event(
        event, parameter=RESPONSE_LENGTH_PARAMETER, now=101.0
    ) is None

    replay = await storage.request_response_length_preference_from_aggregate(
        aggregate, now=102.0
    )
    assert replay.code == "duplicate"
    assert replay.record is not None
    assert replay.record.candidate_id == pending.record.candidate_id
    assert len((await storage.list_response_preferences())) == 1

    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=110.0
    )
    assert approved.code == "approved"
    active = await storage.get_response_preference_for_event(
        event, parameter=RESPONSE_LENGTH_PARAMETER, now=111.0
    )
    assert active is not None and active.value == SHORT
    assert backend.values[RESPONSE_PREFERENCE_KV_KEY]["schema_version"] == "response-style-preference.v1"

    ineligible = ResponseLengthFeedbackAggregateV1(
        scope=scope,
        parameter=RESPONSE_LENGTH_PARAMETER,
        value=SHORT,
        feedback_refs=(),
        invalidated_feedback_refs=(),
        out_of_window_feedback_refs=(),
        distinct_source_event_count=0,
        distinct_reply_link_count=0,
        distinct_host_output_count=0,
        eligible=False,
        reason="d02_insufficient_independent_evidence",
    )
    assert (
        await storage.request_response_length_preference_from_aggregate(
            ineligible, now=112.0
        )
    ).code == "aggregate_ineligible"


@pytest.mark.asyncio
async def test_l11_admin_command_invokes_existing_review_observer_consolidator():
    storage, _ = _storage()
    event = _Event(message_id="l11-admin-aggregate")
    scope = scope_from_event(event)
    assert scope is not None
    aggregate = ResponseLengthFeedbackAggregateV1(
        scope=scope,
        parameter=RESPONSE_LENGTH_PARAMETER,
        value=SHORT,
        feedback_refs=(
            ("feedback-c", "inbound-c", "link-c", "host-c"),
            ("feedback-d", "inbound-d", "link-d", "host-d"),
        ),
        invalidated_feedback_refs=(),
        out_of_window_feedback_refs=(),
        distinct_source_event_count=2,
        distinct_reply_link_count=2,
        distinct_host_output_count=2,
        eligible=True,
        reason=RESPONSE_LENGTH_FEEDBACK_AGGREGATION_ELIGIBLE_REASON,
    )

    class _Observer:
        async def consolidate_eligible(self, owner):
            return (
                await owner.request_response_length_preference_from_aggregate(
                    aggregate, now=200.0
                ),
            )

    manager = _Manager(storage)
    handler = ResponsePreferenceCommandHandler()
    registry = get_registry()
    original_handlers = registry._handlers.copy()
    try:
        registry.register(handler)
        with (
            patch(
                "iris_memory.commands.response_preference_handler.get_component_manager",
                return_value=manager,
            ),
            patch(
                "iris_memory.cognitive.iris_adapter.get_cognitive_runtime",
                return_value=SimpleNamespace(
                    response_length_feedback_observer=_Observer()
                ),
            ),
        ):
            event.message_outline = "iris_mem preference consolidate_length"
            result = await execute_command(event)
        assert result is not None
        assert "待人工核实候选" in result
        assert "批准后才会影响请求" in result
        records = await storage.list_response_preferences(status=PENDING)
        assert len(records) == 1
    finally:
        registry._handlers = original_handlers


@pytest.mark.asyncio
async def test_l13_complete_local_demo_with_fixed_clock():
    """Walk the bounded preference lifecycle without producing an answer."""

    storage, _ = _storage()
    event = _Event(message_id="l13-fixed-clock", message="初始问题")
    manager = _Manager(storage)
    empty_parts = []

    async def empty(*args, **kwargs):
        return ""

    async def empty_l2(*args, **kwargs):
        return "", []

    def request():
        return SimpleNamespace(
            extra_user_content_parts=list(empty_parts),
            prompt="当前问题",
            contexts=[],
        )

    def injected_text(req):
        return "\n".join(part.text for part in req.extra_user_content_parts)

    # Initial request: the default path has no controlled preference block.
    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
        patch("iris_memory.profile.storage.time.time", return_value=1.0),
    ):
        initial = request()
        await preprocess_llm_request(event, initial, manager)
    assert RESPONSE_PREFERENCE_MARKER not in injected_text(initial)

    # An explicit continuous request creates a pending candidate only.
    event.message_str = "以后这个私聊先给结论"
    pending = await storage.request_explicit_response_preference(event, now=10.0)
    assert pending.code == "pending"
    assert pending.record is not None and pending.record.status == PENDING

    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
        patch("iris_memory.profile.storage.time.time", return_value=11.0),
    ):
        pending_request = request()
        await preprocess_llm_request(event, pending_request, manager)
    assert RESPONSE_PREFERENCE_MARKER not in injected_text(pending_request)

    approved = await storage.approve_response_preference(
        pending.record.candidate_id, "maintainer", now=20.0
    )
    assert approved.code == "approved"
    assert approved.record is not None and approved.record.expires_at == 20.0 + 7 * 24 * 60 * 60

    # The next request sees exactly one controlled block after approval.
    event.message_str = "下一轮问题"
    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
        patch("iris_memory.profile.storage.time.time", return_value=21.0),
    ):
        approved_request = request()
        await preprocess_llm_request(event, approved_request, manager)
    approved_text = injected_text(approved_request)
    assert approved_text.count(RESPONSE_PREFERENCE_MARKER) == 1
    assert "先给直接结论" in approved_text

    # The current detailed request overrides the saved expression preference.
    event.message_str = "这次请详细解释计算过程"
    with (
        patch("iris_memory.core.llm_request_hook._collect_l1_context", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_user_profile", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_l2_memory", new=empty_l2),
        patch("iris_memory.core.llm_request_hook._collect_l3_knowledge_graph", new=empty),
        patch("iris_memory.core.llm_request_hook._collect_learning", new=empty),
        patch("iris_memory.core.llm_request_hook._schedule_related_image_parse"),
        patch("iris_memory.core.llm_request_hook._record_injection_log"),
        patch("iris_memory.core.llm_request_hook._log_final_context"),
        patch("iris_memory.profile.storage.time.time", return_value=22.0),
    ):
        detailed_request = request()
        await preprocess_llm_request(event, detailed_request, manager)
    assert RESPONSE_PREFERENCE_MARKER not in injected_text(detailed_request)

    revoked = await storage.revoke_response_preferences_for_event(event, now=23.0)
    assert revoked.code == "revoked"
    assert await storage.get_response_preference_for_event(event, now=24.0) is None

    # Reopening the same KV keeps the revoked state and does not resurrect it.
    restarted = ProfileStorage(storage._storage)
    restarted._is_available = True
    records = await restarted.list_response_preferences()
    assert len(records) == 1
    assert records[0].status == REVOKED


@pytest.mark.asyncio
async def test_p2b_explicit_publish_requires_approved_short_candidate_and_is_idempotent():
    storage, backend = _storage()
    pending = _p2b_candidate(status=CandidateStatus.PENDING)

    before = await storage.publish_p2b_candidate(pending, "maintainer", now=110.0)
    assert not before.success and before.code == "not_approved"
    assert await storage.list_response_preferences() == []

    approved = replace(pending, status=CandidateStatus.APPROVED)
    published = await storage.publish_p2b_candidate(
        approved, "maintainer", now=110.0
    )
    assert published.success and published.code == "published"
    assert published.record is not None
    assert published.record.status == APPROVED
    assert published.record.parameter == RESPONSE_LENGTH_PARAMETER
    assert published.record.value == SHORT
    assert published.record.source.source_kind == P2B_EXPLICIT_PUBLISH_SOURCE_KIND
    assert published.record.source.source_event_id.startswith("p2b:")
    assert published.record.expires_at == 110.0 + 7 * 24 * 60 * 60
    assert backend.put_calls == 1  # publication used CAS, not put_kv_data

    repeated = await storage.publish_p2b_candidate(
        approved, "another-maintainer", now=111.0
    )
    assert repeated.success and repeated.code == "already_published"
    assert repeated.record is not None
    assert repeated.record.candidate_id == published.record.candidate_id
    assert len(await storage.list_response_preferences()) == 1


@pytest.mark.asyncio
async def test_p2b_explicit_publish_keeps_private_uid_scopes_isolated():
    storage, _ = _storage()
    first = _p2b_candidate(user_id="p2b-user-a")
    second = _p2b_candidate(user_id="p2b-user-b")

    assert (await storage.publish_p2b_candidate(first, "maintainer", now=110.0)).code == "published"
    second_result = await storage.publish_p2b_candidate(second, "maintainer", now=110.0)
    assert second_result.success and second_result.code == "published"
    records = await storage.list_response_preferences()
    assert len(records) == 2
    assert {record.scope.user_id for record in records} == {"p2b-user-a", "p2b-user-b"}


@pytest.mark.asyncio
async def test_p2b_explicit_publish_fails_closed_on_conflict_and_unsupported_candidate():
    storage, _ = _storage()
    event = _Event(
        message_id="p2b-conflict",
        sender_id="p2b-user-a",
        message="管理员创建的冲突候选",
    )
    pending_default = await storage.request_response_preference(
        event, "DEFAULT", parameter=RESPONSE_LENGTH_PARAMETER, now=100.0
    )
    assert pending_default.code == "pending"

    conflicting = await storage.publish_p2b_candidate(
        _p2b_candidate(user_id="p2b-user-a"), "maintainer", now=110.0
    )
    assert not conflicting.success and conflicting.code == "conflict"
    assert len(await storage.list_response_preferences()) == 1

    unsupported = await storage.publish_p2b_candidate(
        _p2b_candidate(
            parameter=BehaviorParameter.ANSWER_STRUCTURE,
            value="CONCLUSION_FIRST",
        ),
        "maintainer",
        now=110.0,
    )
    assert not unsupported.success and unsupported.code == "unsupported"


@pytest.mark.asyncio
async def test_p2b_explicit_publish_rejects_expired_candidate_and_missing_cas():
    storage, backend = _storage()
    expired = _p2b_candidate(
        expires_at=datetime.fromtimestamp(110.0, timezone.utc),
    )
    result = await storage.publish_p2b_candidate(expired, "maintainer", now=110.0)
    assert not result.success and result.code == "expired"
    assert await storage.list_response_preferences() == []

    backend.compare_and_swap_kv_data = None  # type: ignore[method-assign]
    cas_result = await storage.publish_p2b_candidate(
        _p2b_candidate(user_id="p2b-user-c"), "maintainer", now=110.0
    )
    assert not cas_result.success and cas_result.code == "storage_failed"
    assert await storage.list_response_preferences() == []


@pytest.mark.asyncio
async def test_p2b_explicit_unpublish_revokes_only_the_deterministic_publication():
    storage, _ = _storage()
    candidate = _p2b_candidate()
    published = await storage.publish_p2b_candidate(candidate, "maintainer", now=110.0)
    assert published.code == "published"
    located = await storage.find_p2b_publication(candidate)
    assert located is not None and located.status == APPROVED

    removed = await storage.unpublish_p2b_candidate(candidate, "maintainer", now=120.0)
    assert removed.success is True and removed.code == "unpublished"
    assert removed.record is not None and removed.record.status == REVOKED
    repeated = await storage.unpublish_p2b_candidate(candidate, "maintainer", now=121.0)
    assert repeated.success is True and repeated.code == "already_unpublished"


@pytest.mark.asyncio
async def test_p2b_publish_reports_committed_unverified_after_cas_readback_failure():
    class _ReadbackFailureKV(_KV):
        def __init__(self) -> None:
            super().__init__()
            self.cas_done = False

        async def get_kv_data(self, key: str, default: object) -> object:
            if self.cas_done:
                raise OSError("fixture readback failure")
            return await super().get_kv_data(key, default)

        async def compare_and_swap_kv_data(
            self, key: str, expected: object, value: object
        ) -> bool:
            committed = await super().compare_and_swap_kv_data(key, expected, value)
            self.cas_done = committed
            return committed

    backend = _ReadbackFailureKV()
    storage = ProfileStorage(backend)
    storage._is_available = True
    result = await storage.publish_p2b_candidate(
        _p2b_candidate(), "maintainer", now=110.0
    )
    assert result.success is False
    assert result.code == "committed_unverified"
    assert RESPONSE_PREFERENCE_KV_KEY in backend.values


@pytest.mark.asyncio
async def test_p2b_admin_publish_requires_confirmation_and_current_authoritative_evidence(
    tmp_path,
):
    storage, _ = _storage()
    candidate_store = AppendOnlyBehaviorCandidateStore(tmp_path / "p2b.jsonl")
    candidate = _p2b_candidate(
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)
    )
    candidate_store.append_candidate(replace(candidate, status=CandidateStatus.PENDING))
    candidate_store.approve(candidate.candidate_id, actor="reviewer")
    runtime = SimpleNamespace(
        observatory_p2b_shadow_store=candidate_store,
        p2b_shadow_validate=lambda candidate_id: candidate_id == candidate.candidate_id,
    )
    handler = ResponsePreferenceCommandHandler()
    event = _Event(message_id="p2b-admin")
    manager = _Manager(storage)

    with (
        patch(
            "iris_memory.commands.response_preference_handler.get_component_manager",
            return_value=manager,
        ),
        patch(
            "iris_memory.cognitive.iris_adapter.get_cognitive_runtime",
            return_value=runtime,
        ),
    ):
        missing_confirmation = await handler.handle(
            event,
            ParsedArgs(raw_args=["p2b_publish", candidate.candidate_id]),
            "p2b_publish",
        )
        assert missing_confirmation.success is False
        assert await storage.find_p2b_publication(candidate) is None

        runtime.p2b_shadow_validate = lambda _candidate_id: False
        invalid = await handler.handle(
            event,
            ParsedArgs(raw_args=["p2b_publish", candidate.candidate_id, "CONFIRM"]),
            "p2b_publish",
        )
        assert invalid.success is False and "零写入" in invalid.message
        assert await storage.find_p2b_publication(candidate) is None

        runtime.p2b_shadow_validate = lambda candidate_id: candidate_id == candidate.candidate_id
        published = await handler.handle(
            event,
            ParsedArgs(raw_args=["p2b_publish", candidate.candidate_id, "CONFIRM"]),
            "p2b_publish",
        )
        assert published.success is True and "显式发布" in published.message

        blocked_revoke = await handler.handle(
            event,
            ParsedArgs(raw_args=["p2b_revoke", candidate.candidate_id]),
            "p2b_revoke",
        )
        assert blocked_revoke.success is False and "p2b_unpublish" in blocked_revoke.message

        unpublished = await handler.handle(
            event,
            ParsedArgs(raw_args=["p2b_unpublish", candidate.candidate_id, "CONFIRM"]),
            "p2b_unpublish",
        )
        assert unpublished.success is True and "恢复默认表达" in unpublished.message
