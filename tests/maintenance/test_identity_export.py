from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from deploy.maintenance.identity_export import export_history, write_export
from deploy.maintenance.identity_rebuild import (
    CanonicalEntity,
    EntityRegistry,
    IdentityClaim,
    IdentityClaimStatus,
    IdentityConfig,
    make_plan,
)


def _jsonl(path: Path, records: list[dict]) -> None:
    path.write_bytes(b"".join(json.dumps(record, separators=(",", ":")).encode() + b"\n" for record in records))


def _identity(*, role: str = "user", platform: str = "qq", account_id: str = "acct", uid: str = "1001", entity_id: str | None = None) -> dict:
    value = {"role": role, "platform": platform, "account_id": account_id, "uid": uid}
    if entity_id is not None:
        value["entity_id"] = entity_id
    return value


def _p2r0_account(platform: str = "qq", account_id: str = "bot-account") -> dict:
    return {
        "payload": {
            "fields": {
                "source_platform_message_identity": {
                    "fields": {"platform_id": platform, "account_id": account_id}
                }
            }
        }
    }


def test_episode_export_requires_explicit_account_and_role_and_dedupes_uid(tmp_path: Path):
    episodes = tmp_path / "episodes.jsonl"
    _jsonl(
        episodes,
        [
            {"payload": {"participants": [_identity(uid="1001")]}},
            {"payload": {"participants": [_identity(uid="1001")]}},
            {"payload": {"participants": [_identity(platform="onebot", uid="1001")]}},
            {"payload": {"participants": [{"entity_id": "person:qq:1002", "source": "platform_uid"}]}},
        ],
    )
    result = export_history(episode_path=episodes, authorization_ref="fixture-auth")
    entities = [record for record in result.document["records"] if record["kind"] == "entity"]
    assert {record["payload"]["id"] for record in entities} == {"person:qq:1001", "person:onebot:1001"}
    assert result.report["counts"]["accepted"] == 2
    assert result.report["skipped_categories"]["ROLE_UNDECLARED"] == 1
    assert all("content" not in record for record in result.document["records"])


def test_event_and_message_ids_are_never_treated_as_user_uid(tmp_path: Path):
    p2r0 = tmp_path / "facts.jsonl"
    p2r1 = tmp_path / "authority.jsonl"
    trap = {
        "payload": {
            "platform_id": "qq",
            "account_id": "bot-account",
            "conversation_id": "conversation-uid-looking",
            "message_id": "message-uid-looking",
            "source_event_id": "event-uid-looking",
            "trace_id": "trace-uid-looking",
        },
        "content": {"uid": "must-not-be-read"},
    }
    _jsonl(p2r0, [trap])
    _jsonl(p2r1, [trap])
    result = export_history(p2r0_path=p2r0, p2r1_path=p2r1, authorization_ref="fixture-auth")
    assert result.document["records"] == []
    assert result.report["counts"]["accepted"] == 0
    assert result.report["skipped_categories"]["NO_EXPLICIT_USER_UID_FIELD"] == 2
    assert result.report["safety"]["message_identity_fields_used_as_user_uid"] is False
    assert result.report["safety"]["message_content_read"] is False


def test_consistent_self_binding_emits_one_observation_group_and_conflict_blocks(tmp_path: Path):
    episodes = tmp_path / "episodes.jsonl"
    _jsonl(
        episodes,
        [
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
        ],
    )
    result = export_history(episode_path=episodes, authorization_ref="fixture-auth")
    bindings = [record for record in result.document["records"] if record["kind"] == "self_binding"]
    assert len(bindings) == 1
    assert bindings[0]["payload"]["platform_id"] == "9000"
    assert result.report["counts"]["self_bindings_emitted"] == 1
    assert result.report["apply_blocked"] is False

    conflict = tmp_path / "conflict.jsonl"
    _jsonl(
        conflict,
        [
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
            {"payload": {"sender_identity": _identity(role="self", uid="9001", entity_id="agent:xiaotianwen")}},
        ],
    )
    blocked = export_history(episode_path=conflict, authorization_ref="fixture-auth")
    assert blocked.document["records"] == []
    assert blocked.report["conflict_categories"] == {"SELF_BINDING_CONFLICT": 2}
    assert blocked.report["apply_blocked"] is True


def test_confirmed_claim_can_be_exported_but_possible_claim_is_skipped(tmp_path: Path):
    identity = tmp_path / "identity.json"
    registry = EntityRegistry(IdentityConfig(self_aliases=()), storage_path=identity)
    registry.register_entity(
        CanonicalEntity("person:qq:1001", platform_ids={"qq": "1001"}),
        source="fixture",
    )
    registry.add_claim(
        IdentityClaim(
            mention="confirmed",
            candidate_entity="person:qq:1001",
            evidence=("fixture:evidence",),
            confidence=1.0,
            source="admin:fixture",
            status=IdentityClaimStatus.CONFIRMED,
            created_at=datetime.fromisoformat("2026-09-10T00:00:00+00:00"),
        )
    )
    registry.add_claim(
        IdentityClaim(
            mention="possible",
            candidate_entity="person:qq:1001",
            evidence=("fixture:evidence",),
            confidence=0.4,
            source="model:fixture",
            status=IdentityClaimStatus.POSSIBLE,
            created_at=datetime.fromisoformat("2026-09-10T00:00:00+00:00"),
        )
    )
    result = export_history(identity_registry_path=identity, authorization_ref="fixture-auth")
    aliases = [record["payload"]["mention"] for record in result.document["records"]]
    assert aliases == ["confirmed"]
    assert result.report["skipped_categories"]["UNCONFIRMED_ALIAS_SKIPPED"] == 1


