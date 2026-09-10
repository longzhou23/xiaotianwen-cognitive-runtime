from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from deploy.maintenance.identity_rebuild import (
    EntityRegistry,
    IdentityConfig,
    RebuildError,
    _guarded_replace,
    _owner_lock,
    main,
    make_plan,
    write_plan,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current(path: Path) -> None:
    EntityRegistry(IdentityConfig(self_aliases=()), storage_path=path)


def _provenance(source_type: str = "platform_session", basis: str = "platform_uid") -> dict:
    return {
        "source_type": source_type,
        "source_ref": "fixture:source",
        "basis": basis,
        "evidence_refs": ["fixture:evidence"],
        "field_path": "fixture.payload.identity",
        "record_hash": "a" * 64,
        "role": "self" if basis == "self_binding" else "user",
        "account_id": "fixture-account",
        "platform": "qq",
        "uid": "9000",
    }


def _source(*records: dict, authorized: bool = True) -> dict:
    return {
        "schema": "iris.identity-rebuild-source.v1",
        "authorization": {
            "authorized": authorized,
            "scope": "identity-rebuild",
            "authorization_ref": "fixture:authorization",
        },
        "records": list(records),
        "scan": {"apply_blocked": False, "conflicts": []},
    }


def _record(kind: str, payload: dict, *, source_type: str = "platform_session", basis: str | None = None) -> dict:
    return {
        "kind": kind,
        "record_ref": f"fixture:{kind}:{len(payload)}",
        "payload": payload,
        "provenance": _provenance(source_type, basis or ("platform_uid" if kind == "entity" else "self_binding" if kind == "self_binding" else "manual_confirmed_alias")),
    }


def _self_binding() -> dict:
    return _record(
        "self_binding",
        {"entity_id": "agent:xiaotianwen", "platform": "qq", "platform_id": "9000"},
    )


def _entity(entity_id: str, platform: str, uid: str) -> dict:
    return _record(
        "entity",
        {"id": entity_id, "aliases": [], "platform_ids": {platform: uid}},
    )


def _alias(mention: str, entity_id: str, *, status: str = "CONFIRMED") -> dict:
    return _record(
        "alias",
        {
            "mention": mention,
            "candidate_entity": entity_id,
            "evidence": ["fixture:manual-confirmation"],
            "confidence": 1.0 if status == "CONFIRMED" else 0.4,
            "source": "admin:fixture",
            "status": status,
            "created_at": "2026-09-10T00:00:00+00:00",
        },
        source_type="manual_confirmed_claim",
        basis="manual_confirmed_alias",
    )


def _write_source(path: Path, *records: dict, authorized: bool = True) -> None:
    path.write_text(json.dumps(_source(*records, authorized=authorized), ensure_ascii=False), encoding="utf-8")


def test_plan_reuses_uid_identity_and_keeps_platforms_and_unconfirmed_aliases_separate(tmp_path: Path):
    current = tmp_path / "current.json"
    source = tmp_path / "source.json"
    _current(current)
    _write_source(
        source,
        _self_binding(),
        _entity("person:qq-one", "qq", "1001"),
        _entity("person:onebot-one", "onebot", "1001"),
        _entity("person:qq-two", "qq", "1002"),
        _alias("confirmed-name", "person:qq-one"),
        _alias("possible-name", "person:qq-two", status="POSSIBLE"),
    )

    result = make_plan(current, [source])
    assert result.manifest["apply_blocked"] is False
    assert result.manifest["counts"] == {
        "entities_before": 1,
        "entities_after": 4,
        "claims_before": 0,
        "claims_after": 1,
        "source_records": 6,
        "accepted": 5,
        "conflicts": 0,
        "skipped": 1,
    }
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(result.candidate_bytes)
    registry = EntityRegistry(storage_path=candidate)
    assert registry.available
    assert registry.resolve_platform_id("qq", "1001").entity_id == "person:qq-one"
    assert registry.resolve_platform_id("onebot", "1001").entity_id == "person:onebot-one"
    assert registry.resolve_platform_id("qq", "1002").entity_id == "person:qq-two"
    assert registry.resolve_alias("confirmed-name").entity_id == "person:qq-one"
    assert registry.resolve_alias("possible-name") is None


def test_alias_conflict_is_preserved_but_blocks_apply_and_resolves_fail_closed(tmp_path: Path):
    current = tmp_path / "current.json"
    source = tmp_path / "source.json"
    _current(current)
    _write_source(
        source,
        _self_binding(),
        _entity("person:first", "qq", "2001"),
        _entity("person:second", "qq", "2002"),
        _alias("ambiguous", "person:first"),
        _alias("ambiguous", "person:second"),
    )
    result = make_plan(current, [source])
    assert result.manifest["apply_blocked"] is True
    assert any(item["category"] == "CONFIRMED_ALIAS_CONFLICT" for item in result.manifest["conflicts"])
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(result.candidate_bytes)
    assert EntityRegistry(storage_path=candidate).resolve_alias("ambiguous") is None


@pytest.mark.parametrize(
    "document",
    [
        {"schema": "wrong", "authorization": {}, "records": []},
        {"schema": "iris.identity-rebuild-source.v1", "authorization": {"authorized": False, "scope": "identity-rebuild", "authorization_ref": "x"}, "records": []},
        {"schema": "iris.identity-rebuild-source.v1", "authorization": {"authorized": True, "scope": "identity-rebuild", "authorization_ref": "x"}, "records": [{"kind": "entity"}]},
    ],
)
def test_invalid_or_unauthorized_source_fails_closed(tmp_path: Path, document: dict):
    current = tmp_path / "current.json"
    source = tmp_path / "source.json"
    _current(current)
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RebuildError):
        make_plan(current, [source])


