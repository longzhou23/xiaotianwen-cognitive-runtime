from __future__ import annotations

import pytest
from astrbot.api.provider import ProviderRequest
from astrbot_plugin_xiaotianwen_orchestrator.context import ContextBridgeV1
from astrbot_plugin_xiaotianwen_orchestrator.contracts import (
    ContractValidationError,
    ConversationKeyV1,
    ConversationScope,
)
from astrbot_plugin_xiaotianwen_orchestrator.conversation import (
    ConversationLedgerV1,
    ConversationRole,
    ConversationTurnAssemblerV1,
)
from astrbot_plugin_xiaotianwen_orchestrator.ingress import (
    conversation_key_from_event,
    event_to_envelope,
)
from astrbot_plugin_xiaotianwen_orchestrator.main import Main


def _event(
    message_id: str,
    text: str | None = None,
    *,
    group_id: str | None = "g-1",
    user_id: str = "u-1",
    umo: str = "onebot:group:g-1",
) -> dict[str, object]:
    value: dict[str, object] = {
        "message_id": message_id,
        "user_id": user_id,
        "platform_name": "aiocqhttp",
        "account_id": "bot-1",
        "unified_msg_origin": umo,
        "raw_message": text or message_id,
    }
    if group_id is not None:
        value["group_id"] = group_id
    return value


def test_group_identity_ignores_umo_but_separates_groups() -> None:
    first = conversation_key_from_event(_event("m-1", umo="synthetic-a"))
    second = conversation_key_from_event(_event("m-2", umo="synthetic-b"))
    other = conversation_key_from_event(_event("m-3", group_id="g-2", umo="synthetic-a"))

    assert first == second
    assert first.scope_kind is ConversationScope.GROUP
    assert first != other


def test_private_identity_uses_explicit_peer_and_is_stable() -> None:
    first = conversation_key_from_event(_event("m-1", group_id=None, user_id="peer-7", umo="onebot:private:old"))
    second = conversation_key_from_event(_event("m-2", group_id=None, user_id="peer-7", umo="onebot:private:new"))

    assert first == second
    assert first.scope_kind is ConversationScope.PRIVATE
    assert first.conversation_id == "peer-7"


def test_private_identity_fails_closed_without_explicit_peer() -> None:
    with pytest.raises(ContractValidationError):
        conversation_key_from_event(_event("m-1", group_id=None, user_id=""))


def test_real_astrbot_method_identity_is_authoritative() -> None:
    class MethodEvent:
        message_id = "m-method"

        def get_platform_id(self) -> str:
            return "aiocqhttp"

        def get_self_id(self) -> str:
            return "bot-9"

        def is_private_chat(self) -> bool:
            return False

        def get_group_id(self) -> str:
            return "group-method"

        def get_sender_id(self) -> str:
            return "member-1"

        def get_message_str(self) -> str:
            return "方法式身份"

    turn = event_to_envelope(MethodEvent(), received_at=1.0)

    assert turn.session_id == "conversation:aiocqhttp:bot-9:group:group-method"
    assert turn.sender_id == "member-1"


def test_real_astrbot_missing_platform_or_account_fails_closed() -> None:
    class IncompleteEvent:
        def is_private_chat(self) -> bool:
            return False

        def get_group_id(self) -> str:
            return "group-method"

        def get_sender_id(self) -> str:
            return "member-1"

    with pytest.raises(ContractValidationError):
        conversation_key_from_event(IncompleteEvent())


def test_method_group_identity_drives_group_metadata() -> None:
    class MethodEvent:
        def get_platform_id(self) -> str:
            return "aiocqhttp"

        def get_self_id(self) -> str:
            return "bot-9"

        def is_private_chat(self) -> bool:
            return False

        def get_group_id(self) -> str:
            return "group-method"

        def get_sender_id(self) -> str:
            return "member-1"

        def get_message_str(self) -> str:
            return "群消息"

    assert event_to_envelope(MethodEvent()).metadata["is_group"] is True


def test_canonical_assembler_merges_same_sender_and_finalizes_speaker_change() -> None:
    assembler = ConversationTurnAssemblerV1(quiet_window_seconds=3)
    first = event_to_envelope(_event("m-1", "甲一", user_id="a"), received_at=0)
    second = event_to_envelope(_event("m-2", "甲二", user_id="a"), received_at=1)
    third = event_to_envelope(_event("m-3", "乙一", user_id="b"), received_at=2)

    assert assembler.ingest(first, now=0) == ()
    assert assembler.ingest(second, now=1) == ()
    finalized = assembler.ingest(third, now=2)
    assert len(finalized) == 1
    assert finalized[0].sender_id == "a"
    assert finalized[0].text == "甲一\n甲二"
    tail = assembler.flush_ready(now=5)
    assert len(tail) == 1
    assert tail[0].sender_id == "b"


def test_canonical_assembler_quiet_expiry_finalizes_without_next_message() -> None:
    assembler = ConversationTurnAssemblerV1(quiet_window_seconds=3)
    turn = event_to_envelope(_event("m-1", "单条"), received_at=0)
    assembler.ingest(turn, now=0)

    assert assembler.flush_ready(now=3) == (turn,)


