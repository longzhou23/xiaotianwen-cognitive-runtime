"""Authenticated, read-only Cognitive Observatory endpoints."""

from __future__ import annotations

from quart import jsonify, request

from iris_memory.cognitive.iris_adapter import get_cognitive_runtime
from iris_memory.web.services import P1ObservatoryService

PLUGIN_NAME = "astrbot_plugin_iris_memory"


def get_observatory_service() -> P1ObservatoryService:
    runtime = get_cognitive_runtime()
    observer = runtime.episode_observer
    feedback = getattr(runtime, "observatory_feedback_observer", None)
    p2b_store = getattr(runtime, "observatory_p2b_shadow_store", None)
    registry = getattr(runtime, "registry", None)
    try:
        registry_available = registry is not None and getattr(registry, "available", True) is True
        entity_count = len(registry.entities()) if registry_available else None
        claim_count = len(registry.all_claims()) if registry_available else None
    except Exception:
        registry_available = False
        entity_count = claim_count = None
    return P1ObservatoryService(
        getattr(observer, "store", None),
        review_store=getattr(runtime, "observatory_review_store", None),
        p2r0_store=getattr(runtime, "observatory_p2r0_store", None),
        execution_observatory=getattr(runtime, "execution_observatory", None),
        interaction_trace_reader=getattr(runtime, "observatory_interaction_trace", None),
        runtime_state={
            "lifecycle_enabled": getattr(runtime, "observatory_lifecycle_enabled", False),
            "review_enabled": getattr(runtime, "observatory_review_enabled", False),
            "promotion_enabled": getattr(runtime, "observatory_promotion_enabled", False),
            "promotion_rules": getattr(runtime, "observatory_promotion_rules", ()),
            "semantic_evaluator": getattr(runtime, "observatory_semantic_evaluator", None),
            "p2b_enabled": getattr(runtime, "observatory_p2b_enabled", False),
            "host_cas_available": getattr(runtime, "observatory_host_cas_available", False),
            "feedback_available": bool(getattr(feedback, "available", False)),
            "feedback_observations": len(getattr(feedback, "observations", ())),
            "identity_available": registry_available and entity_count is not None and claim_count is not None,
            "identity_entities": entity_count,
            "identity_claims": claim_count,
            "identity_registry": registry,
            # Affect snapshots are accepted only when another owner explicitly
            # publishes the existing versioned, TTL-bound sanitized carrier.
            "affect_snapshot": getattr(runtime, "observatory_affect_snapshot", None),
            "projection_details": getattr(runtime, "observatory_projection_details", None),
            "response_preference_records": getattr(runtime, "observatory_response_preference_records", None),
            "feedback_detail": getattr(runtime, "observatory_feedback_detail", None),
            "projection_counts": dict(getattr(runtime, "observatory_projection_counts", {})),
            "last_projection_at": getattr(runtime, "observatory_last_projection_at", None),
            "p2b_shadow_store": p2b_store,
            "p2b_shadow_last_evaluation_at": getattr(
                runtime, "observatory_p2b_shadow_last_evaluation_at", None
            ),
        },
    )


async def observatory_summary():
    return jsonify({"success": True, "summary": get_observatory_service().summary()})


async def observatory_runtime_detail():
    try:
        return jsonify({"success": True, "detail": get_observatory_service().runtime_detail()})
    except (TypeError, ValueError):
        # A malformed optional owner projection is rendered as unavailable by
        # the service; this boundary protects the endpoint if its clock input
        # or host object is itself invalid.
        return jsonify({"success": False, "error": "runtime detail unavailable"}), 503


async def observatory_episodes():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        payload = get_observatory_service().list_episodes(state=request.args.get("state"), query=request.args.get("query"), limit=limit, offset=offset)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


async def observatory_episode_detail(episode_id: str):
    try:
        return jsonify({"success": True, **get_observatory_service().episode_detail(episode_id)})
    except KeyError:
        return jsonify({"success": False, "error": "episode not found"}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


async def observatory_preview(episode_id: str):
    try:
        return jsonify({"success": True, **get_observatory_service().preview_review(episode_id)})
    except KeyError:
        return jsonify({"success": False, "error": "episode not found"}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


async def observatory_demo_cases():
    return jsonify({"success": True, "demo": True, "cases": get_observatory_service().demo_cases()})


async def observatory_demo_case(case_id: str):
    try:
        return jsonify({"success": True, **get_observatory_service().demo_case(case_id)})
    except KeyError:
        return jsonify({"success": False, "error": "demo case not found"}), 404


def register_observatory_routes(context) -> None:
    prefix = f"/{PLUGIN_NAME}/cognitive-observatory"
    for route, handler, methods, description in [
        (f"{prefix}/summary", observatory_summary, ["GET"], "获取认知观测台摘要"),
        (f"{prefix}/runtime-detail", observatory_runtime_detail, ["GET"], "获取运行态脱敏详情"),
        (f"{prefix}/episodes", observatory_episodes, ["GET"], "获取 Episode 列表"),
        (f"{prefix}/episodes/<episode_id>", observatory_episode_detail, ["GET"], "获取 Episode 详情"),
        (f"{prefix}/episodes/<episode_id>/preview", observatory_preview, ["POST"], "预览 Review（不持久化）"),
        (f"{prefix}/demo-cases", observatory_demo_cases, ["GET"], "获取 P1 演示案例"),
        (f"{prefix}/demo-cases/<case_id>", observatory_demo_case, ["GET"], "获取 P1 演示案例详情"),
    ]:
        context.register_web_api(route, handler, methods, description)
