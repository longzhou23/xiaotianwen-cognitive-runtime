"""AstrBot-facing shell for the bounded conversation runtime.

The source-level ingress/request/response hooks are present for a reversible
canary, but all three return immediately unless the explicit runtime flag is
enabled. Installation alone therefore cannot alter a production response.
"""

from __future__ import annotations

from typing import Any

from astrbot import logger
from astrbot.api import star
from astrbot.api.event import filter
from astrbot.core.agent.message import TextPart

from .context import (
    ContextAssembler,
    ContextAssemblyPolicy,
    ContextAssemblyResult,
    ContextBridgeV1,
    SharedContextAdapter,
)
from .contracts import (
    ContextSection,
    ContractValidationError,
    ConversationKeyV1,
    TurnEnvelope,
)
from .conversation import ConversationLedgerV1, ConversationTurnAssemblerV1
from .ingress import (
    ShadowTurnCoordinator,
    event_to_envelope,
)
from .integration import (
    AstrBotObservationAdapter,
    ObservationAdapter,
    RuntimeObservationStore,
)


class Main(star.Star):
    """Dormant plugin shell; P1/P2 expose only in-memory local helpers."""

    def __init__(self, context: star.Context, config: Any | None = None) -> None:
        super().__init__(context)
        self._config = config
        self.shadow_enabled = self._cfg_bool("shadow_enabled", False)
        self.shared_context_enabled = self._cfg_bool("shared_context_enabled", False)
        self.conversation_ledger_enabled = self._cfg_bool("conversation_ledger_enabled", False)
        # Helper/ledger diagnostics and live AstrBot hook cutover are separate
        # controls.  The legacy helper flag must never activate live hooks.
        self.conversation_runtime_enabled = self._cfg_bool("conversation_runtime_enabled", False)
        self.observation_capture_text = self._cfg_bool("observation_capture_text", False)
        self.observation_retention_seconds = max(
            60.0,
            self._cfg_float("observation_retention_seconds", 86_400.0),
        )
        # This is an explicit adapter target for a future isolated test
        # instance.  It is intentionally not registered with AstrBot here:
        # merely installing the plugin must not observe or rewrite production
        # requests.
        self.observation_store = RuntimeObservationStore(
            "orchestrator-instance",
            retention_seconds=self.observation_retention_seconds,
        )
        self.observation_adapter = ObservationAdapter(
            self.observation_store,
            source="ORCHESTRATOR_ADAPTER",
        )
        self.astrbot_observation_adapter = AstrBotObservationAdapter(
            self.observation_adapter
        )
        self.coordinator = ShadowTurnCoordinator(
            enabled=self.shadow_enabled,
            quiet_window_seconds=max(0.1, self._cfg_float("quiet_window_seconds", 3.0)),
            dedup_ttl_seconds=max(1.0, self._cfg_float("dedup_ttl_seconds", 30.0)),
        )
        self.context_assembler = ContextAssembler(
            ContextAssemblyPolicy(
                total_budget_chars=max(0, self._cfg_int("context_budget_chars", 12_000))
            )
        )
        self.shared_context_adapter = SharedContextAdapter(
            enabled=self.shared_context_enabled
        )
        self.conversation_ledger = ConversationLedgerV1(
            max_conversations=max(1, self._cfg_int("conversation_max_conversations", 128)),
            max_turns_per_conversation=max(1, self._cfg_int("conversation_max_turns", 40)),
        )
        self.conversation_assembler = ConversationTurnAssemblerV1(
            quiet_window_seconds=max(0.1, self._cfg_float("quiet_window_seconds", 3.0)),
            max_conversations=max(1, self._cfg_int("conversation_max_conversations", 128)),
        )
        self.context_bridge = ContextBridgeV1(
            max_chars=max(1, self._cfg_int("conversation_history_budget_chars", 4_000))
        )
        # Host request identity for the current canonical user turn.  This is
        # request-local continuity state, not a second history store.
        self._request_turn_ids: dict[ConversationKeyV1, str] = {}

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self._config.get(key, default) if self._config is not None else default
        except Exception:
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        value = self._cfg(key, default)
        if type(value) is bool:
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _cfg_float(self, key: str, default: float) -> float:
        try:
            return float(self._cfg(key, default))
        except (TypeError, ValueError):
            return default

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self._cfg(key, default))
        except (TypeError, ValueError):
            return default

    async def initialize(self) -> None:
        logger.info(
            "[XiaotianwenOrchestrator] P1/P2 local shadow library loaded; "
            f"shadow_enabled={self.shadow_enabled}, "
            f"shared_context_enabled={self.shared_context_enabled}; "
            f"conversation_ledger_enabled={self.conversation_ledger_enabled}; "
            f"conversation_runtime_enabled={self.conversation_runtime_enabled}; "
            "explicit observation adapter is prepared; hooks remain gated by "
            "conversation_runtime_enabled and no tool/timer/delivery owner is active"
        )

    async def terminate(self) -> None:
        self.coordinator.disable()
        self.observation_store.clear()
        self.conversation_ledger.clear_all()
        self.conversation_assembler.clear_all()
        self._request_turn_ids.clear()

    @property
    def _helper_enabled(self) -> bool:
        return self.conversation_ledger_enabled or self.conversation_runtime_enabled

    def _append_finalized_turns(self, turns: tuple[TurnEnvelope, ...]) -> int:
        appended = 0
        for turn in turns:
            key = self._key_for_turn(turn)
            if self.conversation_ledger.append_user_turn(
                key,
                speaker_id=turn.sender_id,
                speaker_name=str(turn.metadata.get("sender_name") or turn.sender_id),
                content=turn.text,
                turn_id=turn.request_id,
                occurred_at=turn.received_at,
            ):
                appended += 1
        return appended

    def flush_conversation_turns(self, *, now: float | None = None) -> int:
        """Finalize quiet-window turns and put only finalized turns in the ledger."""

        if not self._helper_enabled:
            return 0
        return self._append_finalized_turns(self.conversation_assembler.flush_ready(now=now))

    @staticmethod
    def _key_for_turn(turn: TurnEnvelope) -> ConversationKeyV1:
        raw = turn.metadata.get("conversation_key")
        if not isinstance(raw, dict):
            raise ContractValidationError("TurnEnvelope is missing canonical conversation_key metadata")
        return ConversationKeyV1.from_dict(raw)

    def observe_inbound_turn(self, event: object, *, now: float | None = None) -> TurnEnvelope:
        """Normalize and optionally append one canonical user turn.

        This explicit method is also used by the registered hook when the
        runtime cutover flag is enabled; helper-only callers may use it without
        activating live AstrBot hooks.
        """

        turn = event_to_envelope(event, received_at=now)
        if self._helper_enabled:
            self._append_finalized_turns(self.conversation_assembler.ingest(turn, now=now))
        return turn

    def record_logical_response(
        self,
        key: ConversationKeyV1,
        *,
        content: str,
        logical_response_id: str,
        occurred_at: float,
    ) -> bool:
        """Append exactly one assistant turn for one logical response."""

        if not self._helper_enabled:
            return False
        return self.conversation_ledger.append_assistant_turn(
            key,
            content=content,
            logical_response_id=logical_response_id,
            occurred_at=occurred_at,
        )

    def compose_conversation_context(
        self,
        turn: TurnEnvelope,
        *,
        approved_sections: tuple[ContextSection, ...] = (),
        current_turn_id: str | None = None,
    ) -> ContextAssemblyResult:
        """Assemble one request-scoped context result with owned history."""

        if not isinstance(turn, TurnEnvelope):
            raise ContractValidationError("compose_conversation_context requires TurnEnvelope")
        self.flush_conversation_turns(now=turn.received_at)
        key = self._key_for_turn(turn)
        history = self.context_bridge.section(
            key,
            self.conversation_ledger,
            current_turn_id=current_turn_id or turn.request_id,
        )
        sections = (history, *approved_sections) if history is not None else approved_sections
        return self.context_assembler.assemble(sections, route=turn.route)

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def on_message(self, event: object, *args: Any, **kwargs: Any) -> None:
        """Default-off ingress hook for the canonical conversation runtime."""

        del args, kwargs
        if not self.conversation_runtime_enabled:
            return
        if self._event_has_clean_marker(event) or self._event_reset_command(event):
            turn = event_to_envelope(event)
            self.reset_conversation(self._key_for_turn(turn))
            return
        # Publish ownership before lower-priority legacy context hooks run.
        # The marker is request metadata only; it carries no content or
        # authority and lets ContextAware stay limited to image handling.
        self._set_event_extra(event, self.CONVERSATION_RUNTIME_OWNER, True)
        self.observe_inbound_turn(event)

    @filter.after_message_sent()
    async def after_message_sent(self, event: object) -> None:
        """Observe Host clean markers without creating a reset command."""

        if not self.conversation_runtime_enabled or not self._event_has_clean_marker(event):
            return
        try:
            turn = event_to_envelope(event)
            self.reset_conversation(self._key_for_turn(turn))
        except ContractValidationError:
            # Reset is best-effort for malformed/unsupported external events;
            # never invent an identity or mutate another conversation.
            return

    @filter.on_llm_request(priority=-5)
    async def on_llm_request(self, event: object, req: Any) -> None:
        """Inject the single owned conversation-history section when enabled."""

        if not self.conversation_runtime_enabled:
            return
        turn = event_to_envelope(event)
        key = self._key_for_turn(turn)
        finalized = self.conversation_assembler.finalize_for_request(key)
        if finalized is not None:
            self._append_finalized_turns((finalized,))
            self._request_turn_ids[key] = finalized.request_id
        current_turn_id = self._request_turn_ids.get(key)
        result = self.compose_conversation_context(turn, current_turn_id=current_turn_id)
        self._set_event_extra(event, self.CONVERSATION_RUNTIME_OWNER, True)
        if not result.payload:
            return
        marker = "<!-- xiaotianwen_conversation_history_v1 -->"
        extra_parts = getattr(req, "extra_user_content_parts", None)
        if isinstance(extra_parts, list):
            if any(marker in str(getattr(part, "text", "")) for part in extra_parts):
                return
            part = TextPart(text=f"{marker}\n{result.payload}")
            mark_as_temp = getattr(part, "mark_as_temp", None)
            if callable(mark_as_temp):
                part = mark_as_temp() or part
            extra_parts.append(part)
            return
        current_prompt = getattr(req, "system_prompt", "") or ""
        if marker not in current_prompt:
            req.system_prompt = f"{current_prompt}\n\n{marker}\n{result.payload}"

    @filter.on_llm_response()
    async def on_llm_response(self, event: object, resp: Any) -> None:
        """Record one assistant turn per logical response, never per send."""

        if not self.conversation_runtime_enabled:
            return
        turn = event_to_envelope(event)
        key = self._key_for_turn(turn)
        content = getattr(resp, "completion_text", None)
        if not isinstance(content, str) or not content.strip():
            self._request_turn_ids.pop(key, None)
            return
        # Defensive boundary: a Host may emit a response hook without a
        # request hook in a custom runtime.  Finalize any still-pending user
        # turn before publishing the logical assistant turn.
        finalized = self.conversation_assembler.finalize_for_request(key)
        if finalized is not None:
            self._append_finalized_turns((finalized,))
        self.record_logical_response(
            key,
            content=content,
            logical_response_id=f"response:{turn.request_id}",
            occurred_at=turn.received_at,
        )
        self._request_turn_ids.pop(key, None)

    def reset_conversation(self, key: ConversationKeyV1) -> bool:
        """Clear short-term continuity while preserving canonical identity."""

        if not isinstance(key, ConversationKeyV1):
            raise ContractValidationError("reset_conversation requires ConversationKeyV1")
        self.conversation_assembler.clear(key)
        self._request_turn_ids.pop(key, None)
        return self.conversation_ledger.clear(key)

    CONVERSATION_RUNTIME_OWNER = "_xiaotianwen_conversation_runtime_owner_v1"

    @staticmethod
    def _event_extra(event: object, key: str, default: Any = None) -> Any:
        if isinstance(event, dict):
            return event.get(key, default)
        getter = getattr(event, "get_extra", None)
        if callable(getter):
            try:
                return getter(key, default)
            except Exception:
                return default
        return default

    @staticmethod
    def _set_event_extra(event: object, key: str, value: Any) -> None:
        if isinstance(event, dict):
            event[key] = value
            return
        setter = getattr(event, "set_extra", None)
        if callable(setter):
            try:
                setter(key, value)
            except Exception:
                return

    @classmethod
    def _event_has_clean_marker(cls, event: object) -> bool:
        return any(
            bool(cls._event_extra(event, name, False))
            for name in ("_clean_group_context_session", "_clean_ltm_session")
        )

    @classmethod
    def _event_reset_command(cls, event: object) -> str:
        is_command = bool(cls._event_extra(event, "is_at_or_wake_command", False))
        if not is_command:
            return ""
        applied = bool(cls._event_extra(event, "__astrbot_plugin_cmdmask:applied", False))
        target = cls._event_extra(event, "__astrbot_plugin_cmdmask:target", "") if applied else ""
        raw = target or cls._event_extra(event, "raw_message", "")
        if not raw and not isinstance(event, dict):
            getter = getattr(event, "get_message_str", None)
            if callable(getter):
                try:
                    raw = getter()
                except Exception:
                    raw = ""
        if not isinstance(raw, str):
            return ""
        tokens = raw.split(maxsplit=1)
        token = tokens[0] if tokens else ""
        command = token.lstrip("/.!！。#").casefold()
        return command if command in {"reset", "new"} else ""