def test_canonical_assembler_capacity_eviction_returns_pending_turn() -> None:
    assembler = ConversationTurnAssemblerV1(quiet_window_seconds=3, max_conversations=1)
    first = event_to_envelope(_event("m-1", "先说", group_id="g-1"), received_at=0)
    second = event_to_envelope(_event("m-2", "后说", group_id="g-2"), received_at=1)
    assert assembler.ingest(first, now=0) == ()
    assert assembler.ingest(second, now=1) == (first,)


def test_envelope_carries_canonical_key_and_legacy_umo_only_as_metadata() -> None:
    turn = event_to_envelope(_event("m-1", umo="synthetic-umo"), received_at=1.0)

    assert turn.session_id == "conversation:aiocqhttp:bot-1:group:g-1"
    assert turn.metadata["legacy_umo"] == "synthetic-umo"
    assert turn.metadata["conversation_key"]["conversation_id"] == "g-1"


def test_ledger_preserves_speakers_bounds_and_resets() -> None:
    key = ConversationKeyV1("onebot", "bot", ConversationScope.GROUP, "g-1")
    ledger = ConversationLedgerV1(max_conversations=1, max_turns_per_conversation=3)
    ledger.append_user_turn(key, speaker_id="a", speaker_name="甲", content="今晚看土星", turn_id="u-1", occurred_at=1)
    ledger.append_user_turn(key, speaker_id="b", speaker_name="乙", content="那木星呢", turn_id="u-2", occurred_at=2)
    ledger.append_assistant_turn(key, content="可以先看土星", logical_response_id="r-1", occurred_at=3)
    assert [turn.role for turn in ledger.history(key)] == [ConversationRole.USER, ConversationRole.USER, ConversationRole.ASSISTANT]
    assert ledger.append_assistant_turn(key, content="重复发送不重复入历史", logical_response_id="r-1", occurred_at=4) is False
    assert ledger.append_assistant_turn(key, content="重复发送不重复入历史", logical_response_id="r-1", occurred_at=5) is False
    assert ledger.conversation_count == 1
    assert ledger.clear(key) is True
    assert ledger.history(key) == ()


def test_ledger_evicts_old_conversations_without_secondary_unbounded_state() -> None:
    ledger = ConversationLedgerV1(max_conversations=1, max_turns_per_conversation=2)
    for index in range(1000):
        key = ConversationKeyV1("onebot", "bot", ConversationScope.GROUP, f"g-{index}")
        ledger.append_user_turn(key, speaker_id="u", speaker_name="用户", content="消息", turn_id=f"u-{index}", occurred_at=index)
    assert ledger.conversation_count == 1


def test_context_bridge_excludes_current_turn_and_keeps_speaker_order() -> None:
    key = ConversationKeyV1("onebot", "bot", ConversationScope.GROUP, "g-1")
    ledger = ConversationLedgerV1()
    ledger.append_user_turn(key, speaker_id="a", speaker_name="甲", content="今晚能看到土星吗", turn_id="u-1", occurred_at=1)
    ledger.append_user_turn(key, speaker_id="b", speaker_name="乙", content="那木星呢", turn_id="u-2", occurred_at=2)
    ledger.append_assistant_turn(key, content="可以看", logical_response_id="r-1", occurred_at=3)
    ledger.append_user_turn(key, speaker_id="a", speaker_name="甲", content="当前问题", turn_id="u-current", occurred_at=4)

    section = ContextBridgeV1(max_chars=200).section(key, ledger, current_turn_id="u-current")

    assert section is not None
    assert section.source == "conversation_history"
    assert "甲: 当前问题" not in section.content
    assert section.content.index("甲: 今晚能看到土星吗") < section.content.index("乙: 那木星呢") < section.content.index("小天文: 可以看")


def test_context_bridge_keeps_fragment_of_oversized_newest_turn() -> None:
    key = ConversationKeyV1("onebot", "bot", ConversationScope.GROUP, "g-1")
    ledger = ConversationLedgerV1()
    ledger.append_user_turn(
        key,
        speaker_id="u",
        speaker_name="甲",
        content="这是一条很长的历史消息" * 20,
        turn_id="u-long",
        occurred_at=1,
    )

    section = ContextBridgeV1(max_chars=32).section(key, ledger)

    assert section is not None
    assert section.content.startswith("[最近对话]\n甲: ")
    assert len(section.content) <= 32


@pytest.mark.asyncio
async def test_runtime_hooks_are_default_off_and_enabled_path_uses_finalized_history() -> None:
    event_a = _event("m-a", "甲先说", user_id="a")
    event_b = _event("m-b", "乙后说", user_id="b")
    disabled = Main(object(), {})
    await disabled.on_message(event_a)
    assert disabled.conversation_ledger.conversation_count == 0

    enabled = Main(object(), {"conversation_runtime_enabled": True})
    await enabled.on_message(event_a)
    await enabled.on_message(event_b)
    assert event_b[Main.CONVERSATION_RUNTIME_OWNER] is True
    key = conversation_key_from_event(event_b)
    assert [turn.content for turn in enabled.conversation_ledger.history(key)] == ["甲先说"]

    request = ProviderRequest(prompt="乙后说")
    await enabled.on_llm_request(event_b, request)
    assert any("a: 甲先说" in str(getattr(part, "text", "")) for part in request.extra_user_content_parts)


