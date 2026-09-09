"""P1b.1 runtime integration repair tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from iris_memory.cognitive.contracts import (
    CanonicalExperience,
    EntityReference,
    Perspective,
    ResolvedEvent,
)
from iris_memory.cognitive.episode import EpisodeState
from iris_memory.cognitive.episode_shadow import EpisodeShadowObserver
from iris_memory.cognitive.episode_store import (
    AppendOnlyEpisodeStore,
    EpisodeLogCorruptionError,
    InMemoryEpisodeStore,
)
from iris_memory.cognitive.iris_adapter import CognitiveRuntime
from iris_memory.cognitive.outcome import OutcomeKind
from iris_memory.tasks.scheduler import TaskScheduler


_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
_USER = EntityReference("person:qq:1", "platform_uid", 1.0, ("qq:1",))


def _exp(
    event_id: str,
    content: str,
    *,
    reply_event_id: str | None = None,
    mode: str = "private",
    session_id: str = "g1",
) -> CanonicalExperience:
    raw = {}
    if reply_event_id is not None:
        raw["reply_event_id"] = reply_event_id
    event = ResolvedEvent(
        event_id=event_id,
        source="qq",
        occurred_at=_NOW,
        session_id=session_id,
        mode=mode,
        content=content,
        actor=_USER,
        raw_metadata=raw,
    )
    return CanonicalExperience(
        id=f"experience:{event_id}",
        event=event,
        subject=_USER,
        perspective=Perspective.INTERPERSONAL,
        provenance=("test",),
    )


def test_outcome_collector_is_invoked_on_attached_feedback():
    store = InMemoryEpisodeStore()
    observer = EpisodeShadowObserver(store)
    runtime = CognitiveRuntime(episode_observer=observer)

    runtime.run_behavior(_exp("qq:q1", "今晚几点观测？"))
    ep = store.all_episodes()[0]

    runtime.run_behavior(
        _exp("qq:thanks", "谢谢", reply_event_id="qq:q1")
    )
    kinds = {o.kind for o in store.get_outcomes(ep.episode_id)}
    assert OutcomeKind.EXPLICIT_ACKNOWLEDGEMENT in kinds


def test_finalized_late_feedback_creates_current_episode_and_targets_old():
    store = InMemoryEpisodeStore()
    observer = EpisodeShadowObserver(store)
    runtime = CognitiveRuntime(episode_observer=observer)

    runtime.run_behavior(_exp("qq:old", "昨天那个望远镜可以吗？"))
    old = store.all_episodes()[0]
    old = store.transition_state(old.episode_id, EpisodeState.SOFT_CLOSED, reason="idle")
    old = store.transition_state(old.episode_id, EpisodeState.FINALIZED, reason="grace")
    old_refs = old.event_refs

    runtime.run_behavior(
        _exp("qq:today", "你昨天说的那个不对", reply_event_id="qq:old")
    )

    after = store.get_episode(old.episode_id)
    assert after is not None
    assert after.state is EpisodeState.FINALIZED
    assert after.event_refs == old_refs

    episodes = [ep for ep in store.all_episodes() if ep.episode_id != old.episode_id]
    assert len(episodes) == 1
    kinds = {o.kind for o in store.get_outcomes(old.episode_id)}
    assert OutcomeKind.EXPLICIT_CORRECTION in kinds


def test_finalized_reply_is_not_hijacked_by_unique_open_private_episode():
    store = InMemoryEpisodeStore()
    observer = EpisodeShadowObserver(store)
    runtime = CognitiveRuntime(episode_observer=observer)

    runtime.run_behavior(_exp("qq:open", "当前私聊问题", session_id="private:1"))
    open_episode = store.all_episodes()[0]
    old = store.transition_state(open_episode.episode_id, EpisodeState.SOFT_CLOSED, reason="idle")
    old = store.transition_state(old.episode_id, EpisodeState.FINALIZED, reason="grace")
    runtime.run_behavior(_exp("qq:current", "新的当前问题", session_id="private:1"))
    current_open = next(episode for episode in store.all_episodes() if episode.state is EpisodeState.OPEN)

    runtime.run_behavior(
        _exp(
            "qq:feedback",
            "你刚才那个不对",
            reply_event_id="qq:open",
            session_id="private:1",
        )
    )

    assert store.get_episode(current_open.episode_id) == current_open
    historical = store.get_episode(old.episode_id)
    assert historical is not None and historical.state is EpisodeState.FINALIZED
    assert OutcomeKind.EXPLICIT_CORRECTION in {
        outcome.kind for outcome in store.get_outcomes(old.episode_id)
    }
    new_episodes = [
        episode
        for episode in store.all_episodes()
        if episode.episode_id not in {old.episode_id, current_open.episode_id}
    ]
    assert len(new_episodes) == 1


def test_orphan_outcome_is_rejected():
    store = InMemoryEpisodeStore()
    from iris_memory.cognitive.outcome import (
        OutcomeObservation,
        make_outcome_observation_id,
    )

    outcome = OutcomeObservation(
        observation_id=make_outcome_observation_id(
            "ep:missing",
            OutcomeKind.EXPLICIT_CORRECTION,
            source_event_id="qq:1",
        ),
        target_episode_id="ep:missing",
        kind=OutcomeKind.EXPLICIT_CORRECTION,
        observed_at=_NOW,
        source_event_id="qq:1",
    )
    with pytest.raises(ValueError):
        store.record_outcome(outcome)


def test_mid_log_corruption_is_not_silently_skipped(tmp_path):
    from iris_memory.cognitive.episode import (
        Episode,
        EpisodeEventKind,
        EpisodeEventRef,
        EpisodeState,
        make_episode_id,
    )

    path = tmp_path / "episodes.jsonl"
    store = AppendOnlyEpisodeStore(path)
    ep = Episode(
        episode_id=make_episode_id("g1", "qq:1"),
        scope_id="g1",
        state=EpisodeState.OPEN,
        root_event_id="qq:1",
        opened_at=_NOW,
        last_activity_at=_NOW,
    )
    store.create_episode(ep)
    store.append_event_ref(
        ep.episode_id,
        EpisodeEventRef(
            ref_id="EXPERIENCE:qq:1",
            kind=EpisodeEventKind.EXPERIENCE,
            source_event_id="qq:1",
            observed_at=_NOW,
        ),
    )
    # Corrupt middle line, followed by another valid operation.
    with path.open("a", encoding="utf-8") as f:
        f.write("{bad-json}\n")
    # Trigger a second valid operation line after corruption.
    store.create_episode(
        Episode(
            episode_id=make_episode_id("g1", "qq:2"),
            scope_id="g1",
            state=EpisodeState.OPEN,
            root_event_id="qq:2",
            opened_at=_NOW,
            last_activity_at=_NOW,
        )
    )
    with pytest.raises(EpisodeLogCorruptionError):
        AppendOnlyEpisodeStore(path)


def test_main_episode_observer_wiring_helper(tmp_path, monkeypatch):
    import main
    from iris_memory.cognitive.iris_adapter import get_cognitive_runtime, reset_cognitive_runtime

    reset_cognitive_runtime()
    plugin = object.__new__(main.IrisMemoryPlugin)
    plugin.data_dir = str(tmp_path)
    plugin._episode_store = None
    plugin._episode_observer = None
    plugin._init_episode_shadow_observer()
    assert plugin._episode_store is not None
    assert plugin._episode_observer is not None
    assert get_cognitive_runtime().episode_observer is not None
    # Avoid cross-test pollution.
    get_cognitive_runtime().episode_observer = None
    reset_cognitive_runtime()


@pytest.mark.asyncio
async def test_main_binds_owner_projections_to_observatory_runtime():
    """The production request collector is the only source for runtime details."""
    import main
    from iris_memory.cognitive.iris_adapter import (
        get_cognitive_runtime,
        reset_cognitive_runtime,
    )
    from iris_memory.web.routes import observatory as observatory_routes

    reset_cognitive_runtime()
    runtime = get_cognitive_runtime()
    now = 1_000_000.0

    class PreferenceStorage:
        async def active_response_preference_records_for_event(self, _event):
            return [
                SimpleNamespace(
                    parameter="response_length",
                    value="PRIVATE_VALUE",
                    candidate_id="PRIVATE_CANDIDATE",
                    scope=SimpleNamespace(
                        to_dict=lambda: {
                            "user_id": "PRIVATE_USER",
                            "conversation_id": "PRIVATE_SCOPE",
                        }
                    ),
                    source=SimpleNamespace(
                        source_kind="EXPLICIT_CONTROLLED_REQUEST",
                        source_event_id="PRIVATE_EVENT",
                    ),
                    status="APPROVED",
                    requested_at=now - 10,
                    approved_at=now - 5,
                    expires_at=now + 60,
                    revoked_at=None,
                    suspended_reason=None,
                    display_status=lambda timestamp: "APPROVED" if timestamp < now + 60 else "EXPIRED",
                )
            ]

    class FeedbackItem:
        evidence_state = "ACTIVE"

        def __init__(self):
            self.occurred_at = datetime.fromtimestamp(now - 2, timezone.utc)

    class Event:
        message_str = ""

        def get_sender_id(self):
            return "fictional-user"

        def get_extra(self, key):
            return (
                {
                    "schema": "iris.affect-view.v1",
                    "owner": "astrbot_plugin_affection",
                    "user_id": "fictional-user",
                    "scope": "PRIVATE_SCOPE",
                    "generated_at": now - 1,
                    "expires_at": now + 60,
                    "towards_user": "warm",
                    "self_state": "steady",
                    "affection": 99,
                    "prompt": "PRIVATE_PROMPT",
                }
                if key == "iris_affect_view_v1"
                else None
            )

    class EmptyEvent(Event):
        def get_extra(self, key):
            return (
                {
                    "schema": "iris.affect-view.v1",
                    "owner": "astrbot_plugin_affection",
                    "user_id": "fictional-user",
                    "generated_at": now - 120,
                    "expires_at": now - 60,
                    "towards_user": "expired",
                }
                if key == "iris_affect_view_v1"
                else None
            )

    class EmptyStorage:
        async def active_response_preference_records_for_event(self, _event):
            return []

    plugin = object.__new__(main.IrisMemoryPlugin)
    plugin.config = SimpleNamespace(get=lambda _key, default=None: default)
    plugin._episode_lifecycle_owner = None
    plugin._episode_lifecycle_registered = False
    plugin._production_review_store = None
    plugin._production_review_completion = None
    plugin._production_review_evidence_enabled = False
    plugin._production_semantic_evaluator = None
    plugin._p2r0_archive = None
    plugin._interaction_trace_observatory = None
    plugin._response_length_feedback = SimpleNamespace(
        available=True,
        observations=(FeedbackItem(),),
    )
    plugin._p2b_shadow_store = None
    plugin._p2b_shadow_last_evaluation_at = None
    plugin._get_response_preference_storage = lambda: PreferenceStorage()

    try:
        plugin._sync_observatory_runtime_state()
        await plugin._collect_cognitive_runtime_views(Event())
        detail = observatory_routes.get_observatory_service().runtime_detail(now=now)

        assert runtime.observatory_affect_snapshot["towards_user"] == "warm"
        assert runtime.observatory_affect_snapshot["self_state"] == "steady"
        assert runtime.observatory_affect_snapshot["affection"] == 99.0
        assert "user_id" not in runtime.observatory_affect_snapshot
        assert runtime.observatory_response_preference_records[0]["parameter"] == "response_length"
        assert "value" not in runtime.observatory_response_preference_records[0]
        assert runtime.observatory_projection_details["behavioral_prior"]["parameters"] == [
            "response_length"
        ]
        assert runtime.observatory_feedback_detail["evidence_states"]["ACTIVE"] == 1
        assert detail["details"]["affect"]["status"] == "AVAILABLE"
        assert detail["details"]["affect"]["labels"] == {
            "towards_user": "warm",
            "self_state": "steady",
        }
        assert detail["details"]["response_preferences"]["status"] == "AVAILABLE"
        assert detail["details"]["behavioral_prior"]["status"] == "AVAILABLE"
        assert detail["details"]["behavioral_prior"]["source_kind"] == "ProfileStorage"
        assert detail["details"]["feedback_replay"]["evidence_states"] == {
            "ACTIVE": 1,
            "REVOKED": 0,
            "CONFLICTED": 0,
        }
        encoded = json.dumps(detail, ensure_ascii=False)
        for secret in (
            "PRIVATE_USER",
            "PRIVATE_SCOPE",
            "PRIVATE_VALUE",
            "PRIVATE_CANDIDATE",
            "PRIVATE_EVENT",
            "PRIVATE_PROMPT",
        ):
            assert secret not in encoded

        plugin._get_response_preference_storage = lambda: EmptyStorage()
        await plugin._collect_cognitive_runtime_views(EmptyEvent())
        expired_detail = observatory_routes.get_observatory_service().runtime_detail(now=now)
        assert runtime.observatory_response_preference_records == []
        assert runtime.observatory_affect_snapshot["expires_at"] == now - 60
        assert expired_detail["details"]["affect"]["status"] == "EXPIRED"
        assert expired_detail["details"]["response_preferences"]["status"] == "EMPTY"
    finally:
        reset_cognitive_runtime()


@pytest.mark.asyncio
async def test_main_episode_lifecycle_uses_shared_scheduler_once_and_stops(monkeypatch):
    import main

    scheduler = TaskScheduler()
    await scheduler.initialize()
    config_values = {"episode_lifecycle.auto_finalize": True}

    class _Config:
        def get(self, key, default=None):
            return config_values.get(key, default)

    owner = SimpleNamespace(
        max_episodes_per_scan=7,
        running=False,
        run_scheduled_scan=AsyncMock(),
    )
    plugin = object.__new__(main.IrisMemoryPlugin)
    plugin.config = _Config()
    plugin.component_manager = SimpleNamespace(
        get_component=lambda name: scheduler if name == "scheduler" else None
    )
    plugin._episode_lifecycle_owner = owner
    plugin._episode_lifecycle_scheduler = None
    plugin._episode_lifecycle_registered = False
    monkeypatch.setattr(plugin, "_sync_observatory_runtime_state", lambda: None)

    try:
        with patch("iris_memory.tasks.scheduler.random.uniform", return_value=1.0):
            await asyncio.gather(
                plugin._start_episode_lifecycle_owner(),
                plugin._start_episode_lifecycle_owner(),
            )

        assert scheduler.is_task_registered(main.EPISODE_LIFECYCLE_TASK_NAME) is True
        assert owner.running is False
        assert list(
            name
            for name in scheduler._tasks
            if name == main.EPISODE_LIFECYCLE_TASK_NAME
        ) == [main.EPISODE_LIFECYCLE_TASK_NAME]

        config_values["episode_lifecycle.auto_finalize"] = False
        await plugin._start_episode_lifecycle_owner()
        assert scheduler.is_task_registered(main.EPISODE_LIFECYCLE_TASK_NAME) is False
        assert scheduler.is_available is True
    finally:
        await scheduler.shutdown()