def test_export_is_private_and_planner_accepts_contract(tmp_path: Path):
    episodes = tmp_path / "episodes.jsonl"
    _jsonl(
        episodes,
        [
            {"payload": {"participants": [_identity(uid="1001")]}},
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
        ],
    )
    current = tmp_path / "current.json"
    EntityRegistry(IdentityConfig(self_aliases=()), storage_path=current)
    result = export_history(episode_path=episodes, authorization_ref="fixture-auth")
    source, report = write_export(result, tmp_path / "private" / "source.json")
    assert source.exists() and report.exists()
    if os.name != "nt":
        assert source.parent.stat().st_mode & 0o777 == 0o700
        assert source.stat().st_mode & 0o777 == 0o600
        assert report.stat().st_mode & 0o777 == 0o600
    planned = make_plan(current, [source])
    assert planned.manifest["counts"]["accepted"] == 2
    assert planned.manifest["apply_blocked"] is False
    assert hashlib.sha256(episodes.read_bytes()).hexdigest() == result.report["inputs"][0]["sha256"]


def test_export_conflict_is_carried_into_planner_fail_closed(tmp_path: Path):
    episodes = tmp_path / "episodes.jsonl"
    _jsonl(
        episodes,
        [
            {"payload": {"sender_identity": _identity(role="self", uid="9000", entity_id="agent:xiaotianwen")}},
            {"payload": {"sender_identity": _identity(role="self", uid="9001", entity_id="agent:xiaotianwen")}},
        ],
    )
    current = tmp_path / "current.json"
    EntityRegistry(IdentityConfig(self_aliases=()), storage_path=current)
    result = export_history(episode_path=episodes, authorization_ref="fixture-auth")
    source, _ = write_export(result, tmp_path / "private" / "source.json")
    plan = make_plan(current, [source])
    assert plan.manifest["apply_blocked"] is True
    assert any(
        item["category"] == "EXPORT_PREFLIGHT_SELF_BINDING_CONFLICT"
        for item in plan.manifest["conflicts"]
    )


def test_astrbot_history_uses_sender_id_and_inherits_p2r0_account_without_reading_content(tmp_path: Path):
    p2r0 = tmp_path / "facts.jsonl"
    _jsonl(p2r0, [_p2r0_account(), _p2r0_account()])
    db_path = tmp_path / "data_v4.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE platform_message_history "
        "(id INTEGER PRIMARY KEY, platform_id TEXT, user_id TEXT, sender_id TEXT, content TEXT)"
    )
    connection.executemany(
        "INSERT INTO platform_message_history(id, platform_id, user_id, sender_id, content) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "qq", "group-scope", "1001", "not-json-and-never-read"),
            (2, "qq", "group-scope", "1001", "not-json-and-never-read"),
            (3, "qq", "group-scope", "1002", "not-json-and-never-read"),
            (4, "qq", "group-scope", "bot-account", "not-json-and-never-read"),
            (5, "webchat", "private-scope", "web-user", "not-json-and-never-read"),
        ],
    )
    connection.commit()
    connection.close()
    result = export_history(
        p2r0_path=p2r0,
        astrbot_db_path=db_path,
        authorization_ref="fixture-auth",
    )
    entities = [record for record in result.document["records"] if record["kind"] == "entity"]
    assert {record["payload"]["id"] for record in entities} == {"person:qq:1001", "person:qq:1002"}
    assert result.report["counts"]["self_bindings_emitted"] == 1
    assert result.report["skipped_categories"]["MISSING_ACCOUNT_CONTEXT"] == 1
    assert result.report["skipped_categories"]["SELF_ACCOUNT_ROW"] == 1
    assert all(record["provenance"]["field_path"] == "platform_message_history.sender_id" for record in entities)
    assert all(
        any(ref.startswith("record:") for ref in record["provenance"]["evidence_refs"])
        for record in entities
    )
    binding_hash = hashlib.sha256(p2r0.read_bytes().splitlines(keepends=True)[0]).hexdigest()
    assert all(
        f"record:{binding_hash}" in record["provenance"]["evidence_refs"]
        for record in entities
    )
    assert result.report["inputs"][-1]["content_column_read"] is False


def test_astrbot_account_context_conflict_blocks_history_records(tmp_path: Path):
    p2r0 = tmp_path / "facts.jsonl"
    _jsonl(p2r0, [_p2r0_account(account_id="bot-a"), _p2r0_account(account_id="bot-b")])
    db_path = tmp_path / "data_v4.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE platform_message_history "
        "(id INTEGER PRIMARY KEY, platform_id TEXT, user_id TEXT, sender_id TEXT, content TEXT)"
    )
    connection.execute(
        "INSERT INTO platform_message_history(id, platform_id, user_id, sender_id, content) VALUES (1, 'qq', 'scope', '1001', 'unused')"
    )
    connection.commit()
    connection.close()
    result = export_history(
        p2r0_path=p2r0,
        astrbot_db_path=db_path,
        authorization_ref="fixture-auth",
    )
    assert result.report["apply_blocked"] is True
    assert result.report["conflict_categories"]["SELF_BINDING_CONFLICT"] == 2
    assert result.report["conflict_categories"]["ACCOUNT_BINDING_CONFLICT"] == 1
    assert not [record for record in result.document["records"] if record["kind"] == "entity"]