@pytest.mark.asyncio
async def test_fast_request_finalizes_current_merged_turn_before_assistant() -> None:
    plugin = Main(object(), {"conversation_runtime_enabled": True})
    first = _event("m-fast-1", "甲一", user_id="a")
    second = _event("m-fast-2", "甲二", user_id="a")
    plugin.observe_inbound_turn(first, now=0)
    plugin.observe_inbound_turn(second, now=1)
    key = conversation_key_from_event(second)

    request = ProviderRequest(prompt="甲二")
    await plugin.on_llm_request(second, request)
    history = plugin.conversation_ledger.history(key)
    assert [(turn.role, turn.content) for turn in history] == [
        (ConversationRole.USER, "甲一\n甲二")
    ]
    assert not any("甲一" in str(getattr(part, "text", "")) for part in request.extra_user_content_parts)

    await plugin.on_llm_response(second, type("Response", (), {"completion_text": "答复"})())
    assert [turn.role for turn in plugin.conversation_ledger.history(key)] == [
        ConversationRole.USER,
        ConversationRole.ASSISTANT,
    ]


@pytest.mark.asyncio
async def test_repeated_request_hook_keeps_current_turn_excluded() -> None:
    plugin = Main(object(), {"conversation_runtime_enabled": True})
    event = _event("m-repeat", "当前", user_id="a")
    plugin.observe_inbound_turn(event, now=0)
    first_request = ProviderRequest(prompt="当前")
    await plugin.on_llm_request(event, first_request)
    second_request = ProviderRequest(prompt="当前")
    await plugin.on_llm_request(event, second_request)
    assert not any("当前" in str(getattr(part, "text", "")) for part in second_request.extra_user_content_parts)


@pytest.mark.asyncio
async def test_ledger_helper_flag_does_not_enable_live_hooks() -> None:
    event = _event("m-helper", "仅辅助", user_id="a")
    plugin = Main(object(), {"conversation_ledger_enabled": True})
    await plugin.on_message(event)
    assert plugin.conversation_ledger.conversation_count == 0
    plugin.observe_inbound_turn(event, now=0)
    assert plugin.conversation_assembler.flush_ready(now=10)


@pytest.mark.asyncio
async def test_host_reset_clears_ledger_and_pending_without_changing_key() -> None:
    plugin = Main(object(), {"conversation_runtime_enabled": True})
    first = _event("m-reset-1", "历史", user_id="a")
    second = _event("m-reset-2", "触发收束", user_id="b")
    await plugin.on_message(first)
    key = conversation_key_from_event(first)
    await plugin.on_message(second)
    assert plugin.conversation_ledger.history(key)
    reset = _event("m-reset-marker", "", user_id="a")
    reset["_clean_group_context_session"] = True
    await plugin.on_message(reset)
    assert plugin.conversation_ledger.history(key) == ()
    assert plugin.conversation_assembler.flush_ready(now=100) == ()
    assert conversation_key_from_event(reset) == key


@pytest.mark.asyncio
async def test_reset_and_new_commands_clear_without_recording_history() -> None:
    for command in ("/reset", "/new"):
        plugin = Main(object(), {"conversation_runtime_enabled": True})
        history = _event(f"before-{command}", "历史", user_id="a")
        plugin.observe_inbound_turn(history, now=0)
        key = conversation_key_from_event(history)
        command_event = _event(f"command-{command}", command, user_id="a")
        command_event["is_at_or_wake_command"] = True
        await plugin.on_message(command_event)
        assert plugin.conversation_ledger.history(key) == ()
        assert plugin.conversation_assembler.flush_ready(now=10) == ()


@pytest.mark.asyncio
async def test_cmdmask_reset_and_after_message_clean_marker_clear_runtime_state() -> None:
    plugin = Main(object(), {"conversation_runtime_enabled": True})
    history = _event("before-mask", "历史", user_id="a")
    plugin.observe_inbound_turn(history, now=0)
    key = conversation_key_from_event(history)
    masked = _event("masked-reset", "伪装内容", user_id="a")
    masked["is_at_or_wake_command"] = True
    masked["__astrbot_plugin_cmdmask:applied"] = True
    masked["__astrbot_plugin_cmdmask:target"] = "/reset"
    await plugin.on_message(masked)
    assert plugin.conversation_ledger.history(key) == ()

    plugin.observe_inbound_turn(history, now=1)
    marker = _event("after-marker", "", user_id="a")
    marker["_clean_group_context_session"] = True
    await plugin.after_message_sent(marker)
    assert plugin.conversation_ledger.history(key) == ()
