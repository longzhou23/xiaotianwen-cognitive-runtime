"""Read-only projection of the frozen P1 cognitive-review foundation.

This service is deliberately not a second cognitive authority.  It reads the
public EpisodeStore/ReviewStore APIs, and its preview path uses a fresh
InMemoryReviewStore for each request.  No route may use this service to append
Episode, Outcome, Review, Iris, or behavioural state.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import math
import re
import time
from typing import Any, Mapping

from iris_memory.cognitive.contracts import (
    BehaviorExecutionRecord, BehaviorTrace, DivergenceType, GroundingEnforcement,
    HostResult, OutputProducer, OutputState, ShadowComparison, TraceStage,
    TriggerDecision,
)
from iris_memory.cognitive.episode import Episode, EpisodeEventKind, EpisodeEventRef, EpisodeState
from iris_memory.cognitive.episode_store import EpisodeStore
from iris_memory.cognitive.execution_observatory import ExecutionRecordObservatory
from iris_memory.cognitive.outcome import OutcomeExplicitness, OutcomeKind, OutcomeObservation
from iris_memory.cognitive.review import EvidenceSourceType, ReviewRun
from iris_memory.cognitive.review_service import (
    ReviewInputSnapshot, compute_input_snapshot_hash, evaluate_review_eligibility, review_episode,
)
from iris_memory.cognitive.review_store import InMemoryReviewStore, ReviewStore


def _json_value(value: Any) -> Any:
    """Convert frozen contracts to safe JSON without retaining live objects."""
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        # ``asdict`` deep-copies MappingProxyType fields used by frozen cognitive
        # contracts and therefore raises.  Read declared fields directly instead.
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    # The service never serializes arbitrary supplied facts.  This final branch
    # only protects the management response if a future public contract grows.
    return {"unavailable_type": type(value).__name__}


def _timestamp(value: datetime | None) -> str | None:
    return _json_value(value) if value else None


_RUNTIME_DETAIL_SCHEMA = "iris.observatory-runtime-detail.v1"
_ADMIN_IDENTITY_SCHEMA = "iris.observatory-admin-identity.v1"
_ADMIN_EPISODE_SCHEMA = "iris.observatory-admin-episode.v1"
_ADMIN_OUTCOME_SCHEMA = "iris.observatory-admin-outcome.v1"
_ADMIN_CONTENT_LIMIT = 240
_ADMIN_PAGE_LIMIT = 200
_ADMIN_STRING_LIMIT = 512
_ADMIN_TRUNCATION_MARKER = "...[TRUNCATED]"
_SENSITIVE_NAME_MARKERS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "cookie",
    "authorization",
    "private_key",
    "privatekey",
    "bearer",
    "credential",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9])(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])(?:AIza|gh[pousr]_)[A-Za-z0-9_-]{16,}(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])(?:xox[baprs]-|glpat-|npm_|hf_|pypi-)[A-Za-z0-9._-]{16,}(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"\bcookie\s*[:=]\s*[^\s;]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:cookie\s*[:=]\s*)?(?:session(?:id)?|sid|phpsessid|connect\.sid|auth(?:entication)?|refresh_token)\s*=\s*[^\s;]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:secret|token|password|api[_ -]?key|authorization|credential)\s*[:=]\s*[^\s,;]{8,}", re.IGNORECASE),
)
_SAFE_AFFECT_NUMERIC_FIELDS = {
    "affection": 100.0,
    "current_libido_other": 50.0,
    "current_aggression_other": 50.0,
    "current_libido_self": 50.0,
    "current_aggression_self": 50.0,
}
_SAFE_AFFECT_LABEL_FIELDS = {"towards_user", "self_state"}
_SAFE_PREFERENCE_PARAMETERS = {
    "response_expansion",
    "response_length",
    "tool_memory_retrieval",
    "relationship_familiarity",
}

_PLATFORM_LABELS = {
    "qq": "QQ",
    "wechat": "微信",
    "wecom": "企业微信",
    "telegram": "Telegram",
    "discord": "Discord",
    "feishu": "飞书",
    "dingtalk": "钉钉",
    "webui": "网页管理台",
}
_IDENTITY_STATUS_LABELS = {
    "CONFIRMED": "已确认",
    "POSSIBLE": "待确认",
    "REVOKED": "已撤销",
    "REJECTED": "冲突",
}
_EPISODE_STATE_LABELS = {
    "OPEN": "进行中",
    "SOFT_CLOSED": "暂时结束，等待后续互动",
    "FINALIZED": "已结束并封存",
    "INTERRUPTED": "运行中断",
}
_EVENT_HUMAN_LABELS = {
    "EXPERIENCE": ("用户发来消息", "系统记录了这次用户互动。"),
    "COGNITIVE_PROPOSAL": ("小天文形成判断", "系统记录了小天文当时形成的判断。"),
    "NO_INTENT": ("小天文形成判断", "系统记录了小天文判断当前无需主动发言。"),
    "HOST_OUTPUT": ("生成回复", "系统记录了实际生成的回复。"),
    "DISPATCH": ("成功发送", "系统记录了回复已交给发送链路。"),
    "DELIVERY": ("成功发送", "系统记录了回复已送达发送链路。"),
    "TOOL_RESULT": ("工具返回结果", "系统记录了工具结果。"),
    "INTENTIONAL_SILENCE": ("小天文保持安静", "系统记录了这次有意保持安静。"),
    "TRIGGER_NO": ("没有触发回复", "系统记录了这次互动没有触发回复。"),
    "GUARD_BLOCKED": ("回复被安全规则拦截", "系统记录了安全规则阻止了后续回复。"),
}
_OUTCOME_HUMAN_LABELS = {
    "EXPLICIT_ACKNOWLEDGEMENT": "用户明确确认或回应了此前的回复",
    "EXPLICIT_CORRECTION": "用户明确纠正了此前的回复",
    "EXPLICIT_STOP_REQUEST": "用户明确要求停止当前互动",
    "FOLLOWUP_QUESTION": "用户继续提出了问题",
    "ANSWER_OBSERVED": "系统观察到回答已经产生",
    "REACTION_OBSERVED": "系统观察到后续回应",
    "REPLY_OBSERVED": "系统观察到后续回复",
    "MENTION_OBSERVED": "系统观察到一次提及",
    "CONVERSATION_CONTINUED": "系统观察到互动继续",
    "TOOL_RESULT_RECEIVED": "系统收到工具结果",
    "TOOL_SUCCEEDED": "系统观察到工具执行成功",
    "TOOL_FAILED": "系统观察到工具执行失败",
    "DISPATCH_OBSERVED": "系统观察到回复进入发送链路",
    "DELIVERY_FAILED": "系统观察到回复发送失败",
    "OBSERVATION_WINDOW_ELAPSED": "观察窗口结束",
}
_EXPLICITNESS_HUMAN_LABELS = {
    "EXPLICIT": "是，用户直接表达",
    "STRUCTURAL": "否，这是系统结构记录",
    "ABSENCE": "否，这是根据观察窗口未发生的事实记录",
}


def _enum_value(value: object) -> str:
    """Read a known enum value without guessing future or malformed values."""
    raw = getattr(value, "value", None)
    return raw if isinstance(raw, str) and raw else "UNKNOWN"


def _safe_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list, frozenset, set)):
        return tuple(value)
    return ()


def _platform_label(platform: object) -> str:
    if not isinstance(platform, str) or not platform.strip():
        return "未知平台"
    normalized = platform.strip().casefold()
    return _PLATFORM_LABELS.get(normalized, platform.strip())


def _opaque_ref(value: object, prefix: str = "ref") -> str:
    """Return a stable short reference without exposing the supplied value."""
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()
    return f"{prefix}#{digest[:10]}"


def _safe_count(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _admin_sensitive_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _SENSITIVE_NAME_MARKERS)


def _admin_sensitive_value(value: str) -> bool:
    marker_word = re.search(
        r"(?<![A-Za-z0-9_-])(?:secret|token|password|api[_ -]?key|cookie|authorization|private[ _-]?key|bearer|credential)(?![A-Za-z0-9_-])",
        value,
        re.IGNORECASE,
    )
    return bool(marker_word or any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS))


def _admin_bounded_string(value: str) -> str:
    if len(value) <= _ADMIN_STRING_LIMIT:
        return value
    keep = _ADMIN_STRING_LIMIT - len(_ADMIN_TRUNCATION_MARKER)
    return value[:keep] + _ADMIN_TRUNCATION_MARKER


def _admin_redact(value: object, *, _key: str | None = None, _depth: int = 0) -> Any:
    """Return a detached admin projection with recursive secret redaction.

    Admin record views may expose IDs, aliases, scopes, and evidence refs, but
    a malformed/future contract must not make arbitrary values or repr output
    reachable from the Web API.  Redaction is intentionally applied after the
    existing contract-only JSON conversion so unknown objects remain an
    ``unavailable_type`` marker rather than an object representation.
    """
    if _depth > 12:
        return "[REDACTED_DEPTH_LIMIT]"
    if _key is not None and _admin_sensitive_name(_key):
        return "[REDACTED]"
    if isinstance(value, str):
        return "[REDACTED]" if _admin_sensitive_value(value) else _admin_bounded_string(value)
    if isinstance(value, Mapping):
        return {
            str(key): _admin_redact(item, _key=str(key), _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_admin_redact(item, _depth=_depth + 1) for item in value]
    return value


def _admin_json(value: object) -> Any:
    return _admin_redact(_json_value(value))


def _admin_page(limit: object, offset: object) -> tuple[int, int]:
    try:
        bounded_limit = min(max(int(limit), 1), _ADMIN_PAGE_LIMIT)
        bounded_offset = max(int(offset), 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid pagination") from exc
    return bounded_limit, bounded_offset


def _admin_content_snapshot(value: object) -> dict[str, Any]:
    """Project only the persisted Episode.topic_hint content carrier."""
    if value is None:
        return {"status": "EMPTY", "text": None, "truncated": False}
    if not isinstance(value, str):
        return {"status": "CORRUPTED", "text": None, "truncated": False}
    truncated = len(value) > _ADMIN_CONTENT_LIMIT
    clipped = value[:_ADMIN_CONTENT_LIMIT]
    return {
        "status": "AVAILABLE" if clipped else "EMPTY",
        "text": _admin_redact(clipped),
        "truncated": truncated,
    }


class P1ObservatoryService:
    """Thin read model and non-persistent preview runner for the P1 UI."""

    PROMOTION_REASON = (
        "Promotion 当前未接入有效的 production composition；观测台保持只读、fail-closed。"
    )

    def __init__(
        self,
        episode_store: EpisodeStore | None = None,
        review_store: ReviewStore | None = None,
        execution_records: Mapping[str, BehaviorExecutionRecord] | None = None,
        execution_observatory: ExecutionRecordObservatory | None = None,
        p2r0_store: Any | None = None,
        runtime_state: Mapping[str, Any] | None = None,
        interaction_trace_reader: Any | None = None,
    ) -> None:
        self._episode_store = episode_store
        self._review_store = review_store
        self._p2r0_store = p2r0_store
        self._runtime_state = dict(runtime_state or {})
        # A caller may inject immutable records for tests/demo integration.  The
        # production runtime currently does not expose this source, so absent
        # records are reported as unavailable rather than reconstructed.
        self._execution_records = dict(execution_records or {})
        self._execution_observatory = execution_observatory
        self._interaction_trace_reader = interaction_trace_reader

    @property
    def available(self) -> bool:
        return self._episode_store is not None

    def summary(self) -> dict[str, Any]:
        if self._episode_store is None:
            return self._unavailable_summary()
        episodes = self._episode_store.all_episodes()
        outcomes = self._episode_store.get_outcomes()
        runs: list[ReviewRun] = []
        evidence_count = 0
        review_data_available = self._review_store is not None
        review_error: str | None = None
        if self._review_store is not None:
            try:
                for episode in episodes:
                    runs.extend(self._review_store.list_review_runs_for_episode(episode.episode_id))
                    evidence_count += len(self._review_store.list_evidence_for_episode(episode.episode_id))
            except Exception:
                review_data_available = False
                review_error = "review_store_unavailable"
        promotion_enabled = self._state_bool("promotion_enabled")
        lifecycle_enabled = self._state_bool("lifecycle_enabled")
        review_enabled = self._state_bool("review_enabled")
        rules = self._state_rules()
        phase = "P2l.1" if lifecycle_enabled else "P2r.1" if promotion_enabled else "P1"
        review_status = (
            "UNAVAILABLE"
            if not review_data_available
            else "ENABLED"
            if review_enabled
            else "DISABLED"
        )
        review_runs_value: int | str = len(runs) if review_data_available else "Unavailable"
        findings_value: int | str = sum(len(run.findings) for run in runs) if review_data_available else "Unavailable"
        evidence_value: int | str = evidence_count if review_data_available else "Unavailable"
        interaction_trace = self._interaction_trace_projection()
        p2b_shadow = self._p2b_shadow_projection()
        return {
            "available": True,
            "phase": phase,
            "episodes": len(episodes),
            "finalized_episodes": sum(e.state is EpisodeState.FINALIZED for e in episodes),
            "outcomes": len(outcomes),
            "review_runs": review_runs_value,
            "review_findings": findings_value,
            "review_evidence": evidence_value,
            "review_store": "AVAILABLE" if review_data_available else "UNAVAILABLE",
            "review_store_error": review_error,
            "review_run_count_source": (
                "runtime_owned_persisted_review_store" if review_data_available else "Unavailable"
            ),
            "finding_count_source": (
                "runtime_owned_persisted_review_store" if review_data_available else "Unavailable"
            ),
            "evidence_count_source": (
                "runtime_owned_persisted_review_store" if review_data_available else "Unavailable"
            ),
            "review_status_counts": (
                {status.value: sum(run.status is status for run in runs) for status in {run.status for run in runs}}
                if review_data_available
                else None
            ),
            "lifecycle": {
                "enabled": lifecycle_enabled,
                "status": "ENABLED" if lifecycle_enabled else "DISABLED",
            },
            "review": {
                "enabled": review_enabled,
                "status": review_status,
            },
            "preview_available": True,
            "promotion": {
                "enabled": promotion_enabled,
                "status": "ENABLED" if promotion_enabled else "DISABLED / FAIL-CLOSED",
                "rules": list(rules),
                "rule_count": len(rules),
                "reason": (
                    "当前尚无 ReviewFinding 满足生产唯一允许的明确纠正规则。"
                    if promotion_enabled
                    else self.PROMOTION_REASON
                ),
            },
            "semantic_evaluator": self._runtime_state.get("semantic_evaluator"),
            "interaction_trace": interaction_trace,
            "behavioral_learning": {
                "enabled": p2b_shadow["enabled"],
                "status": "SHADOW" if p2b_shadow["enabled"] else "DISABLED",
                "label": "P2b 影子候选已启用" if p2b_shadow["enabled"] else "P2b 尚未启用",
            },
            "p2b_shadow": p2b_shadow,
            "adaptive_runtime": self._adaptive_runtime_projection(),
        }

    def runtime_detail(self, *, now: float | None = None) -> dict[str, Any]:
        """Return a safe detail projection for the runtime summary cards.

        The dashboard does not have a conversation scope, so this method never
        exposes scope identifiers, user IDs, aliases, candidate IDs, message
        text, evidence text, or storage payloads.  Owner objects are read only;
        malformed owner data is represented as ``CORRUPTED`` instead of being
        guessed into an apparently healthy state.
        """

        current_time = time.time() if now is None else float(now)
        if not math.isfinite(current_time):
            current_time = time.time()
        episodes = ()
        outcomes = ()
        episode_read_ok = self._episode_store is None
        if self._episode_store is not None:
            try:
                episodes = tuple(self._episode_store.all_episodes())
                outcomes = tuple(self._episode_store.get_outcomes())
                episode_read_ok = True
            except Exception:
                episodes = outcomes = ()
                episode_read_ok = False
        return {
            "schema_version": _RUNTIME_DETAIL_SCHEMA,
            "available": True,
            "generated_at": current_time,
            "details": {
                "identity": self._identity_runtime_detail(),
                "host_cas": self._host_cas_runtime_detail(),
                "relationship": self._projection_runtime_detail(
                    "relationship", owner="ProfileStorage", count_key="relationship", ttl_seconds=7 * 24 * 60 * 60,
                ),
                "behavioral_prior": self._projection_runtime_detail(
                    "behavioral_prior", owner="ProfileStorage", count_key="behavioral_prior",
                ),
                "situation": self._projection_runtime_detail(
                    "situation", owner="CognitiveRuntime", count_key="events",
                ),
                "affect": self._affect_runtime_detail(current_time),
                "feedback_replay": self._feedback_runtime_detail(current_time),
                "response_preferences": self._preference_runtime_detail(current_time),
                "p2b_shadow": self._p2b_runtime_detail(),
                "episodes": {
                    "available": episode_read_ok,
                    "status": "AVAILABLE" if episode_read_ok else "UNAVAILABLE",
                    "count": len(episodes) if episode_read_ok else "Unavailable",
                    "finalized_count": (
                        sum(item.state is EpisodeState.FINALIZED for item in episodes)
                        if episode_read_ok
                        else "Unavailable"
                    ),
                    "outcome_count": len(outcomes) if episode_read_ok else "Unavailable",
                    "reason": None if episode_read_ok else "episode_store_read_failed" if self._episode_store is not None else "episode_store_not_wired",
                },
                "outcomes": {
                    "available": episode_read_ok,
                    "status": "AVAILABLE" if episode_read_ok and outcomes else "EMPTY" if episode_read_ok else "UNAVAILABLE",
                    "owner": "EpisodeStore",
                    "count": len(outcomes) if episode_read_ok else "Unavailable",
                    "reason": None if episode_read_ok and outcomes else "outcome_store_empty" if episode_read_ok else "episode_store_read_failed",
                },
                "review": self._review_runtime_detail(episodes) if episode_read_ok else {
                    "available": False,
                    "status": "UNAVAILABLE",
                    "owner": "ReviewStore",
                    "reason": "episode_store_read_failed",
                },
            },
        }

    def _host_cas_runtime_detail(self) -> dict[str, Any]:
        available = self._state_bool("host_cas_available")
        return {
            "available": available,
            "status": "AVAILABLE" if available else "UNAVAILABLE",
            "owner": "Host persistence adapter",
            "mode": "CAS + transaction + read-back" if available else None,
            "allowed_parameter": "response_style_preference:v1",
            "permission_effect": "NONE",
            "reason": None if available else "host_cas_not_bound",
        }

    def _identity_runtime_detail(self) -> dict[str, Any]:
        """Project Identity without returning private identifiers or aliases."""

        base = {
            "owner": "Identity/EntityRegistry",
            "redacted_fields": ["platform_uid", "alias", "evidence"],
            "entities": [],
            "claims": [],
            "status_counts": {},
        }
        registry = self._runtime_state.get("identity_registry")
        if registry is None:
            available = self._state_bool("identity_available")
            base.update(
                {
                    "available": available,
                    "status": "SUMMARY_ONLY" if available else "UNAVAILABLE",
                    "entity_count": self._runtime_state.get("identity_entities") if available else "Unavailable",
                    "claim_count": self._runtime_state.get("identity_claims") if available else "Unavailable",
                    "reason": "identity_registry_not_bound" if available else "identity_registry_unavailable",
                }
            )
            return base
        if getattr(registry, "available", True) is not True:
            base.update(
                {
                    "available": False,
                    "status": "UNAVAILABLE",
                    "entity_count": "Unavailable",
                    "claim_count": "Unavailable",
                    "reason": "identity_registry_corrupted_or_unavailable",
                }
            )
            return base
        try:
            entities = tuple(registry.entities())
            claims = tuple(registry.all_claims())
            self_entity = str(getattr(registry, "self_entity", ""))
            entity_views = []
            entity_keys: dict[str, str] = {}
            for entity in entities:
                entity_id = str(getattr(entity, "id", ""))
                if not entity_id:
                    raise ValueError("identity entity lacks an ID")
                entity_key = "SELF" if entity_id == self_entity else _opaque_ref(entity_id, "entity")
                entity_keys[entity_id] = entity_key
                aliases = getattr(entity, "aliases", ())
                platform_ids = getattr(entity, "platform_ids", {})
                entity_views.append(
                    {
                        "entity_ref": entity_key,
                        "kind": entity_id.split(":", 1)[0].upper() or "UNKNOWN",
                        "alias_count": len(tuple(aliases)) if aliases is not None else 0,
                        "platform_binding_count": len(platform_ids) if isinstance(platform_ids, Mapping) else 0,
                    }
                )
            claim_views = []
            status_counts: dict[str, int] = {}
            for claim in claims:
                status = getattr(getattr(claim, "status", None), "value", None)
                status = str(status or "UNKNOWN")
                status_counts[status] = status_counts.get(status, 0) + 1
                candidate = str(getattr(claim, "candidate_entity", ""))
                source = str(getattr(claim, "source", ""))
                claim_views.append(
                    {
                        "claim_ref": _opaque_ref(
                            getattr(registry, "claim_id", lambda value: value)(claim), "claim"
                        ),
                        "candidate_ref": entity_keys.get(candidate, _opaque_ref(candidate, "entity")),
                        "status": status,
                        "confidence": getattr(claim, "confidence", None),
                        "source_kind": source.split(":", 1)[0] if source else "unknown",
                        "created_at": _json_value(getattr(claim, "created_at", None)),
                    }
                )
            return {
                **base,
                "available": True,
                "status": "AVAILABLE" if entities or claims else "EMPTY",
                "entity_count": len(entities),
                "claim_count": len(claims),
                "self_present": bool(self_entity and self_entity in entity_keys),
                "entities": entity_views,
                "claims": claim_views,
                "status_counts": status_counts,
                "reason": "identity_registry_empty" if not entities and not claims else None,
            }
        except Exception:
            return {
                **base,
                "available": False,
                "status": "CORRUPTED",
                "entity_count": "Unavailable",
                "claim_count": "Unavailable",
                "reason": "identity_registry_read_failed",
            }

    def _projection_runtime_detail(
        self, key: str, *, owner: str, count_key: str, ttl_seconds: int | None = None
    ) -> dict[str, Any]:
        counts = self._runtime_state.get("projection_counts")
        if not isinstance(counts, Mapping):
            counts = {}
        observed = _safe_count(counts.get(count_key, 0))
        raw_details = self._runtime_state.get("projection_details")
        raw = raw_details.get(key) if isinstance(raw_details, Mapping) else None
        if raw is not None and not isinstance(raw, Mapping):
            return {
                "available": False,
                "status": "CORRUPTED",
                "owner": owner,
                "observed": "Unavailable",
                "reason": f"{key}_projection_invalid",
            }
        status = "AVAILABLE" if observed else "EMPTY"
        result: dict[str, Any] = {
            "available": True,
            "status": status,
            "owner": owner,
            "observed": observed,
            "last_projection_at": self._runtime_state.get("last_projection_at"),
            "reason": None if observed else f"{key}_projection_empty",
        }
        if ttl_seconds is not None:
            result["ttl_seconds"] = ttl_seconds
        if isinstance(raw, Mapping):
            # Only owner metadata is accepted; values and scope are deliberately
            # omitted even when a caller supplies them in a test fixture.
            if isinstance(raw.get("last_projection_at"), (int, float)):
                result["last_projection_at"] = raw["last_projection_at"]
            if isinstance(raw.get("source_kind"), str):
                result["source_kind"] = raw["source_kind"][:80]
            if isinstance(raw.get("reason"), str):
                result["reason"] = raw["reason"][:160]
            parameters = raw.get("parameters")
            if isinstance(parameters, (list, tuple, set, frozenset)):
                result["parameters"] = sorted(
                    {item for item in parameters if isinstance(item, str) and item in _SAFE_PREFERENCE_PARAMETERS}
                )
        return result

    def _affect_runtime_detail(self, now: float) -> dict[str, Any]:
        base = {
            "owner": "astrbot_plugin_affection",
            "schema": "iris.affect-view.v1",
            "redacted_fields": ["user_id", "scope", "history", "prompt"],
            "metrics": [],
            "labels": {},
            "generated_at": None,
            "expires_at": None,
            "ttl_seconds": None,
        }
        raw = self._runtime_state.get("affect_snapshot")
        if raw is None:
            return {
                **base,
                "available": False,
                "status": "UNAVAILABLE",
                "reason": "sanitized_affect_snapshot_not_bound",
            }
        if not isinstance(raw, Mapping):
            return {**base, "available": False, "status": "CORRUPTED", "reason": "affect_snapshot_invalid"}
        if raw.get("schema") != "iris.affect-view.v1" or raw.get("owner") != "astrbot_plugin_affection":
            return {**base, "available": False, "status": "CORRUPTED", "reason": "affect_snapshot_contract_mismatch"}
        generated = raw.get("generated_at")
        expires = raw.get("expires_at")
        if (
            type(generated) not in (int, float)
            or type(expires) not in (int, float)
            or not math.isfinite(float(generated))
            or not math.isfinite(float(expires))
            or float(expires) <= float(generated)
            or float(generated) > now
        ):
            return {**base, "available": False, "status": "CORRUPTED", "reason": "affect_snapshot_ttl_invalid"}
        base.update(
            {
                "generated_at": float(generated),
                "expires_at": float(expires),
                "ttl_seconds": max(0, int(float(expires) - float(generated))),
            }
        )
        if now >= float(expires):
            return {**base, "available": False, "status": "EXPIRED", "reason": "affect_snapshot_ttl_elapsed"}
        metrics = []
        for name, maximum in _SAFE_AFFECT_NUMERIC_FIELDS.items():
            if name not in raw:
                continue
            value = raw[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                or float(value) > maximum
            ):
                return {**base, "available": False, "status": "CORRUPTED", "reason": "affect_snapshot_metric_invalid"}
            metrics.append({"name": name, "value": float(value), "maximum": maximum})
        labels = {}
        for name in _SAFE_AFFECT_LABEL_FIELDS:
            if name in raw:
                if not isinstance(raw[name], str) or len(raw[name]) > 120:
                    return {**base, "available": False, "status": "CORRUPTED", "reason": "affect_snapshot_label_invalid"}
                labels[name] = raw[name]
        return {
            **base,
            "available": True,
            "status": "AVAILABLE" if metrics or labels else "EMPTY",
            "metrics": metrics,
            "labels": labels,
            "reason": None if metrics or labels else "affect_snapshot_has_no_safe_values",
        }

    def _feedback_runtime_detail(self, now: float) -> dict[str, Any]:
        available = self._state_bool("feedback_available")
        observed = _safe_count(self._runtime_state.get("feedback_observations"))
        result = {
            "available": available,
            "status": "AVAILABLE" if available and observed else "EMPTY" if available else "UNAVAILABLE",
            "owner": "ResponseLengthFeedbackReviewObserverV1",
            "observed": observed if available else "Unavailable",
            "mode": "append-only",
            "reason": None if available and observed else "feedback_projection_empty" if available else "feedback_observer_unavailable",
        }
        raw = self._runtime_state.get("feedback_detail")
        if raw is not None and not isinstance(raw, Mapping):
            return {**result, "available": False, "status": "CORRUPTED", "observed": "Unavailable", "reason": "feedback_projection_invalid"}
        if isinstance(raw, Mapping):
            states = raw.get("evidence_states")
            if isinstance(states, Mapping):
                result["evidence_states"] = {
                    str(key): _safe_count(value) for key, value in states.items() if isinstance(key, str)
                }
            latest = raw.get("latest_observed_at")
            if isinstance(latest, (int, float)) and math.isfinite(float(latest)):
                result["latest_observed_at"] = float(latest)
        return result

    def _preference_runtime_detail(self, now: float) -> dict[str, Any]:
        """Aggregate injected preference records without cross-scope fields."""

        raw = self._runtime_state.get("response_preference_records")
        base = {
            "owner": "ProfileStorage",
            "redacted_fields": ["scope", "value", "candidate_id", "source_event_id"],
            "records": [],
            "status_counts": {},
            "parameter_counts": {},
        }
        if raw is None:
            return {
                **base,
                "available": False,
                "status": "UNAVAILABLE",
                "record_count": "Unavailable",
                "reason": "response_preference_records_not_bound",
            }
        if not isinstance(raw, (list, tuple)):
            return {**base, "available": False, "status": "CORRUPTED", "record_count": "Unavailable", "reason": "response_preference_projection_invalid"}
        invalid = 0
        for record in raw:
            getter = record.get if isinstance(record, Mapping) else lambda name, default=None: getattr(record, name, default)
            parameter = getter("parameter")
            if parameter not in _SAFE_PREFERENCE_PARAMETERS:
                invalid += 1
                continue
            status = getter("display_status")
            if callable(status):
                try:
                    status = status(now)
                except Exception:
                    status = None
            if not isinstance(status, str):
                status = getter("status")
            if not isinstance(status, str):
                invalid += 1
                continue
            expires = getter("expires_at")
            if status == "APPROVED" and isinstance(expires, (int, float)) and expires <= now:
                status = "EXPIRED"
            source = getter("source")
            source_kind = source.get("source_kind") if isinstance(source, Mapping) else getattr(source, "source_kind", None)
            view = {
                "parameter": parameter,
                "status": status,
                "requested_at": getter("requested_at") if isinstance(getter("requested_at"), (int, float)) else None,
                "approved_at": getter("approved_at") if isinstance(getter("approved_at"), (int, float)) else None,
                "expires_at": expires if isinstance(expires, (int, float)) else None,
                "revoked_at": getter("revoked_at") if isinstance(getter("revoked_at"), (int, float)) else None,
                "suspended_reason": getter("suspended_reason")[:120] if isinstance(getter("suspended_reason"), str) else None,
                "source_kind": source_kind.split(":", 1)[0] if isinstance(source_kind, str) and source_kind else "unknown",
            }
            base["records"].append(view)
            base["status_counts"][status] = base["status_counts"].get(status, 0) + 1
            base["parameter_counts"][parameter] = base["parameter_counts"].get(parameter, 0) + 1
        if invalid and not base["records"]:
            return {**base, "available": False, "status": "CORRUPTED", "record_count": "Unavailable", "invalid_record_count": invalid, "reason": "response_preference_projection_corrupted"}
        return {
            **base,
            "available": True,
            "status": "AVAILABLE" if base["records"] else "EMPTY",
            "record_count": len(base["records"]),
            "invalid_record_count": invalid,
            "reason": None if base["records"] else "response_preference_projection_empty",
        }

    def _p2b_runtime_detail(self) -> dict[str, Any]:
        projection = dict(self._p2b_shadow_projection())
        enabled = projection.get("enabled") is True
        return {
            "available": enabled,
            "status": "AVAILABLE" if enabled else "UNAVAILABLE",
            "owner": "ShadowCandidateEvaluator / append-only journal",
            "mode": projection.get("mode"),
            "candidate_status_counts": projection.get("candidate_status_counts", {}),
            "last_evaluation_at": projection.get("last_evaluation_at"),
            "allowed_parameters": projection.get("allowed_parameters", []),
            "permission_effect": projection.get("permission_effect", "NONE"),
            "reason": None if enabled else "p2b_shadow_store_unavailable",
            "redacted_fields": ["candidate_id", "scope", "evidence_refs", "value"],
        }

    def _review_runtime_detail(self, episodes: tuple[Any, ...]) -> dict[str, Any]:
        if self._review_store is None:
            return {"available": False, "status": "UNAVAILABLE", "owner": "ReviewStore", "reason": "review_store_not_wired"}
        try:
            runs = []
            evidence_count = 0
            for episode in episodes:
                runs.extend(self._review_store.list_review_runs_for_episode(episode.episode_id))
                evidence_count += len(self._review_store.list_evidence_for_episode(episode.episode_id))
            return {
                "available": True,
                "status": "AVAILABLE" if runs else "EMPTY",
                "owner": "ReviewStore",
                "run_count": len(runs),
                "finding_count": sum(len(run.findings) for run in runs),
                "evidence_count": evidence_count,
                "reason": None if runs else "review_store_empty",
            }
        except Exception:
            return {"available": False, "status": "UNAVAILABLE", "owner": "ReviewStore", "reason": "review_store_read_failed"}

    def _p2b_shadow_projection(self) -> dict[str, Any]:
        store = self._runtime_state.get("p2b_shadow_store")
        statuses = {name: 0 for name in ("PENDING", "APPROVED", "REJECTED", "REVOKED", "CONFLICTED", "EXPIRED")}
        enabled = store is not None and bool(getattr(store, "available", False))
        if enabled:
            try:
                for candidate in store.all_candidates():
                    status = getattr(getattr(candidate, "status", None), "value", None)
                    if status in statuses:
                        statuses[status] += 1
            except Exception:
                enabled = False
                statuses = {name: 0 for name in statuses}
        return {
            "enabled": enabled,
            "mode": "SHADOW",
            "auto_approve": False,
            "auto_publish": False,
            "permission_effect": "NONE",
            "allowed_scope": "PRIVATE_UID_ONLY",
            "allowed_parameters": ["response_length"],
            "minimum_exact_evidence": 2,
            "minimum_distinct_episodes": 2,
            "candidate_status_counts": statuses,
            "last_evaluation_at": self._runtime_state.get("p2b_shadow_last_evaluation_at"),
        }

    def _adaptive_runtime_projection(self) -> dict[str, Any]:
        counts = self._runtime_state.get("projection_counts")
        if not isinstance(counts, Mapping):
            counts = {}
        return {
            "host_cas": {
                "available": self._state_bool("host_cas_available"),
                "scope": "response_style_preference:v1",
            },
            "feedback_replay": {
                "available": self._state_bool("feedback_available"),
                "observations": int(self._runtime_state.get("feedback_observations") or 0),
                "mode": "append-only",
            },
            "identity": {
                "available": self._state_bool("identity_available"),
                "entities": self._runtime_state.get("identity_entities"),
                "claims": self._runtime_state.get("identity_claims"),
                "owner": "Identity/EntityRegistry",
            },
            "situation": {
                "available": True,
                "events": int(counts.get("events", 0) or 0),
                "last_projection_at": self._runtime_state.get("last_projection_at"),
            },
            "relationship": {"available": True, "observed": int(counts.get("relationship", 0) or 0), "owner": "ProfileStorage"},
            "behavioral_prior": {"available": True, "observed": int(counts.get("behavioral_prior", 0) or 0), "permission_effect": "none"},
            "affect": {"available": True, "observed": int(counts.get("affect", 0) or 0), "owner": "astrbot_plugin_affection", "ttl_seconds": 60},
            "history_write": {"status": "LOCKED", "reason": "exact_single_record_authorization_required"},
        }

    def _interaction_trace_projection(self) -> dict[str, Any]:
        if self._interaction_trace_reader is None:
            return {
                "schema_version": "p2x.interaction-observatory.v1",
                "available": False,
                "reason": "interaction_trace_not_bound",
            }
        try:
            payload = self._interaction_trace_reader.read_summary()
            if not isinstance(payload, Mapping) or payload.get("schema_version") != "p2x.interaction-observatory.v1":
                raise ValueError("invalid_interaction_trace_projection")
            return dict(payload)
        except Exception:
            return {
                "schema_version": "p2x.interaction-observatory.v1",
                "available": False,
                "reason": "interaction_trace_read_failed",
            }

    def list_episodes(
        self, *, state: str | None = None, query: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        if self._episode_store is None:
            return {"available": False, "episodes": [], "total": 0, "reason": "episode_store_not_wired"}
        try:
            wanted = EpisodeState(state) if state and state != "ALL" else None
        except ValueError as exc:
            raise ValueError("invalid episode state") from exc
        needle = (query or "").strip().casefold()
        items = []
        for episode in self._episode_store.all_episodes():
            if wanted and episode.state is not wanted:
                continue
            searchable = " ".join([episode.episode_id, episode.root_event_id] + [ref.ref_id for ref in episode.event_refs]).casefold()
            if needle and needle not in searchable:
                continue
            outcomes = self._episode_store.get_outcomes(episode.episode_id)
            items.append(self._episode_summary(episode, outcomes))
        items.sort(key=lambda item: (item["last_activity_at"] or "", item["episode_id"]), reverse=True)
        total = len(items)
        return {"available": True, "episodes": items[offset : offset + limit], "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def _identity_claim_human(
        claim: object,
        entities_by_id: Mapping[str, object],
        claims: tuple[object, ...],
    ) -> dict[str, Any]:
        mention = getattr(claim, "mention", None)
        mention_text = mention.strip() if isinstance(mention, str) else "未命名"
        candidate = getattr(claim, "candidate_entity", None)
        candidate_id = candidate if isinstance(candidate, str) else ""
        target = entities_by_id.get(candidate_id)
        target_aliases = tuple(
            alias.strip()
            for alias in _safe_sequence(getattr(target, "aliases", ()))
            if isinstance(alias, str) and alias.strip()
        )
        target_name = target_aliases[0] if target_aliases else (
            "小天文自己" if candidate_id.startswith("agent:") else "未命名用户"
        )
        mention_key = mention_text.casefold()
        related = tuple(
            item
            for item in claims
            if isinstance(getattr(item, "mention", None), str)
            and getattr(item, "mention").strip().casefold() == mention_key
            and _enum_value(getattr(item, "status", None)) != "REVOKED"
        )
        targets = {
            item.candidate_entity
            for item in related
            if isinstance(getattr(item, "candidate_entity", None), str)
        }
        raw_status = _enum_value(getattr(claim, "status", None))
        conflict = len(targets) > 1 or raw_status == "REJECTED"
        status_label = "冲突" if conflict else _IDENTITY_STATUS_LABELS.get(
            raw_status, "未知状态，查看工程详情"
        )
        evidence = _safe_sequence(getattr(claim, "evidence", ()))
        source = getattr(claim, "source", None)
        source_text = source.strip() if isinstance(source, str) else ""
        source_label = "人工确认" if source_text.casefold().startswith("admin:") else "系统记录"
        return {
            "summary": (
                f"名称“{mention_text}”指向“{target_name}”，当前{status_label}；"
                f"依据 {len(evidence)} 条；来源为{source_label}。"
            ),
            "name": mention_text,
            "target_name": target_name,
            "status": status_label,
            "evidence_count": len(evidence),
            "source_explanation": f"来源为{source_label}",
            "known": raw_status in _IDENTITY_STATUS_LABELS or conflict,
        }

    @classmethod
    def _identity_entity_human(
        cls,
        entity: object,
        claims: tuple[object, ...],
        self_entity: str,
        entities_by_id: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        entity_id = getattr(entity, "id", None)
        entity_id = entity_id if isinstance(entity_id, str) else ""
        is_self = entity_id == self_entity
        aliases = tuple(
            alias.strip()
            for alias in _safe_sequence(getattr(entity, "aliases", ()))
            if isinstance(alias, str) and alias.strip()
        )
        entity_claims = tuple(
            claim for claim in claims if getattr(claim, "candidate_entity", None) == entity_id
        )
        entities_by_id = entities_by_id or {entity_id: entity}
        alias_views: list[dict[str, Any]] = []
        for alias in aliases:
            related = tuple(
                claim
                for claim in claims
                if isinstance(getattr(claim, "mention", None), str)
                and claim.mention.strip().casefold() == alias.casefold()
            )
            statuses = [
                cls._identity_claim_human(claim, entities_by_id, claims).get("status")
                for claim in related
            ]
            status = (
                "冲突" if "冲突" in statuses else
                "已确认" if "已确认" in statuses else
                "待确认" if "待确认" in statuses else
                "已撤销" if "已撤销" in statuses else
                "未知状态，查看工程详情"
            )
            source_label = (
                "人工确认"
                if any(
                    isinstance(getattr(claim, "source", None), str)
                    and claim.source.casefold().startswith("admin:")
                    for claim in related
                )
                else "系统记录"
            )
            alias_views.append(
                {
                    "name": alias,
                    "status": status,
                    "source_explanation": f"来源为{source_label}",
                }
            )
        platform_bindings = [
            {
                "platform": _platform_label(platform),
                "value": value if isinstance(value, str) else "未知值，查看工程详情",
                "status": "已绑定" if isinstance(value, str) and value else "不可用",
                "source_explanation": "来源为系统记录的平台绑定",
            }
            for platform, value in dict(getattr(entity, "platform_ids", {})).items()
        ]
        conflict_mentions: set[str] = set()
        for claim in claims:
            mention = getattr(claim, "mention", None)
            if not isinstance(mention, str):
                continue
            related_targets = {
                item.candidate_entity
                for item in claims
                if isinstance(getattr(item, "mention", None), str)
                and item.mention.strip().casefold() == mention.strip().casefold()
                and _enum_value(getattr(item, "status", None)) != "REVOKED"
            }
            if len(related_targets) > 1:
                conflict_mentions.add(mention.strip().casefold())
        valid_count = sum(
            _enum_value(getattr(claim, "status", None)) in {"CONFIRMED", "POSSIBLE"}
            and not (
                isinstance(getattr(claim, "mention", None), str)
                and claim.mention.strip().casefold() in conflict_mentions
            )
            for claim in entity_claims
        )
        revoked_count = sum(
            _enum_value(getattr(claim, "status", None)) == "REVOKED" for claim in entity_claims
        )
        conflict_count = sum(
            isinstance(getattr(claim, "mention", None), str)
            and (
                claim.mention.strip().casefold() in conflict_mentions
                or _enum_value(getattr(claim, "status", None)) == "REJECTED"
            )
            for claim in entity_claims
        )
        confirmed_alias_count = sum(item["status"] == "已确认" for item in alias_views)
        name = aliases[0] if aliases else ("小天文自己" if is_self else "未命名用户")
        kind_label = "小天文自己" if is_self else "一个用户身份"
        return {
            "name": name,
            "kind_label": kind_label,
            "summary": (
                f"这是{kind_label}；已绑定 {len(platform_bindings)} 个平台账号；"
                f"有 {confirmed_alias_count} 个确认别名；当前有 {valid_count} 条有效、"
                f"{conflict_count} 条冲突、{revoked_count} 条撤销声明。"
            ),
            "platforms": platform_bindings,
            "aliases": alias_views,
            "claim_counts": {
                "valid": valid_count,
                "conflict": conflict_count,
                "revoked": revoked_count,
            },
            "known": bool(entity_id),
        }

    @classmethod
    def _identity_human(
        cls,
        entities: tuple[object, ...],
        claims: tuple[object, ...],
        self_entity: str,
    ) -> dict[str, Any]:
        entities_by_id = {
            entity.id: entity
            for entity in entities
            if isinstance(getattr(entity, "id", None), str)
        }
        entity_views = [
            cls._identity_entity_human(entity, claims, self_entity, entities_by_id) for entity in entities
        ]
        claim_views = [
            cls._identity_claim_human(claim, entities_by_id, claims) for claim in claims
        ]
        return {
            "summary": f"当前记录了 {len(entities)} 个身份和 {len(claims)} 条身份声明。",
            "entities": entity_views,
            "claims": claim_views,
            "empty_message": "当前没有可显示的身份记录。" if not entities and not claims else None,
        }

    def admin_identity(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Return the bounded, administrator-only Identity record listing.

        This endpoint is still a read model.  It exposes the Identity contract
        fields needed for audit (including aliases and platform bindings), but
        never calls a registry mutation method and never returns the registry
        storage envelope.
        """
        limit, offset = _admin_page(limit, offset)
        registry = self._runtime_state.get("identity_registry")
        base = {
            "schema": _ADMIN_IDENTITY_SCHEMA,
            "available": False,
            "status": "UNAVAILABLE",
            "entities": [],
            "claims": [],
            "entity_count": "Unavailable",
            "claim_count": "Unavailable",
            "human": {
                "summary": "身份详情当前不可用，不能把不可用误报成空数据。",
                "entities": [],
                "claims": [],
                "empty_message": "身份库当前不可用。",
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "entities_total": "Unavailable",
                "claims_total": "Unavailable",
            },
            "reason": "identity_registry_not_bound",
        }
        if registry is None:
            if self._state_bool("identity_available"):
                base["status"] = "SUMMARY_ONLY"
                base["reason"] = "identity_registry_not_bound"
            return base
        if getattr(registry, "available", True) is not True:
            base["reason"] = "identity_registry_corrupted_or_unavailable"
            return base
        try:
            entities = tuple(registry.entities())
            claims = tuple(registry.all_claims())
            self_entity = str(getattr(registry, "self_entity", ""))
            human_projection = self._identity_human(entities, claims, self_entity)
            human_entities = human_projection["entities"]
            human_claims = human_projection["claims"]
            entity_views = [
                _admin_json(
                    {
                        "id": entity.id,
                        "type": entity.id.split(":", 1)[0] if ":" in entity.id else "unknown",
                        "platform_ids": dict(entity.platform_ids),
                        "aliases": list(entity.aliases),
                        "self": entity.id == self_entity,
                        "human": human_entities[index],
                    }
                )
                for index, entity in enumerate(entities)
            ]
            claim_views = [
                _admin_json(
                    {
                        "claim_id": registry.claim_id(claim),
                        "mention": claim.mention,
                        "candidate_entity": claim.candidate_entity,
                        "evidence": list(claim.evidence),
                        "source": claim.source,
                        "status": _enum_value(claim.status),
                        "confidence": claim.confidence,
                        "created_at": claim.created_at,
                        "human": human_claims[index],
                    }
                )
                for index, claim in enumerate(claims)
            ]
            status = "AVAILABLE" if entities or claims else "EMPTY"
            return {
                "schema": _ADMIN_IDENTITY_SCHEMA,
                "available": True,
                "status": status,
                "entities": entity_views[offset : offset + limit],
                "claims": claim_views[offset : offset + limit],
                "entity_count": len(entities),
                "claim_count": len(claims),
                "human": _admin_json(
                    {
                        **human_projection,
                        "entities": human_entities[offset : offset + limit],
                        "claims": human_claims[offset : offset + limit],
                    }
                ),
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "entities_total": len(entities),
                    "claims_total": len(claims),
                },
                "reason": "identity_registry_empty" if status == "EMPTY" else None,
            }
        except Exception:
            return {
                **base,
                "status": "CORRUPTED",
                "reason": "identity_registry_read_failed",
            }

    def admin_episodes(
        self,
        *,
        state: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return bounded Episode records for an authenticated admin view."""
        limit, offset = _admin_page(limit, offset)
        if self._episode_store is None:
            return {
                "schema": _ADMIN_EPISODE_SCHEMA,
                "available": False,
                "status": "UNAVAILABLE",
                "episodes": [],
                "total": "Unavailable",
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": "互动历史当前不可用，不能把不可用误报成空数据。",
                    "episodes": [],
                    "empty_message": "EpisodeStore 当前不可用。",
                },
                "reason": "episode_store_not_wired",
            }
        try:
            wanted = EpisodeState(state) if state and state != "ALL" else None
        except ValueError as exc:
            raise ValueError("invalid episode state") from exc
        needle = (query or "").strip().casefold()
        try:
            selected = []
            for episode in self._episode_store.all_episodes():
                if wanted and episode.state is not wanted:
                    continue
                searchable = " ".join(
                    [episode.episode_id, episode.scope_id, episode.root_event_id]
                    + [ref.ref_id for ref in episode.event_refs]
                ).casefold()
                if needle and needle not in searchable:
                    continue
                outcomes = self._episode_store.get_outcomes(episode.episode_id)
                selected.append(self._admin_episode_summary(episode, outcomes))
            selected.sort(key=lambda item: (item["last_activity_at"] or "", item["episode_id"]), reverse=True)
            return {
                "schema": _ADMIN_EPISODE_SCHEMA,
                "available": True,
                "status": "AVAILABLE" if selected else "EMPTY",
                "episodes": selected[offset : offset + limit],
                "total": len(selected),
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": f"当前显示 {len(selected)} 段互动记录。" if selected else "当前没有可显示的互动记录。",
                    "episodes": [item["human"] for item in selected[offset : offset + limit]],
                    "empty_message": "当前没有可显示的互动记录。" if not selected else None,
                },
                "reason": None if selected else "episode_store_empty",
            }
        except Exception:
            return {
                "schema": _ADMIN_EPISODE_SCHEMA,
                "available": False,
                "status": "UNAVAILABLE",
                "episodes": [],
                "total": "Unavailable",
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": "互动历史读取失败，不能把读取失败误报成空数据。",
                    "episodes": [],
                    "empty_message": "EpisodeStore 当前不可用。",
                },
                "reason": "episode_store_read_failed",
            }

    def admin_episode_detail(self, episode_id: str) -> dict[str, Any]:
        """Return one Episode plus its read-only Outcome/Review associations."""
        episode = self._require_episode(episode_id)
        try:
            outcomes = tuple(self._episode_store.get_outcomes(episode_id))  # type: ignore[union-attr]
        except Exception as exc:
            raise RuntimeError("episode_store_read_failed") from exc
        persisted = self._persisted_review(episode_id)
        try:
            snapshot = self.snapshot_debug_view(episode_id)
            attachments = self._attachment_views(episode, outcomes)
            archive = self._persisted_archive(episode_id)
        except Exception:
            snapshot = {"available": False, "status": "UNAVAILABLE", "reason": "episode_snapshot_read_failed"}
            attachments = []
            archive = {"available": False, "status": "UNAVAILABLE", "count": "Unavailable", "archives": []}
        return {
            "schema": _ADMIN_EPISODE_SCHEMA,
            "available": True,
            "status": "AVAILABLE",
            "episode": self._admin_episode_view(episode, outcomes),
            "outcomes": [self._admin_outcome_view(outcome, episode) for outcome in outcomes],
            "human": _admin_json(self._admin_episode_human(episode, outcomes, persisted)),
            "review": _admin_json(persisted),
            "snapshot": _admin_json(snapshot),
            "attachments": _admin_json(attachments),
            "archive": _admin_json(archive),
            "read_only": True,
        }

    def admin_outcomes(
        self,
        *,
        episode_id: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return bounded OutcomeObservation records, preserving contract data."""
        limit, offset = _admin_page(limit, offset)
        if self._episode_store is None:
            return {
                "schema": _ADMIN_OUTCOME_SCHEMA,
                "available": False,
                "status": "UNAVAILABLE",
                "outcomes": [],
                "total": "Unavailable",
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": "结果记录当前不可用，不能把不可用误报成空数据。",
                    "outcomes": [],
                    "empty_message": "OutcomeStore 当前不可用。",
                },
                "reason": "episode_store_not_wired",
            }
        needle = (query or "").strip().casefold()
        try:
            outcomes = tuple(self._episode_store.get_outcomes(episode_id))
            if needle:
                outcomes = tuple(
                    outcome
                    for outcome in outcomes
                    if needle in " ".join(
                        filter(
                            None,
                            (
                                outcome.observation_id,
                                outcome.target_episode_id,
                                _enum_value(outcome.kind),
                                outcome.source_event_id,
                                outcome.source_ref_id,
                            ),
                        )
                    ).casefold()
                )
            episode_map = {
                episode.episode_id: episode for episode in self._episode_store.all_episodes()
            }
            views = [
                self._admin_outcome_view(outcome, episode_map.get(outcome.target_episode_id))
                for outcome in outcomes
            ]
            views.sort(key=lambda item: (item["observed_at"] or "", item["observation_id"]), reverse=True)
            return {
                "schema": _ADMIN_OUTCOME_SCHEMA,
                "available": True,
                "status": "AVAILABLE" if views else "EMPTY",
                "outcomes": views[offset : offset + limit],
                "total": len(views),
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": f"当前显示 {len(views)} 条结果观察。" if views else "当前没有可显示的结果观察。",
                    "outcomes": [item["human"] for item in views[offset : offset + limit]],
                    "empty_message": "当前没有可显示的结果观察。" if not views else None,
                },
                "reason": None if views else "outcome_store_empty",
            }
        except Exception:
            return {
                "schema": _ADMIN_OUTCOME_SCHEMA,
                "available": False,
                "status": "UNAVAILABLE",
                "outcomes": [],
                "total": "Unavailable",
                "limit": limit,
                "offset": offset,
                "human": {
                    "summary": "结果记录读取失败，不能把读取失败误报成空数据。",
                    "outcomes": [],
                    "empty_message": "OutcomeStore 当前不可用。",
                },
                "reason": "outcome_store_read_failed",
            }

    def episode_detail(self, episode_id: str) -> dict[str, Any]:
        episode = self._require_episode(episode_id)
        outcomes = self._episode_store.get_outcomes(episode_id)  # type: ignore[union-attr]
        persisted = self._persisted_review(episode_id)
        snapshot = self.snapshot_debug_view(episode_id)
        attachments = self._attachment_views(episode, outcomes)
        archive = self._persisted_archive(episode_id)
        return {
            "available": True,
            "episode": self._episode_view(episode),
            "outcomes": [self._outcome_view(outcome, episode) for outcome in outcomes],
            "timeline": self._timeline(episode, outcomes, persisted),
            "attachments": attachments,
            "review": persisted,
            "archive": archive,
            "snapshot": snapshot,
            # Pure read-model projection for the default human-readable view.
            # It never becomes an Episode/Outcome/Review source of truth.
            "human": self._human_detail(episode, outcomes, persisted, snapshot, attachments),
            "raw": {"episode": self._episode_view(episode), "outcomes": _json_value(outcomes), "review": persisted, "archive": archive, "snapshot": snapshot},
        }

    def persisted_review(self, episode_id: str) -> dict[str, Any]:
        self._require_episode(episode_id)
        return self._persisted_review(episode_id)

    def preview_review(self, episode_id: str) -> dict[str, Any]:
        """Run frozen review logic only against request-local in-memory state."""
        episode = self._require_episode(episode_id)
        outcomes = self._episode_store.get_outcomes(episode_id)  # type: ignore[union-attr]
        eligibility = evaluate_review_eligibility(episode, outcomes)
        facts, missing = self._attached_execution_facts(episode)
        if missing and any(ref.kind is EpisodeEventKind.HOST_OUTPUT for ref in episode.event_refs):
            return self._preview_response(
                eligibility=eligibility, run=None, facts=facts, unavailable_reason="execution_records_not_wired", missing=missing
            )
        preview_store = InMemoryReviewStore()
        run = review_episode(episode, outcomes, preview_store, fact_envelopes=facts)
        return self._preview_response(eligibility=eligibility, run=run, facts=facts, missing=missing)

    def snapshot_debug_view(self, episode_id: str) -> dict[str, Any]:
        episode = self._require_episode(episode_id)
        outcomes = self._episode_store.get_outcomes(episode_id)  # type: ignore[union-attr]
        facts, missing = self._attached_execution_facts(episode)
        try:
            snapshot = ReviewInputSnapshot(episode, outcomes, facts)
            return {
                "available": True,
                "hash": compute_input_snapshot_hash(episode, outcomes, facts),
                "fact_payload_hashed": True,
                "fact_deep_snapshotted": True,
                "episode_attachment": "ENFORCED",
                "event_count": len(episode.event_refs),
                "outcome_count": len(outcomes),
                "canonical_fact_count": len(snapshot.fact_envelopes),
                "source_types": sorted({source.value for source, _ in snapshot.fact_envelopes}),
                "canonical_facts": [
                    {
                        "source_type": source.value,
                        "ref_id": ref_id,
                        "schema_version": envelope.schema_version,
                        "payload": self._safe_fact_view(facts[(source, ref_id)]),
                    }
                    for (source, ref_id), envelope in snapshot.fact_envelopes.items()
                ],
                "execution_records_unavailable": missing,
            }
        except ValueError as exc:
            return {"available": False, "status": "REJECTED", "reason": str(exc), "execution_records_unavailable": missing}

    def demo_cases(self) -> list[dict[str, str]]:
        return [
            {"id": "correction", "title": "Correction", "summary": "Host output → explicit correction → Finding → zero Evidence"},
            {"id": "acknowledgement", "title": "Acknowledgement", "summary": "Host output → explicit acknowledgement → Finding → zero Evidence"},
            {"id": "late-feedback", "title": "Late Feedback", "summary": "Later feedback explicitly targets an old finalized Episode"},
            {"id": "silence", "title": "Silence / No Feedback", "summary": "No feedback never fabricates negative Finding or Evidence"},
            {"id": "unattached", "title": "Rejected Unattached Fact", "summary": "Typed Host execution not attached to Episode is rejected at snapshot boundary"},
        ]

    def demo_case(self, case_id: str) -> dict[str, Any]:
        if case_id not in {case["id"] for case in self.demo_cases()}:
            raise KeyError(case_id)
        episode, outcomes, records = self._demo_fixture(case_id)
        store = _DemoEpisodeStore(episode, outcomes)
        service = P1ObservatoryService(store, execution_records=records)
        detail = service.episode_detail(episode.episode_id)
        preview = service.preview_review(episode.episode_id)
        if case_id == "unattached":
            bad_ref = next(ref for ref in episode.event_refs if ref.kind is EpisodeEventKind.HOST_OUTPUT)
            bad_record = self._execution_record(event_id="demo:unattached")
            try:
                ReviewInputSnapshot(episode, outcomes, {(EvidenceSourceType.HOST_RESULT, bad_ref.ref_id): bad_record})
            except ValueError as exc:
                detail["rejection"] = {"status": "REJECTED", "reason": str(exc)}
        return {"demo": True, "case_id": case_id, "detail": detail, "preview": preview}

    def _require_episode(self, episode_id: str) -> Episode:
        if self._episode_store is None:
            raise RuntimeError("episode_store_not_wired")
        episode = self._episode_store.get_episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return episode

    def _persisted_review(self, episode_id: str) -> dict[str, Any]:
        if self._review_store is None:
            return {
                "available": False,
                "status": "NOT_WIRED",
                "result_code": "REVIEW_STORE_UNAVAILABLE",
                "result_reason": "ReviewStore 尚未接入；因此不能判断是否存在 ReviewRun。",
                "run_count": "Unavailable",
                "finding_count": "Unavailable",
                "evidence_count": "Unavailable",
                "runs": [],
                "evidence": [],
            }
        try:
            runs = self._review_store.list_review_runs_for_episode(episode_id)
            evidence = self._review_store.list_evidence_for_episode(episode_id)
        except Exception:
            return {
                "available": False,
                "status": "UNAVAILABLE",
                "result_code": "REVIEW_STORE_UNAVAILABLE",
                "result_reason": "ReviewStore 读取失败；不能把不可用误报成 0 条记录。",
                "run_count": "Unavailable",
                "finding_count": "Unavailable",
                "evidence_count": "Unavailable",
                "runs": [],
                "evidence": [],
            }

        run_views = [self._review_run_view(run, evidence) for run in runs]
        finding_count = sum(len(run.findings) for run in runs)
        evidence_count = len(evidence)
        result_code, result_reason = self._review_result_explanation(
            runs=runs,
            finding_count=finding_count,
            evidence_count=evidence_count,
        )
        return {
            "available": True,
            "status": "AVAILABLE" if runs else "NO_PERSISTED_REVIEW",
            "result_code": result_code,
            "result_reason": result_reason,
            "run_count": len(runs),
            "finding_count": finding_count,
            "evidence_count": evidence_count,
            "runs": run_views,
            "evidence": _json_value(evidence),
        }

    @classmethod
    def _review_run_view(cls, run: ReviewRun, evidence: tuple[Any, ...]) -> dict[str, Any]:
        """Expose one immutable Run with human-readable Finding references.

        This is a detached read projection.  It deliberately keeps the frozen
        ReviewFinding claim as recorded, while making structural references and
        the absence of promoted Evidence explicit for a human reader.
        """
        run_evidence = tuple(
            item for item in evidence if item.source_review_run_id == run.review_run_id
        )
        findings = []
        for finding in run.findings:
            findings.append(
                {
                    "finding_id": finding.finding_id,
                    "episode_id": finding.episode_id,
                    "review_run_id": finding.review_run_id,
                    "created_at": _timestamp(finding.created_at),
                    "dimension": finding.dimension.value,
                    "finding_type": finding.finding_type.value,
                    "claim": finding.claim,
                    "attributed_to": _json_value(finding.attributed_to),
                    "confidence": finding.confidence.value,
                    "causal_attribution": finding.causal_attribution.value,
                    "interpretation_producer": finding.interpretation_producer.value,
                    "evidence_refs": [
                        {
                            "ref_id": ref.ref_id,
                            "source_type": ref.source_type.value,
                            "evidence_kind": ref.evidence_kind.value,
                        }
                        for ref in finding.evidence_refs
                    ],
                }
            )
        return {
            "review_run_id": run.review_run_id,
            "episode_id": run.episode_id,
            "created_at": _timestamp(run.created_at),
            "status": run.status.value,
            "input_snapshot_hash": run.input_snapshot_hash,
            "finding_count": len(findings),
            "findings": findings,
            "evidence_count": len(run_evidence),
            "no_evidence_reason": (
                "Finding 已记录，但没有 ReviewEvidence；当前严格 promotion 条件未满足。"
                if findings and not run_evidence
                else None
            ),
        }

    def _review_result_explanation(
        self,
        *,
        runs: tuple[ReviewRun, ...],
        finding_count: int,
        evidence_count: int,
    ) -> tuple[str, str]:
        if not runs:
            return "NO_RUN", "该 Episode 没有持久化 ReviewRun；不是把结果默认为 0。"
        if finding_count == 0:
            return "NO_FINDINGS", "ReviewRun 已存在，但没有生成 Finding。"
        if evidence_count == 0:
            if self._runtime_state.get("promotion_enabled") is False:
                return "PROMOTION_DISABLED", "Finding 已记录；当前 promotion 未启用，因此没有生成 Evidence。"
            return "FINDINGS_NOT_PROMOTABLE", "Finding 已记录，但没有满足当前严格 promotion 条件的 Evidence。"
        return "EVIDENCE_AVAILABLE", "ReviewFinding 与已持久化 ReviewEvidence 均可查看。"

    def _persisted_archive(self, episode_id: str) -> dict[str, Any]:
        """Project the runtime-owned P2r0 archive without opening another store."""
        if self._p2r0_store is None:
            return {"available": False, "status": "UNAVAILABLE", "count": "Unavailable", "archives": []}
        try:
            archives = tuple(item for item in self._p2r0_store.archives if item.episode_id == episode_id)
        except Exception:
            return {"available": False, "status": "UNAVAILABLE", "count": "Unavailable", "archives": []}
        return {"available": True, "status": "AVAILABLE", "count": len(archives), "archives": _json_value(archives)}

    def _state_bool(self, key: str) -> bool:
        return self._runtime_state.get(key) is True

    def _state_rules(self) -> tuple[str, ...]:
        raw = self._runtime_state.get("promotion_rules", ())
        if isinstance(raw, (tuple, list, frozenset, set)):
            return tuple(item for item in raw if isinstance(item, str))
        return ()

    def _attached_execution_facts(self, episode: Episode) -> tuple[dict[tuple[EvidenceSourceType, str], object], list[str]]:
        facts: dict[tuple[EvidenceSourceType, str], object] = {}
        missing: list[str] = []
        for ref in episode.event_refs:
            if ref.kind is not EpisodeEventKind.HOST_OUTPUT:
                continue
            record = self._execution_records.get(ref.ref_id)
            if record is None and self._execution_observatory is not None:
                record = self._execution_observatory.find_for_event_ref(ref)
            if record is None:
                missing.append(ref.ref_id)
            else:
                facts[(EvidenceSourceType.HOST_RESULT, ref.ref_id)] = record
        return facts, missing

    def _attachment_views(self, episode: Episode, outcomes: tuple[OutcomeObservation, ...]) -> list[dict[str, Any]]:
        views = []
        for ref in episode.event_refs:
            source_type = EvidenceSourceType.EPISODE_EVENT
            fact: object = ref
            if ref.kind is EpisodeEventKind.HOST_OUTPUT:
                source_type = EvidenceSourceType.HOST_RESULT
                fact = self._execution_records.get(ref.ref_id)
                if fact is None and self._execution_observatory is not None:
                    fact = self._execution_observatory.find_for_event_ref(ref)
                if fact is None:
                    views.append({"ref_id": ref.ref_id, "source_type": source_type.value, "status": "UNAVAILABLE", "reason": "execution_record_not_wired"})
                    continue
            try:
                ReviewInputSnapshot(episode, outcomes, {(source_type, ref.ref_id): fact})
                views.append({"ref_id": ref.ref_id, "source_type": source_type.value, "status": "ATTACHED", "canonical_payload": self._safe_fact_view(fact)})
            except ValueError as exc:
                views.append({"ref_id": ref.ref_id, "source_type": source_type.value, "status": "REJECTED", "reason": str(exc)})
        return views

    def _timeline(self, episode: Episode, outcomes: tuple[OutcomeObservation, ...], review: dict[str, Any]) -> list[dict[str, Any]]:
        entries = [
            {"at": _timestamp(ref.observed_at), "kind": _enum_value(ref.kind), "ref_id": ref.ref_id, "source_event_id": ref.source_event_id, "trace_id": ref.trace_id}
            for ref in episode.event_refs
        ]
        entries.extend({"at": _timestamp(outcome.observed_at), "kind": "OUTCOME", "ref_id": outcome.observation_id, "outcome_kind": _enum_value(outcome.kind), "late_feedback": self._is_late(outcome, episode)} for outcome in outcomes)
        for run in review.get("runs", []):
            entries.append({"at": run.get("created_at"), "kind": "REVIEW", "ref_id": run.get("review_run_id"), "status": run.get("status")})
        return sorted(entries, key=lambda item: item.get("at") or "")

    def _outcome_view(self, outcome: OutcomeObservation, episode: Episode) -> dict[str, Any]:
        payload = {
            "observation_id": outcome.observation_id,
            "target_episode_id": outcome.target_episode_id,
            "kind": _enum_value(outcome.kind),
            "observed_at": _timestamp(outcome.observed_at),
            "source_event_id": outcome.source_event_id,
            "source_ref_id": outcome.source_ref_id,
            "explicitness": _enum_value(outcome.explicitness),
            "confidence": outcome.confidence,
            "evidence": list(outcome.evidence),
            "producer": outcome.producer,
            "provenance": list(outcome.provenance),
        }
        payload["late_feedback"] = self._is_late(outcome, episode)
        return payload

    @classmethod
    def _event_human(cls, ref: object) -> dict[str, Any]:
        kind = _enum_value(getattr(ref, "kind", None))
        label, description = _EVENT_HUMAN_LABELS.get(
            kind,
            ("未知事件，查看工程详情", "系统保存了一个无法按当前版本解释的事件类型。"),
        )
        return {
            "at": _timestamp(getattr(ref, "observed_at", None))
            if isinstance(getattr(ref, "observed_at", None), datetime)
            else None,
            "label": label,
            "description": description,
            "source_explanation": "依据已持久化的 Episode 结构记录",
            "known": kind in _EVENT_HUMAN_LABELS,
        }

    @staticmethod
    def _episode_human_title(episode: object) -> str:
        snapshot = _admin_content_snapshot(getattr(episode, "topic_hint", None))
        text = snapshot.get("text")
        if snapshot.get("status") == "AVAILABLE" and isinstance(text, str) and text:
            return text
        return "未命名互动"

    @classmethod
    def _outcome_human(
        cls, outcome: object, episode: object | None = None
    ) -> dict[str, Any]:
        kind = _enum_value(getattr(outcome, "kind", None))
        explicitness = _enum_value(getattr(outcome, "explicitness", None))
        evidence = _safe_sequence(getattr(outcome, "evidence", ()))
        what_happened = _OUTCOME_HUMAN_LABELS.get(
            kind, "未知类型，查看工程详情"
        )
        direct_expression = _EXPLICITNESS_HUMAN_LABELS.get(
            explicitness, "未知是否直接表达，查看工程详情"
        )
        if kind == "EXPLICIT_CORRECTION":
            impact = "只记录为事实观察，并可能进入 Review；不会自动修改人格、关系或回复偏好。"
        elif kind == "EXPLICIT_ACKNOWLEDGEMENT":
            impact = "只记录为事实观察，并可能进入 Review；不等于奖励，也不会自动修改人格、关系或回复偏好。"
        elif kind in {"TOOL_SUCCEEDED", "TOOL_FAILED", "TOOL_RESULT_RECEIVED"}:
            impact = "只记录工具结果事实；不会自动当作奖励或修改人格、关系、偏好。"
        elif kind == "DELIVERY_FAILED":
            impact = "只记录发送结果事实；不会自动修改未来行为或推断用户偏好。"
        elif kind in _OUTCOME_HUMAN_LABELS:
            impact = "只记录为事实观察；不会自动当作奖励或修改人格、关系、偏好。"
        else:
            impact = "影响未知，查看工程详情；系统不会据此推断奖励、人格、关系或偏好。"
        late = (
            cls._is_late(outcome, episode)
            if episode is not None
            else False
        )
        return {
            "what_happened": what_happened,
            "target_interaction": cls._episode_human_title(episode) if episode is not None else "未知互动，查看工程详情",
            "basis": f"依据 {len(evidence)} 条已保存记录" if evidence else "没有附带依据记录",
            "basis_details": list(evidence),
            "evidence_count": len(evidence),
            "source_explanation": "来源为系统记录",
            "direct_expression": direct_expression,
            "late_feedback": "是，发生在互动封存之后" if late else "否，在互动期间记录",
            "current_impact": impact,
            "known": kind in _OUTCOME_HUMAN_LABELS and explicitness in _EXPLICITNESS_HUMAN_LABELS,
        }

    @classmethod
    def _human_review(cls, review: Mapping[str, Any]) -> dict[str, Any]:
        status = review.get("status")
        result_code = review.get("result_code")
        run_count = review.get("run_count")
        finding_count = review.get("finding_count")
        evidence_count = review.get("evidence_count")
        unavailable = status in {"NOT_WIRED", "UNAVAILABLE"} or result_code == "REVIEW_STORE_UNAVAILABLE"
        if unavailable:
            completion = "无法判断：Review 尚未接入或当前不可用。"
            found = "系统没有足够的 Review 记录来说明发现。"
        elif result_code == "NO_RUN":
            completion = "尚未完成复盘：没有持久化 ReviewRun。"
            found = "没有可报告的复盘发现。"
        elif result_code == "NO_FINDINGS":
            completion = "复盘已完成。"
            found = "复盘已完成，但没有发现需要记录的事项。"
        elif result_code in {"PROMOTION_DISABLED", "FINDINGS_NOT_PROMOTABLE"}:
            completion = "复盘已完成。"
            found = f"复盘记录了 {finding_count} 条可审计观察。"
        elif isinstance(run_count, int) and run_count > 0:
            completion = "复盘已完成。"
            found = f"复盘记录了 {finding_count} 条可审计观察。"
        else:
            completion = "尚未完成复盘：当前记录不足以确认。"
            found = "没有可报告的复盘发现。"
        reason = review.get("result_reason")
        if not isinstance(reason, str) or not reason:
            reason = "当前没有可用的复盘说明。"
        if evidence_count == 0:
            evidence_explanation = reason
        elif isinstance(evidence_count, int):
            evidence_explanation = f"已有 {evidence_count} 条 Evidence；来源由既有 Review 记录提供。"
        else:
            evidence_explanation = "Evidence 数量当前不可用，不能把不可用当成 0。"
        if unavailable:
            long_term_impact = "无法从当前记录判断长期影响；复盘页面不会自行修改长期记忆或行为。"
        elif evidence_count:
            long_term_impact = "已生成可审计 Evidence；复盘本身不会自动修改长期记忆、人格、关系或回复行为。"
        else:
            long_term_impact = "没有 Evidence；复盘只保留事实观察，不会自动修改长期记忆或行为。"
        findings: list[dict[str, Any]] = []
        for run in review.get("runs", ()) if isinstance(review.get("runs"), (tuple, list)) else ():
            if not isinstance(run, Mapping):
                continue
            for finding in run.get("findings", ()) if isinstance(run.get("findings"), (tuple, list)) else ():
                if isinstance(finding, Mapping):
                    claim = finding.get("claim")
                    if isinstance(claim, str) and claim:
                        findings.append({"what_was_found": claim})
        return {
            "completion": completion,
            "what_was_found": found,
            "findings": findings,
            "evidence_explanation": evidence_explanation,
            "long_term_impact": long_term_impact,
            "known": not unavailable,
        }

    @classmethod
    def _admin_episode_human(
        cls,
        episode: Episode,
        outcomes: tuple[OutcomeObservation, ...],
        review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        refs = _safe_sequence(getattr(episode, "event_refs", ()))
        state = _enum_value(getattr(episode, "state", None))
        title = cls._episode_human_title(episode)
        content = _admin_content_snapshot(getattr(episode, "topic_hint", None))
        actual_replies = sum(_enum_value(getattr(ref, "kind", None)) == "HOST_OUTPUT" for ref in refs)
        successful_sends = sum(
            _enum_value(getattr(ref, "kind", None)) in {"DISPATCH", "DELIVERY"}
            for ref in refs
        )
        timeline: list[dict[str, Any]] = [cls._event_human(ref) for ref in refs]
        timeline.extend(
            {
                "at": _timestamp(getattr(outcome, "observed_at", None))
                if isinstance(getattr(outcome, "observed_at", None), datetime)
                else None,
                "label": "用户明确纠正或确认"
                if _enum_value(getattr(outcome, "kind", None))
                in {"EXPLICIT_CORRECTION", "EXPLICIT_ACKNOWLEDGEMENT"}
                else cls._outcome_human(outcome, episode)["what_happened"],
                "description": cls._outcome_human(outcome, episode)["what_happened"],
                "source_explanation": "依据已持久化的 Outcome 观察记录",
                "late_feedback": cls._is_late(outcome, episode),
            }
            for outcome in outcomes
        )
        finalized_at = getattr(episode, "finalized_at", None)
        if isinstance(finalized_at, datetime):
            timeline.append(
                {
                    "at": _timestamp(finalized_at),
                    "label": "互动封存",
                    "description": "系统已将这段互动封存为可审计历史。",
                    "source_explanation": "依据 Episode 的封存时间",
                    "late_feedback": False,
                }
            )
        timeline.sort(key=lambda item: item.get("at") or "")
        if content.get("status") == "AVAILABLE":
            content_explanation = "系统保存了以下可读的结构摘要。"
        else:
            content_explanation = "系统只保存了结构记录，没有可读正文。"
        result = {
            "title": title,
            "summary": (
                f"这段互动{_EPISODE_STATE_LABELS.get(state, '处于未知状态，查看工程详情')}，"
                f"共 {sum(_enum_value(getattr(ref, 'kind', None)) == 'EXPERIENCE' for ref in refs)} 轮互动，"
                f"实际回复 {actual_replies} 次，记录 {len(outcomes)} 个结果。"
            ),
            "state_label": _EPISODE_STATE_LABELS.get(state, "未知状态，查看工程详情"),
            "opened_at": _timestamp(getattr(episode, "opened_at", None))
            if isinstance(getattr(episode, "opened_at", None), datetime)
            else None,
            "ended_at": _timestamp(finalized_at)
            if isinstance(finalized_at, datetime)
            else _timestamp(getattr(episode, "last_activity_at", None))
            if isinstance(getattr(episode, "last_activity_at", None), datetime)
            else None,
            "interaction_turns": sum(_enum_value(getattr(ref, "kind", None)) == "EXPERIENCE" for ref in refs),
            "actual_replies": actual_replies,
            "successful_sends": successful_sends,
            "result_count": len(outcomes),
            "content": {
                "status": content.get("status"),
                "text": content.get("text"),
                "explanation": content_explanation,
                "truncated": content.get("truncated", False),
            },
            "timeline": timeline,
            "timeline_empty_message": "这段互动没有可显示的时间线步骤。" if not timeline else None,
            "stored": "系统保存了 Episode、事件引用和结果观察的结构记录。",
        }
        if review is not None:
            result["review"] = cls._human_review(review)
        return result

    @classmethod
    def _admin_episode_summary(
        cls, episode: Episode, outcomes: tuple[OutcomeObservation, ...]
    ) -> dict[str, Any]:
        return _admin_json(
            {
                "episode_id": episode.episode_id,
                "scope_id": episode.scope_id,
                "state": episode.state.value,
                "root_event_id": episode.root_event_id,
                "opened_at": episode.opened_at,
                "last_activity_at": episode.last_activity_at,
                "soft_closed_at": episode.soft_closed_at,
                "finalized_at": episode.finalized_at,
                "event_count": len(episode.event_refs),
                "outcome_count": len(outcomes),
                "content_snapshot": _admin_content_snapshot(episode.topic_hint),
                "provenance": list(episode.provenance),
                "human": cls._admin_episode_human(episode, outcomes),
            }
        )

    @classmethod
    def _admin_episode_view(cls, episode: Episode, outcomes: tuple[OutcomeObservation, ...] = ()) -> dict[str, Any]:
        return _admin_json(
            {
                "episode_id": episode.episode_id,
                "scope_id": episode.scope_id,
                "state": episode.state.value,
                "root_event_id": episode.root_event_id,
                "opened_at": episode.opened_at,
                "last_activity_at": episode.last_activity_at,
                "soft_closed_at": episode.soft_closed_at,
                "finalized_at": episode.finalized_at,
                "participants": episode.participants,
                "content_snapshot": _admin_content_snapshot(episode.topic_hint),
                "event_refs": episode.event_refs,
                "unresolved_refs": list(episode.unresolved_refs),
                "revision": episode.revision,
                "provenance": list(episode.provenance),
                "human": cls._admin_episode_human(episode, outcomes),
            }
        )

    @classmethod
    def _admin_outcome_view(
        cls, outcome: OutcomeObservation, episode: Episode | None = None
    ) -> dict[str, Any]:
        return _admin_json(
            {
                "observation_id": getattr(outcome, "observation_id", None),
                "target_episode_id": getattr(outcome, "target_episode_id", None),
                "kind": _enum_value(getattr(outcome, "kind", None)),
                "observed_at": getattr(outcome, "observed_at", None),
                "source_event_id": getattr(outcome, "source_event_id", None),
                "source_ref_id": getattr(outcome, "source_ref_id", None),
                "actor_entity": getattr(outcome, "actor_entity", None),
                "target_entity": getattr(outcome, "target_entity", None),
                "explicitness": _enum_value(getattr(outcome, "explicitness", None)),
                "confidence": getattr(outcome, "confidence", None),
                "evidence": list(_safe_sequence(getattr(outcome, "evidence", ()))),
                "producer": getattr(outcome, "producer", None),
                "provenance": list(_safe_sequence(getattr(outcome, "provenance", ()))),
                "late_feedback": (
                    cls._is_late(outcome, episode)
                    if episode is not None
                    else None
                ),
                "human": cls._outcome_human(outcome, episode),
            }
        )

    @staticmethod
    def _is_late(outcome: object, episode: object) -> bool:
        finalized_at = getattr(episode, "finalized_at", None)
        observed_at = getattr(outcome, "observed_at", None)
        return bool(
            isinstance(finalized_at, datetime)
            and isinstance(observed_at, datetime)
            and observed_at > finalized_at
            and getattr(outcome, "target_episode_id", None) == getattr(episode, "episode_id", None)
        )

    @staticmethod
    def _episode_summary(episode: Episode, outcomes: tuple[OutcomeObservation, ...]) -> dict[str, Any]:
        return {
            "episode_id": episode.episode_id,
            "state": episode.state.value,
            "root_event_id": episode.root_event_id,
            "opened_at": _timestamp(episode.opened_at),
            "last_activity_at": _timestamp(episode.last_activity_at),
            "finalized_at": _timestamp(episode.finalized_at),
            "event_count": len(episode.event_refs),
            "outcome_count": len(outcomes),
            "topic_hint_available": bool(episode.topic_hint),
            "human": P1ObservatoryService._human_counts(episode, outcomes),
        }

    @staticmethod
    def _human_counts(episode: Episode, outcomes: tuple[OutcomeObservation, ...]) -> dict[str, Any]:
        """Return structural, read-only counts; never infer turns by division."""
        refs = episode.event_refs
        state_label = _EPISODE_STATE_LABELS.get(
            _enum_value(getattr(episode, "state", None)), "未知状态，查看工程详情"
        )
        return {
            "lifecycle_label": state_label,
            "interaction_turns": sum(_enum_value(ref.kind) == "EXPERIENCE" for ref in refs),
            "cognitive_decisions": sum(
                _enum_value(ref.kind) in {"COGNITIVE_PROPOSAL", "NO_INTENT"}
                for ref in refs
            ),
            "no_intent": sum(_enum_value(ref.kind) == "NO_INTENT" for ref in refs),
            "host_outputs": sum(_enum_value(ref.kind) == "HOST_OUTPUT" for ref in refs),
            "dispatches": sum(_enum_value(ref.kind) == "DISPATCH" for ref in refs),
            "outcomes": len(outcomes),
        }

    def _human_detail(
        self,
        episode: Episode,
        outcomes: tuple[OutcomeObservation, ...],
        review: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        attachments: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Project operational facts into labels for the simple UI view only."""
        counts = self._human_counts(episode, outcomes)
        host_attachments = [item for item in attachments if item.get("source_type") == EvidenceSourceType.HOST_RESULT.value]
        verified = sum(item.get("status") == "ATTACHED" for item in host_attachments)
        unavailable = sum(item.get("status") == "UNAVAILABLE" for item in host_attachments)
        rejected = sum(item.get("status") == "REJECTED" for item in host_attachments)
        host_total = counts["host_outputs"]
        if host_total == 0:
            host_integrity = "NO_HOST_OUTPUT"
        elif verified == host_total:
            host_integrity = "COMPLETE"
        else:
            host_integrity = "PARTIAL"
        runs = review.get("runs", [])
        review_storage = review.get("status")
        review_runs_value: int | str = (
            len(runs) if review_storage not in {"NOT_WIRED", "UNAVAILABLE"} else "Unavailable"
        )
        review_findings_value: int | str = (
            sum(len(run.get("findings", [])) for run in runs)
            if review_storage not in {"NOT_WIRED", "UNAVAILABLE"}
            else "Unavailable"
        )
        return {
            **counts,
            "shadow_observation": True,
            "host_fact_integrity": host_integrity,
            "verified_host_facts": verified,
            "unavailable_host_facts": unavailable,
            "rejected_host_facts": rejected,
            "snapshot_available": bool(snapshot.get("available")),
            "snapshot_content_frozen": bool(snapshot.get("fact_deep_snapshotted")),
            "snapshot_payload_hashed": bool(snapshot.get("fact_payload_hashed")),
            "snapshot_attachment_enforced": snapshot.get("episode_attachment") == "ENFORCED",
            "review_storage": review_storage,
            "review_status": review.get("status"),
            "review_runs": review_runs_value,
            "review_findings": review_findings_value,
            "promotion_enabled": self._state_bool("promotion_enabled"),
            "promotion_rules": list(self._state_rules()),
            "p2b_enabled": self._state_bool("p2b_enabled"),
        }

    @staticmethod
    def _episode_view(episode: Episode) -> dict[str, Any]:
        """Safe Episode view: retain structural facts, never message-topic text."""
        return {
            "episode_id": episode.episode_id,
            "scope_id": episode.scope_id,
            "state": episode.state.value,
            "root_event_id": episode.root_event_id,
            "opened_at": _timestamp(episode.opened_at),
            "last_activity_at": _timestamp(episode.last_activity_at),
            "soft_closed_at": _timestamp(episode.soft_closed_at),
            "finalized_at": _timestamp(episode.finalized_at),
            "revision": episode.revision,
            "event_refs": [P1ObservatoryService._safe_fact_view(ref) for ref in episode.event_refs],
            "unresolved_refs": list(episode.unresolved_refs),
            "topic_hint_available": bool(episode.topic_hint),
            "provenance": list(episode.provenance),
        }

    @staticmethod
    def _safe_fact_view(fact: object) -> dict[str, Any]:
        """Expose only the structural observability fields needed by the UI."""
        if isinstance(fact, EpisodeEventRef):
            return {
                "ref_id": fact.ref_id,
                "kind": fact.kind.value,
                "source_event_id": fact.source_event_id,
                "trace_id": fact.trace_id,
                "execution_record_id": fact.execution_record_id,
                "observed_at": _timestamp(fact.observed_at),
            }
        if isinstance(fact, BehaviorExecutionRecord):
            trace, host, comparison = fact.trace, fact.host_result, fact.comparison
            return {
                "trace_id": trace.trace_id,
                "event_id": trace.event_id,
                "runtime_mode": trace.runtime_mode.value,
                "created_at": _timestamp(trace.created_at),
                "stage": fact.stage.value,
                "revision": fact.revision,
                "updated_at": _timestamp(fact.updated_at),
                "host_result": {
                    "legacy_fallthrough": host.legacy_fallthrough,
                    "output_generated": host.output_generated,
                    "output_nonempty": host.output_nonempty,
                    "dispatch_observed": host.dispatch_observed,
                    "output_state": host.output_state.value,
                    "producer": host.producer.value,
                    "applied_enforcement": host.applied_enforcement.value,
                    "delivery_status": host.delivery_status.value,
                },
                "comparison": {
                    "cognitive_would_participate": comparison.cognitive_would_participate,
                    "cognitive_would_reply": comparison.cognitive_would_reply,
                    "legacy_replied": comparison.legacy_replied,
                    "legacy_output_present": comparison.legacy_output_present,
                    "divergence": comparison.divergence.value,
                },
            }
        return _json_value(fact)

    @classmethod
    def _preview_response(cls, *, eligibility: Any, run: ReviewRun | None, facts: Mapping[Any, Any], unavailable_reason: str | None = None, missing: list[str] | None = None) -> dict[str, Any]:
        return {"preview": True, "persisted": False, "eligibility": _json_value(eligibility), "run": _json_value(run) if run else None, "evidence_count": 0, "promotion": {"enabled": False, "status": "DISABLED / FAIL-CLOSED", "reason": cls.PROMOTION_REASON}, "canonical_fact_count": len(facts), "unavailable_reason": unavailable_reason, "execution_records_unavailable": missing or []}

    @staticmethod
    def _unavailable_summary() -> dict[str, Any]:
        unavailable = "Unavailable"
        return {"available": False, "reason": "episode_store_not_wired", "episodes": unavailable, "finalized_episodes": unavailable, "outcomes": unavailable, "review_runs": unavailable, "review_findings": unavailable, "review_evidence": unavailable, "review_store": "UNAVAILABLE", "review_run_count_source": unavailable, "finding_count_source": unavailable, "evidence_count_source": unavailable, "preview_available": False, "lifecycle": {"enabled": False, "status": "UNAVAILABLE"}, "review": {"enabled": False, "status": "UNAVAILABLE"}, "promotion": {"enabled": False, "status": "UNAVAILABLE", "rules": [], "rule_count": 0, "reason": "episode_store_not_wired"}, "behavioral_learning": {"enabled": False, "status": "DISABLED", "label": "P2b 尚未启用"}, "interaction_trace": {"schema_version": "p2x.interaction-observatory.v1", "available": False, "reason": "interaction_trace_not_bound"}}

    def _demo_fixture(self, case_id: str) -> tuple[Episode, tuple[OutcomeObservation, ...], dict[str, BehaviorExecutionRecord]]:
        now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
        trace = self._execution_record(event_id="demo:event")
        host_ref = EpisodeEventRef(
            f"HOST_OUTPUT:demo:event:{trace.trace.trace_id}", EpisodeEventKind.HOST_OUTPUT,
            "demo:event", trace.trace.trace_id, f"{trace.trace.trace_id}:1", now,
        )
        episode = Episode("episode:demo:root", "demo", EpisodeState.FINALIZED, "demo:event", now, now, event_refs=(host_ref,), finalized_at=now, provenance=("p1_observatory_demo",))
        records = {host_ref.ref_id: trace}
        outcomes: tuple[OutcomeObservation, ...] = ()
        if case_id in {"correction", "late-feedback"}:
            observed = now + timedelta(minutes=5) if case_id == "late-feedback" else now
            outcomes = (OutcomeObservation("outcome:demo:correction", episode.episode_id, OutcomeKind.EXPLICIT_CORRECTION, observed, source_event_id="demo:later" if case_id == "late-feedback" else "demo:reply", explicitness=OutcomeExplicitness.EXPLICIT, provenance=("p1_observatory_demo",)),)
        elif case_id == "acknowledgement":
            outcomes = (OutcomeObservation("outcome:demo:ack", episode.episode_id, OutcomeKind.EXPLICIT_ACKNOWLEDGEMENT, now, source_event_id="demo:reply", explicitness=OutcomeExplicitness.EXPLICIT, provenance=("p1_observatory_demo",)),)
        elif case_id == "silence":
            episode = Episode("episode:demo:silence", "demo", EpisodeState.FINALIZED, "demo:silence", now, now, finalized_at=now, provenance=("p1_observatory_demo",))
            records = {}
        return episode, outcomes, records

    @staticmethod
    def _execution_record(*, event_id: str) -> BehaviorExecutionRecord:
        trace = BehaviorTrace(event_id=event_id, trigger=TriggerDecision(True, "p1_observatory_demo", 1), participation=None, intent=None, grounding=None, exit_reason=None)
        host = HostResult(True, True, True, False, OutputState.OUTPUT_READY, OutputProducer.LEGACY_HOST, GroundingEnforcement.NOT_APPLIED)
        comparison = ShadowComparison(True, True, None, True, True, DivergenceType.MATCH_REPLY)
        return BehaviorExecutionRecord(trace, host, comparison, TraceStage.HOST_OUTPUT, 1)


class _DemoEpisodeStore:
    """Private read-only store facade used only for per-request demo fixtures."""
    def __init__(self, episode: Episode, outcomes: tuple[OutcomeObservation, ...]) -> None:
        self._episode, self._outcomes = episode, outcomes
    def get_episode(self, episode_id: str) -> Episode | None:
        return self._episode if episode_id == self._episode.episode_id else None
    def get_outcomes(self, episode_id: str | None = None) -> tuple[OutcomeObservation, ...]:
        return self._outcomes if episode_id in (None, self._episode.episode_id) else ()
    def all_episodes(self) -> tuple[Episode, ...]:
        return (self._episode,)
