"""Administrator commands for the bounded response-expression experiment."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from iris_memory.core import get_component_manager, get_logger
from iris_memory.profile.response_preferences import (
    APPROVED,
    PENDING,
    REVOKED,
    SUPERSEDED,
    SUSPENDED,
    ResponsePreferenceRecord,
)
from iris_memory.profile.storage import ProfileStorage

from .base import CommandHandler, CommandResult, ParsedArgs

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent


logger = get_logger("commands.response_preference")

_STATUS_LABELS = {
    PENDING: "待人工核实",
    APPROVED: "已批准",
    REVOKED: "已撤销",
    SUSPENDED: "因冲突暂停",
    SUPERSEDED: "已有同值偏好，未延期",
    "EXPIRED": "已过期",
}


def _actor_id(event: AstrMessageEvent) -> str:
    for method_name in ("get_sender_id", "get_self_id"):
        method = getattr(event, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:  # noqa: BLE001 - event accessors are a fail-closed boundary
                value = None
            if type(value) in (str, int) and str(value).strip():
                return str(value).strip()
    # The command itself is protected by AstrBot's ADMIN decorator.  The
    # fallback is only a label; it is never used as an authorization check.
    return "maintainer-command"


def _candidate_arg(args: ParsedArgs) -> str:
    # ParsedArgs.raw_args retains [sub_command, ...] after CommandParser.parse.
    return args.raw_args[1].strip() if len(args.raw_args) > 1 else ""


def _render_record(record: ResponsePreferenceRecord, now: float) -> str:
    scope = record.scope
    source = record.source
    status = record.display_status(now)
    expiry = "—" if record.expires_at is None else str(int(record.expires_at))
    if status == "EXPIRED":
        reason = "reason=approval_ttl_elapsed"
    elif status == SUSPENDED:
        reason = f"reason={record.suspended_reason}"
    elif status == SUPERSEDED:
        reason = "reason=active_same_value"
    elif status == REVOKED:
        reason = f"reason=revoked_by:{record.revoked_by}"
    else:
        reason = "reason=awaiting_manual_approval" if status == PENDING else "reason=approved_by_manual_review"
    return (
        f"{record.candidate_id} | {_STATUS_LABELS.get(status, status)} | "
        f"{record.parameter}={record.value} | platform={scope.platform_id} account={scope.account_id} "
        f"user={scope.user_id} conversation={scope.conversation_id} | "
        f"source={source.source_kind}:{source.source_event_id} | expires_at={expiry} | {reason}"
    )


class ResponsePreferenceCommandHandler(CommandHandler):
    """The admin-only ``iris_mem preference`` command family."""

    @property
    def name(self) -> str:
        return "preference"

    @property
    def description(self) -> str:
        return "受控回复/工具偏好（人工批准、7天、回复或工具参数按 scope 隔离）"

    @property
    def sub_commands(self) -> dict[str, str]:
        return {
            "pending": "查看待人工核实的候选",
            "status": "查看全部候选及有效/过期/撤销状态",
            "consolidate_length": "把已达 L09 门槛的 review-only 聚合转为待核实候选",
            "feedback_status": "查看精确反馈观察 ID 和生命周期，不显示消息正文",
            "feedback_revoke <observation_id>": "撤销一条精确反馈观察，不直接撤销已批准偏好",
            "feedback_conflict <observation_id>": "将一条精确反馈观察标为冲突，停止参与后续巩固",
            "approve <candidate_id>": "批准一个已核实来源（不自动续期）",
            "revoke <candidate_id>": "撤销一个候选或已批准记录",
            "p2b_status": "查看 P2b shadow 候选（管理员审计视图）",
            "p2b_evaluate": "立即执行一次影子评估；不批准、不发布",
            "p2b_approve <candidate_id>": "批准 shadow 候选；仍不发布到回复偏好",
            "p2b_reject <candidate_id>": "拒绝 shadow 候选",
            "p2b_revoke <candidate_id>": "撤销未发布的 shadow 候选",
            "p2b_inspect <candidate_id>": "发布前检查权威候选与当前证据，不显示 scope 明细",
            "p2b_publish <candidate_id> CONFIRM": "显式发布已批准且仍有效的 SHORT 候选",
            "p2b_unpublish <candidate_id> CONFIRM": "撤回该候选发布的回复偏好",
        }

    def _storage(self) -> ProfileStorage | None:
        try:
            manager = get_component_manager()
        except RuntimeError:
            return None
        if not manager:
            return None
        storage = manager.get_component("profile", ProfileStorage)
        return storage if storage and storage.is_available else None

    async def handle(
        self,
        event: AstrMessageEvent,
        args: ParsedArgs,
        sub_command: str | None = None,
    ) -> CommandResult:
        if sub_command and sub_command.startswith("p2b_"):
            return await self._p2b_operation(event, sub_command, args)
        storage = self._storage()
        if storage is None:
            return CommandResult(False, "回复表达偏好存储不可用（需要启用 profile）")

        if sub_command in (None, "pending"):
            return await self._list(storage, PENDING)
        if sub_command == "status":
            return await self._list(storage, None)
        if sub_command == "consolidate_length":
            return await self._consolidate_length(storage)
        if sub_command in {"feedback_status", "feedback_revoke", "feedback_conflict"}:
            return self._feedback_operation(sub_command, args)
        if sub_command == "approve":
            candidate_id = _candidate_arg(args)
            if not candidate_id:
                return CommandResult(False, "用法: iris_mem preference approve <candidate_id>")
            result = await storage.approve_response_preference(
                candidate_id, _actor_id(event)
            )
            if result.success:
                return CommandResult(True, f"✅ 已批准 {candidate_id}，有效 7 天且不自动续期")
            if result.code == "active_duplicate":
                return CommandResult(
                    True,
                    f"ℹ️ {candidate_id} 与当前有效值相同，已标记为已处理，未延期",
                )
            return CommandResult(False, self._operation_error(result.code, candidate_id))
        if sub_command == "revoke":
            candidate_id = _candidate_arg(args)
            if not candidate_id:
                return CommandResult(False, "用法: iris_mem preference revoke <candidate_id>")
            result = await storage.revoke_response_preference(
                candidate_id, _actor_id(event)
            )
            if result.success:
                return CommandResult(True, f"✅ 已撤销 {candidate_id}，后续请求恢复默认表达")
            return CommandResult(False, self._operation_error(result.code, candidate_id))
        if sub_command == "help":
            return CommandResult(True, self.get_help_text())
        return CommandResult(False, f"未知的子指令: {sub_command}\n{self.get_help_text()}")

    async def _p2b_operation(
        self, event: AstrMessageEvent, operation: str, args: ParsedArgs
    ) -> CommandResult:
        from iris_memory.cognitive.iris_adapter import get_cognitive_runtime

        runtime = get_cognitive_runtime()
        store = getattr(runtime, "observatory_p2b_shadow_store", None)
        if store is None or not getattr(store, "available", False):
            return CommandResult(False, "P2b shadow candidate journal 不可用；未执行操作")
        try:
            if operation == "p2b_evaluate":
                evaluate = getattr(runtime, "p2b_shadow_evaluate", None)
                if not callable(evaluate):
                    return CommandResult(False, "P2b shadow evaluator 未接入")
                created = int(evaluate())
                return CommandResult(True, f"✅ 影子评估完成，新增 {created} 个 PENDING 候选；自动批准和发布均关闭")
            if operation == "p2b_status":
                items = store.all_candidates()
                lines = ["P2b Shadow Candidates（permission effect=NONE；批准不等于发布）"]
                lines.extend(
                    f"{item.candidate_id} | {item.status.value} | {item.parameter.value}={item.proposed_value} | evidence={len(item.evidence)} | expires_at={item.expires_at.isoformat() if item.expires_at else '—'}"
                    for item in items
                )
                return CommandResult(True, "\n".join(lines if items else lines + ["（无候选）"]))
            candidate_id = _candidate_arg(args)
            if not candidate_id:
                return CommandResult(False, f"用法: iris_mem preference {operation} <candidate_id>")
            store.expire_due()
            candidate = store.get(candidate_id)
            if candidate is None:
                return CommandResult(False, "P2b 候选不存在；请从 p2b_status 复制完整 ID")
            validate = getattr(runtime, "p2b_shadow_validate", None)
            if operation == "p2b_inspect":
                current = bool(callable(validate) and validate(candidate_id))
                return CommandResult(
                    True,
                    f"{candidate.candidate_id} | {candidate.status.value} | "
                    f"{candidate.parameter.value}={candidate.proposed_value} | "
                    f"evidence={len(candidate.evidence)} | current_evidence={'VALID' if current else 'INVALID'} | "
                    "permission_effect=NONE",
                )
            if operation in {"p2b_publish", "p2b_unpublish"}:
                if len(args.raw_args) != 3 or args.raw_args[2] != "CONFIRM":
                    return CommandResult(
                        False,
                        f"用法: iris_mem preference {operation} <candidate_id> CONFIRM",
                    )
                storage = self._storage()
                if storage is None:
                    return CommandResult(False, "回复表达偏好存储不可用（需要启用 profile）")
                actor = _actor_id(event)
                if operation == "p2b_publish":
                    if not callable(validate) or not validate(candidate_id):
                        return CommandResult(False, "候选的当前精确证据链无效；零写入")
                    result = await storage.publish_p2b_candidate(candidate, actor)
                    messages = {
                        "published": f"✅ 已显式发布 {candidate_id}；仅影响对应私聊 scope，7 天后过期",
                        "already_published": f"ℹ️ {candidate_id} 已有确定的发布记录，没有重复写入或延期",
                        "not_approved": "候选尚未批准；请先执行 p2b_approve，零写入",
                        "expired": "候选已经过期；零写入",
                        "unsupported": "候选参数不在显式发布白名单内；零写入",
                        "conflict": "对应 scope 已有冲突偏好；零写入",
                        "committed_unverified": "发布可能已经提交，但读回验证失败；请先用 status 检查，禁止直接重试",
                        "storage_failed": "发布存储失败，未确认生效",
                    }
                else:
                    result = await storage.unpublish_p2b_candidate(candidate, actor)
                    messages = {
                        "unpublished": f"✅ 已撤回 {candidate_id} 发布的回复偏好；后续请求恢复默认表达",
                        "already_unpublished": f"ℹ️ {candidate_id} 的发布记录已撤回，没有重复写入",
                        "not_found": "未找到该候选的确定发布记录；零写入",
                        "conflict": "发布记录状态冲突；零写入",
                        "unsupported": "该候选没有可撤回的显式发布映射；零写入",
                        "committed_unverified": "撤回可能已经提交，但读回验证失败；请先用 status 检查，禁止直接重试",
                        "storage_failed": "撤回存储失败，未确认生效",
                    }
                return CommandResult(result.success, messages.get(result.code, f"操作失败（{result.code}）"))
            actor = _actor_id(event)
            if operation == "p2b_approve":
                item = store.approve(candidate_id, actor=actor)
            elif operation == "p2b_reject":
                item = store.reject(candidate_id, actor=actor)
            elif operation == "p2b_revoke":
                storage = self._storage()
                if storage is not None and await storage.find_p2b_publication(candidate) is not None:
                    return CommandResult(
                        False,
                        f"{candidate_id} 已有发布记录；请先执行 p2b_unpublish {candidate_id} CONFIRM",
                    )
                item = store.revoke(candidate_id, actor=actor)
            else:
                return CommandResult(False, f"未知的 P2b 子指令: {operation}")
            return CommandResult(
                True,
                f"✅ {item.candidate_id} → {item.status.value}；未发布到 ProfileStorage，不影响当前回复",
            )
        except Exception as exc:  # noqa: BLE001 - admin boundary must fail closed
            logger.warning("P2b shadow 管理操作失败：%s", exc)
            return CommandResult(False, "P2b shadow 操作失败；未回报成功，也未发布偏好")

    def _feedback_operation(self, operation: str, args: ParsedArgs) -> CommandResult:
        from iris_memory.cognitive.response_preference_feedback import (
            FEEDBACK_EVIDENCE_CONFLICTED,
            FEEDBACK_EVIDENCE_REVOKED,
        )

        try:
            from iris_memory.cognitive.iris_adapter import get_cognitive_runtime

            observer = getattr(get_cognitive_runtime(), "response_length_feedback_observer", None)
            if observer is None:
                return CommandResult(False, "反馈观察器未接入")
            observer.refresh_archives()
            if not observer.available:
                return CommandResult(False, "反馈日志或权威 archive 不可用，未执行操作")
            items = observer.observations
            if operation == "feedback_status":
                lines = ["精确反馈观察（无正文；撤销观察不等于撤销已批准偏好）"]
                for item in items:
                    lines.append(
                        f"{observer.observation_id(item)} | {item.evidence_state} | "
                        f"{item.occurred_at.isoformat()} | "
                        f"platform={item.scope.platform_id} account={item.scope.account_id} "
                        f"user={item.scope.user_id} conversation={item.scope.conversation_id}"
                    )
                return CommandResult(True, "\n".join(lines) if items else "当前没有已完成精确归档的反馈观察")
            target_id = _candidate_arg(args)
            if len(args.raw_args) != 2:
                return CommandResult(False, f"用法: iris_mem preference {operation} <observation_id>")
            matches = [item for item in items if observer.observation_id(item) == target_id]
            if len(matches) != 1:
                return CommandResult(False, "精确观察 ID 不存在或不唯一，未修改")
            state = (FEEDBACK_EVIDENCE_REVOKED if operation == "feedback_revoke"
                     else FEEDBACK_EVIDENCE_CONFLICTED)
            if not observer.invalidate_observation(matches[0], state):
                return CommandResult(False, "观察状态未确认写入；请检查日志后重读，未回报成功")
            states = {item.evidence_state for item in observer.observations
                      if observer.observation_id(item) == target_id}
            if len(states) != 1 or not observer.available:
                return CommandResult(False, "观察状态读回未确认，未回报成功")
            return CommandResult(True, f"观察状态已读回：{next(iter(states))}；已有偏好仍需使用 revoke 单独撤销")
        except Exception:  # noqa: BLE001 - no raw observation payload in command errors
            logger.warning("反馈观察管理失败，未回报成功")
            return CommandResult(False, "反馈观察管理失败，未回报成功")

    async def _consolidate_length(self, storage: ProfileStorage) -> CommandResult:
        try:
            from iris_memory.cognitive.iris_adapter import get_cognitive_runtime

            observer = getattr(
                get_cognitive_runtime(),
                "response_length_feedback_observer",
                None,
            )
        except Exception:
            observer = None
        if observer is None or not callable(getattr(observer, "consolidate_eligible", None)):
            return CommandResult(False, "❌ L09 review-only 观察器不可用，未创建候选")
        try:
            results = await observer.consolidate_eligible(storage)
        except Exception as exc:  # noqa: BLE001 - command boundary fails closed
            logger.warning("巩固 L09 回复长度聚合失败：%s", exc)
            return CommandResult(False, "❌ L09 聚合巩固失败，未回报成功")
        pending = [
            result.record.candidate_id
            for result in results
            if getattr(result, "code", None) == "pending"
            and getattr(result, "record", None) is not None
        ]
        duplicates = sum(
            1 for result in results if getattr(result, "code", None) in {"duplicate", "active_duplicate"}
        )
        failures = [result for result in results if not getattr(result, "success", False)]
        if failures:
            return CommandResult(False, f"❌ L09 聚合巩固未完全成功（失败 {len(failures)} 条，未自动批准）")
        if not results:
            return CommandResult(True, "✅ 当前没有达到门槛的 L09 review-only 聚合，未创建候选")
        if pending:
            return CommandResult(
                True,
                "✅ 已创建待人工核实候选：" + ", ".join(pending) + "；请用 pending/status 查看，批准后才会影响请求",
                {"pending": len(pending), "duplicates": duplicates},
            )
        return CommandResult(
            True,
            f"ℹ️ L09 聚合已处理（重复或已有有效候选 {duplicates} 条），未自动批准",
            {"pending": 0, "duplicates": duplicates},
        )

    async def _list(
        self, storage: ProfileStorage, status: str | None
    ) -> CommandResult:
        try:
            records = await storage.list_response_preferences(status=status)
        except Exception as exc:  # noqa: BLE001 - command storage must fail closed
            logger.warning("列出回复表达偏好失败：%s", exc)
            return CommandResult(False, "❌ 回复表达偏好存储读取失败，未执行任何操作")
        now = time.time()
        title = "待人工核实候选" if status == PENDING else "回复表达偏好状态"
        lines = [
            f"📌 {title}（仅一处私聊；批准后 7 天；不自动续期；可恢复默认）",
        ]
        if not records:
            lines.append("（无记录）")
        else:
            lines.extend(_render_record(record, now) for record in records)
        return CommandResult(True, "\n".join(lines), {"count": len(records)})

    @staticmethod
    def _operation_error(code: str, candidate_id: str) -> str:
        messages = {
            "not_found": f"❌ 未找到候选 {candidate_id}；请先用 pending/status 查看系统生成的 ID",
            "already_processed": f"ℹ️ {candidate_id} 已处理，不能重复批准或延期",
            "already_revoked": f"ℹ️ {candidate_id} 已撤销，不能恢复旧状态",
            "invalid_candidate": "❌ candidate_id 必须是系统生成的 rspref:... ID",
            "write_failed": "❌ 持久化失败，未回报操作成功；请检查存储后重试",
            "unavailable": "❌ 回复表达偏好存储不可用",
        }
        return messages.get(code, f"❌ 操作失败（{code}）")