def test_corrupt_or_version_mismatched_current_is_rejected(tmp_path: Path):
    current = tmp_path / "current.json"
    current.write_text('{"payload": {"schema": "wrong"}}', encoding="utf-8")
    with pytest.raises(RebuildError):
        make_plan(current, [])


def test_dry_run_writes_private_outputs_and_never_changes_target(tmp_path: Path):
    current = tmp_path / "current.json"
    source = tmp_path / "source.json"
    output = tmp_path / "private-plan"
    _current(current)
    _write_source(source, _self_binding(), _entity("person:qq-one", "qq", "3001"))
    before = current.read_bytes()
    result = make_plan(current, [source])
    candidate, manifest = write_plan(result, output)
    assert current.read_bytes() == before
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o700
        assert candidate.stat().st_mode & 0o777 == 0o600
        assert manifest.stat().st_mode & 0o777 == 0o600
    assert json.loads(manifest.read_text(encoding="utf-8"))["candidate"]["sha256"] == _sha256(candidate)


def test_precondition_conflict_does_zero_write(tmp_path: Path):
    target = tmp_path / "identity.json"
    candidate = tmp_path / "candidate.json"
    lock = tmp_path / "owner.lock"
    _current(target)
    candidate.write_bytes(target.read_bytes() + b"\n")
    before = target.read_bytes()
    with pytest.raises(RebuildError, match="precondition"):
        _guarded_replace(
            target=target,
            replacement=candidate.read_bytes(),
            expected_sha256="0" * 64,
            lock_path=lock,
            confirm="CONFIRM",
        )
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("identity.json.backup.*"))


def test_atomic_apply_backup_restore_and_restart_replay(tmp_path: Path):
    target = tmp_path / "identity.json"
    source = tmp_path / "source.json"
    output = tmp_path / "plan"
    lock = tmp_path / "owner.lock"
    _current(target)
    _write_source(source, _self_binding(), _entity("person:qq-one", "qq", "4001"), _alias("stable", "person:qq-one"))
    result = make_plan(target, [source])
    candidate, _ = write_plan(result, output)
    before_hash = _sha256(target)
    backup = _guarded_replace(
        target=target,
        replacement=candidate.read_bytes(),
        expected_sha256=before_hash,
        lock_path=lock,
        confirm="CONFIRM",
    )
    assert backup.exists()
    assert _sha256(backup) == before_hash
    restarted = EntityRegistry(storage_path=target)
    assert restarted.available
    assert restarted.resolve_alias("stable").entity_id == "person:qq-one"
    applied_hash = _sha256(target)
    restored_backup = _guarded_replace(
        target=target,
        replacement=backup.read_bytes(),
        expected_sha256=applied_hash,
        lock_path=lock,
        confirm="CONFIRM",
    )
    assert restored_backup.exists()
    assert _sha256(target) == before_hash
    assert EntityRegistry(storage_path=target).resolve_alias("stable") is None


def test_owner_lock_contention_and_invalid_candidate_leave_target_untouched(tmp_path: Path):
    target = tmp_path / "identity.json"
    lock = tmp_path / "owner.lock"
    _current(target)
    before = target.read_bytes()
    with _owner_lock(lock), pytest.raises(RebuildError, match="owner lock"):
        _guarded_replace(
            target=target,
            replacement=b"invalid",
            expected_sha256=_sha256(target),
            lock_path=lock,
            confirm="CONFIRM",
        )
    assert target.read_bytes() == before


def test_blocked_manifest_cannot_be_applied_even_with_confirm(tmp_path: Path):
    target = tmp_path / "identity.json"
    source = tmp_path / "source.json"
    output = tmp_path / "blocked-plan"
    lock = tmp_path / "owner.lock"
    _current(target)
    _write_source(
        source,
        _self_binding(),
        _entity("person:first", "qq", "5001"),
        _entity("person:second", "qq", "5002"),
        _alias("ambiguous", "person:first"),
        _alias("ambiguous", "person:second"),
    )
    result = make_plan(target, [source])
    candidate, manifest = write_plan(result, output)
    before = target.read_bytes()
    assert main(
        [
            "apply",
            "--target",
            str(target),
            "--candidate",
            str(candidate),
            "--manifest",
            str(manifest),
            "--expected-sha256",
            _sha256(target),
            "--owner-lock",
            str(lock),
            "--confirm",
            "CONFIRM",
        ]
    ) == 2
    assert target.read_bytes() == before
