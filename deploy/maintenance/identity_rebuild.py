"""Plan and apply a conservative Identity Registry rebuild.

The planner accepts only an existing Identity Registry envelope and explicitly
authorized, already-normalized export files.  It never reads message text and
does not attempt entity inference.  Candidate construction and validation are
delegated to the production ``EntityRegistry`` contract; this module owns only
the offline plan and the guarded file replacement procedure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOOL_PATH = Path(__file__).resolve()
_REPO_ROOT = _TOOL_PATH.parents[2] if len(_TOOL_PATH.parents) > 2 else Path.cwd()
_IRIS_ROOT = Path(
    os.environ.get(
        "IRIS_PLUGIN_ROOT",
        str(_REPO_ROOT / "plugins" / "upstream" / "astrbot_plugin_iris_memory"),
    )
).resolve()
if str(_IRIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_IRIS_ROOT))

from iris_memory.cognitive.contracts import (
    CanonicalEntity,
    CognitiveContractError,
    IdentityClaim,
    IdentityClaimStatus,
    IdentityConfig,
)
from iris_memory.cognitive.identity import EntityRegistry

SOURCE_SCHEMA = "iris.identity-rebuild-source.v1"
MANIFEST_SCHEMA = "iris.identity-rebuild-manifest.v1"
TOOL_VERSION = "1"
CONFIRM_TOKEN = "CONFIRM"
_ALLOWED_SOURCE_TYPES = {
    "identity_export",
    "manual_confirmed_claim",
    "platform_session",
    "episode_event_ref",
    "p2r0_archive",
    "p2r1_authority",
    "astrbot_platform_history",
}
_REFUSABLE_ALIAS_SOURCES = {"identity_export", "manual_confirmed_claim"}


class RebuildError(ValueError):
    """The requested plan or write cannot satisfy the rebuild contract."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_object(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _ref_hash(value: object) -> str:
    """Hash a provenance reference before putting it in a manifest."""

    return _sha256_object(value)


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RebuildError(f"{label} must be a non-empty string")
    return value.strip()


def _strict_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RebuildError(f"{label} has an unsupported shape")
    return value


def _canonical_json_bytes(envelope: dict[str, Any]) -> bytes:
    return (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RebuildError(f"cannot read input: {path}") from exc


def _load_current(path: Path) -> tuple[bytes, EntityRegistry]:
    raw = _read_bytes(path)
    try:
        json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebuildError("current Identity Registry is not valid JSON") from exc
    registry = EntityRegistry(storage_path=path)
    if not registry.available:
        raise RebuildError("current Identity Registry failed owner/schema/checksum validation")
    return raw, registry


def _parse_provenance(raw: object, *, kind: str) -> dict[str, Any]:
    provenance = _strict_keys(
        raw,
        {
            "source_type",
            "source_ref",
            "basis",
            "evidence_refs",
            "field_path",
            "record_hash",
            "role",
            "account_id",
            "platform",
            "uid",
        },
        f"{kind} provenance",
    )
    source_type = _require_nonempty_string(provenance["source_type"], f"{kind} source_type")
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise RebuildError(f"unsupported {kind} source_type")
    source_ref = _require_nonempty_string(provenance["source_ref"], f"{kind} source_ref")
    basis = _require_nonempty_string(provenance["basis"], f"{kind} basis")
    refs = provenance["evidence_refs"]
    if not isinstance(refs, list) or not refs or any(
        not isinstance(ref, str) or not ref.strip() for ref in refs
    ):
        raise RebuildError(f"{kind} evidence_refs must contain explicit references")
    field_path = _require_nonempty_string(provenance["field_path"], f"{kind} field_path")
    record_hash = _require_nonempty_string(provenance["record_hash"], f"{kind} record_hash")
    if len(record_hash) != 64 or any(char not in "0123456789abcdef" for char in record_hash):
        raise RebuildError(f"{kind} record_hash must be a lowercase SHA-256")
    role = _require_nonempty_string(provenance["role"], f"{kind} role")
    if role not in {"user", "self"}:
        raise RebuildError(f"{kind} role must be user or self")
    account_id = provenance["account_id"]
    platform = provenance["platform"]
    uid = provenance["uid"]
    for label, value in (("account_id", account_id), ("platform", platform), ("uid", uid)):
        if not isinstance(value, str):
            raise RebuildError(f"{kind} {label} must be a string")
    if kind in {"entity", "self_binding"} and (not account_id.strip() or not platform.strip() or not uid.strip()):
        raise RebuildError(f"{kind} provenance must include platform, account_id, and uid")
    return {
        "source_type": source_type,
        "source_ref": source_ref,
        "basis": basis,
        "evidence_refs": [ref.strip() for ref in refs],
        "field_path": field_path,
        "record_hash": record_hash,
        "role": role,
        "account_id": account_id.strip(),
        "platform": platform.strip().casefold(),
        "uid": uid.strip(),
    }


def _load_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    raw = _read_bytes(path)
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebuildError(f"source is not valid JSON: {path}") from exc
    root = _strict_keys(document, {"schema", "authorization", "records", "scan"}, "source")
    if root["schema"] != SOURCE_SCHEMA:
        raise RebuildError(f"source schema mismatch: {path}")
    authorization = _strict_keys(
        root["authorization"],
        {"authorized", "scope", "authorization_ref"},
        "source authorization",
    )
    if authorization["authorized"] is not True or authorization["scope"] != "identity-rebuild":
        raise RebuildError(f"source is not explicitly authorized for identity rebuild: {path}")
    _require_nonempty_string(authorization["authorization_ref"], "authorization_ref")
    scan = _strict_keys(root["scan"], {"apply_blocked", "conflicts"}, "source scan")
    if type(scan["apply_blocked"]) is not bool:
        raise RebuildError("source scan apply_blocked must be boolean")
    scan_conflicts = scan["conflicts"]
    if not isinstance(scan_conflicts, list):
        raise RebuildError("source scan conflicts must be a list")
    for index, conflict in enumerate(scan_conflicts):
        item = _strict_keys(conflict, {"category", "count"}, f"source scan conflict {index}")
        _require_nonempty_string(item["category"], f"source scan conflict {index} category")
        if type(item["count"]) is not int or item["count"] <= 0:
            raise RebuildError(f"source scan conflict {index} count must be positive")
    if bool(scan_conflicts) != scan["apply_blocked"]:
        raise RebuildError("source scan conflict state is inconsistent")
    records = root["records"]
    if not isinstance(records, list):
        raise RebuildError(f"source records must be a list: {path}")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        record = _strict_keys(item, {"kind", "record_ref", "payload", "provenance"}, f"record {index}")
        kind = _require_nonempty_string(record["kind"], f"record {index} kind")
        if kind not in {"entity", "alias", "self_binding"}:
            raise RebuildError(f"unsupported source record kind: {kind}")
        record_ref = _require_nonempty_string(record["record_ref"], f"record {index} record_ref")
        provenance = _parse_provenance(record["provenance"], kind=kind)
        normalized.append(
            {
                "kind": kind,
                "record_ref": record_ref,
                "payload": record["payload"],
                "provenance": provenance,
                "source_path": str(path),
                "source_sha256": _sha256_bytes(raw),
            }
        )
    return authorization, normalized, scan


def _parse_entity(payload: object) -> dict[str, Any]:
    raw = _strict_keys(payload, {"id", "aliases", "platform_ids"}, "entity payload")
    if raw["aliases"] not in ([], ()):
        raise RebuildError("source entity aliases require separate confirmed alias records")
    try:
        entity = CanonicalEntity(raw["id"], aliases=(), platform_ids=raw["platform_ids"])
    except (CognitiveContractError, TypeError, AttributeError) as exc:
        raise RebuildError("source entity violates the Identity contract") from exc
    if not entity.platform_ids:
        raise RebuildError("new source entities require an explicit platform UID binding")
    if entity.id.startswith("agent:"):
        raise RebuildError("agent entities require an explicit self_binding record")
    return {
        "id": entity.id,
        "aliases": [],
        "platform_ids": dict(entity.platform_ids),
    }


def _parse_alias(payload: object) -> IdentityClaim:
    raw = _strict_keys(
        payload,
        {"mention", "candidate_entity", "evidence", "confidence", "source", "status", "created_at"},
        "alias payload",
    )
    try:
        status = IdentityClaimStatus(raw["status"])
        created_at = datetime.fromisoformat(_require_nonempty_string(raw["created_at"], "alias created_at"))
        return IdentityClaim(
            mention=_require_nonempty_string(raw["mention"], "alias mention"),
            candidate_entity=raw["candidate_entity"],
            evidence=tuple(raw["evidence"]),
            confidence=float(raw["confidence"]),
            source=_require_nonempty_string(raw["source"], "alias source"),
            status=status,
            created_at=created_at,
        )
    except (CognitiveContractError, TypeError, ValueError) as exc:
        raise RebuildError("source alias violates the Identity contract") from exc


def _parse_self_binding(payload: object) -> dict[str, str]:
    raw = _strict_keys(payload, {"entity_id", "platform", "platform_id"}, "self binding payload")
    entity_id = _require_nonempty_string(raw["entity_id"], "self binding entity_id")
    platform = _require_nonempty_string(raw["platform"], "self binding platform").casefold()
    platform_id = _require_nonempty_string(raw["platform_id"], "self binding platform_id")
    return {"entity_id": entity_id, "platform": platform, "platform_id": platform_id}


def _entity_view(entity: CanonicalEntity) -> dict[str, Any]:
    return {
        "id": entity.id,
        "aliases": list(entity.aliases),
        "platform_ids": dict(entity.platform_ids),
    }


def _claim_sort_key(claim: IdentityClaim) -> tuple[str, str, str, str, str, str]:
    return (
        claim.mention.casefold(),
        claim.candidate_entity,
        claim.status.value,
        claim.created_at.isoformat(),
        claim.source,
        _sha256_object({"evidence": list(claim.evidence)}),
    )


def _build_candidate(
    *, self_entity: str, entities: dict[str, dict[str, Any]], claims: list[IdentityClaim]
) -> bytes:
    """Build through EntityRegistry, then add the derived alias display field."""

    with tempfile.TemporaryDirectory(prefix="identity-rebuild-") as temp_dir:
        path = Path(temp_dir) / "identity_registry.v1.json"
        # Keep construction in memory so the constructor's default SELF record
        # cannot collide with the explicit snapshot record below.
        registry = EntityRegistry(IdentityConfig(self_entity=self_entity, self_aliases=()))
        registry._entities.pop(self_entity, None)
        for entity in sorted(entities.values(), key=lambda item: item["id"]):
            registry.register_entity(
                CanonicalEntity(entity["id"], aliases=(), platform_ids=entity["platform_ids"]),
                source="offline_identity_rebuild",
            )
        for claim in sorted(claims, key=_claim_sort_key):
            registry.add_claim(claim)
        payload = registry._payload()  # Reuse the production encoder/checksum contract.
        for item in payload["entities"]:
            item["aliases"] = list(entities[item["id"]]["aliases"])
        envelope = {"payload": payload, "sha256": EntityRegistry._digest(payload)}
        candidate = _canonical_json_bytes(envelope)
        path.write_bytes(candidate)
        validated = EntityRegistry(storage_path=path)
        if not validated.available:
            raise RebuildError("constructed candidate failed EntityRegistry validation")
        return candidate


@dataclass(frozen=True)
class PlanResult:
    candidate_bytes: bytes
    manifest: dict[str, Any]


def make_plan(current_path: Path, source_paths: list[Path]) -> PlanResult:
    current_raw, current = _load_current(current_path)
    base_entities = {_entity_view(entity)["id"]: _entity_view(entity) for entity in current.entities()}
    base_claims = list(current.all_claims())
    entities = {key: dict(value) for key, value in base_entities.items()}
    claims = list(base_claims)
    conflicts: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    source_record_count = 0
    accepted_count = 0
    self_entity = current.self_entity
    self_binding_seen = any(
        entity.id == self_entity and bool(entity.platform_ids) for entity in current.entities()
    )

    def note(
        *, item: dict[str, Any], action: str, category: str, detail: str | None = None
    ) -> None:
        nonlocal accepted_count
        entry = {
            "action": action,
            "category": category,
            "item_hash": _ref_hash(item["payload"]),
            "record_ref_hash": _ref_hash(item["record_ref"]),
            "source_path_hash": _ref_hash(item["source_path"]),
            "source_sha256": item["source_sha256"],
            "basis": item["provenance"]["basis"],
            "source_type": item["provenance"]["source_type"],
            "evidence_ref_hashes": [_ref_hash(ref) for ref in item["provenance"]["evidence_refs"]],
            "field_path_hash": _ref_hash(item["provenance"]["field_path"]),
            "record_hash": item["provenance"]["record_hash"],
            "role": item["provenance"]["role"],
            "account_id_hash": _ref_hash(item["provenance"]["account_id"]),
            "platform_hash": _ref_hash(item["provenance"]["platform"]),
            "uid_hash": _ref_hash(item["provenance"]["uid"]),
        }
        if detail:
            entry["detail"] = detail
        provenance.append(entry)
        if action == "accepted":
            accepted_count += 1
        target = conflicts if action == "conflict" else skipped
        if action in {"conflict", "skipped"}:
            target.append(entry)

    items: list[dict[str, Any]] = []
    source_scan_conflicts: list[dict[str, Any]] = []
    for source_path in source_paths:
        _, source_items, source_scan = _load_source(source_path)
        items.extend(source_items)
        for conflict in source_scan["conflicts"]:
            source_scan_conflicts.append(
                {
                    "action": "conflict",
                    "category": "EXPORT_PREFLIGHT_" + conflict["category"],
                    "count": conflict["count"],
                    "source_path_hash": _ref_hash(str(source_path)),
                }
            )
    source_record_count = len(items)
    conflicts.extend(source_scan_conflicts)

    parsed_entities: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in items:
        if item["kind"] != "entity":
            continue
        provenance_item = item["provenance"]
        if provenance_item["basis"] != "platform_uid":
            note(item=item, action="conflict", category="ENTITY_BASIS_UNSUPPORTED")
            continue
        try:
            parsed_entities.append((_parse_entity(item["payload"]), item))
        except RebuildError:
            note(item=item, action="conflict", category="ENTITY_PAYLOAD_INVALID")

    platform_index: dict[tuple[str, str], str] = {}
    for entity in entities.values():
        for platform, platform_id in entity["platform_ids"].items():
            platform_index[(platform.casefold(), str(platform_id).strip())] = entity["id"]
    for entity, item in parsed_entities:
        existing = entities.get(entity["id"])
        if existing is not None:
            if existing["platform_ids"] != entity["platform_ids"]:
                note(item=item, action="conflict", category="ENTITY_DATA_CONFLICT")
                continue
            note(item=item, action="skipped", category="ENTITY_DUPLICATE")
            continue
        collision = next(
            (
                owner
                for platform, platform_id in entity["platform_ids"].items()
                if (platform.casefold(), platform_id) in platform_index
                for owner in [platform_index[(platform.casefold(), platform_id)]]
                if owner != entity["id"]
            ),
            None,
        )
        if collision is not None:
            note(item=item, action="conflict", category="PLATFORM_UID_COLLISION")
            continue
        entities[entity["id"]] = entity
        for platform, platform_id in entity["platform_ids"].items():
            platform_index[(platform.casefold(), platform_id)] = entity["id"]
        note(item=item, action="accepted", category="ENTITY_ADDED")

    for item in items:
        kind = item["kind"]
        if kind == "self_binding":
            try:
                binding = _parse_self_binding(item["payload"])
            except RebuildError:
                note(item=item, action="conflict", category="SELF_BINDING_INVALID")
                continue
            if binding["entity_id"] != self_entity:
                note(item=item, action="conflict", category="SELF_ENTITY_MISMATCH")
                continue
            key = (binding["platform"], binding["platform_id"])
            owner = platform_index.get(key)
            if owner is not None and owner != self_entity:
                note(item=item, action="conflict", category="SELF_UID_COLLISION")
                continue
            entities[self_entity]["platform_ids"][binding["platform"]] = binding["platform_id"]
            platform_index[key] = self_entity
            self_binding_seen = True
            note(item=item, action="accepted", category="SELF_BINDING_ADDED")
        elif kind == "alias":
            provenance_item = item["provenance"]
            if (
                provenance_item["basis"] != "manual_confirmed_alias"
                or provenance_item["source_type"] not in _REFUSABLE_ALIAS_SOURCES
            ):
                note(item=item, action="skipped", category="ALIAS_SOURCE_NOT_AUTHORIZED")
                continue
            try:
                claim = _parse_alias(item["payload"])
            except RebuildError:
                note(item=item, action="conflict", category="ALIAS_PAYLOAD_INVALID")
                continue
            if claim.status is not IdentityClaimStatus.CONFIRMED:
                note(item=item, action="skipped", category="UNCONFIRMED_ALIAS_SKIPPED")
                continue
            if claim.candidate_entity not in entities:
                note(item=item, action="conflict", category="ALIAS_UNKNOWN_ENTITY")
                continue
            if claim in claims:
                note(item=item, action="skipped", category="ALIAS_DUPLICATE")
                continue
            claims.append(claim)
            entities[claim.candidate_entity]["aliases"] = sorted(
                set(entities[claim.candidate_entity]["aliases"]) | {claim.mention}
            )
            note(item=item, action="accepted", category="CONFIRMED_ALIAS_ADDED")

    if not self_binding_seen:
        conflicts.append(
            {
                "action": "conflict",
                "category": "SELF_BINDING_REQUIRED",
                "item_hash": _ref_hash(self_entity),
                "detail": "explicit bot platform/account binding is required",
            }
        )

    alias_targets: dict[str, set[str]] = {}
    for claim in claims:
        if claim.status is IdentityClaimStatus.CONFIRMED:
            alias_targets.setdefault(claim.mention.casefold(), set()).add(claim.candidate_entity)
    for mention, targets in alias_targets.items():
        if len(targets) > 1:
            conflicts.append(
                {
                    "action": "conflict",
                    "category": "CONFIRMED_ALIAS_CONFLICT",
                    "item_hash": _ref_hash(mention),
                    "target_count": len(targets),
                }
            )

    candidate_bytes = _build_candidate(self_entity=self_entity, entities=entities, claims=claims)
    candidate_sha = _sha256_bytes(candidate_bytes)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "tool_version": TOOL_VERSION,
        "mode": "dry-run",
        "apply_blocked": bool(conflicts),
        "current": {
            "path": str(current_path),
            "exists": True,
            "bytes": len(current_raw),
            "sha256": _sha256_bytes(current_raw),
            "valid": True,
        },
        "candidate": {"bytes": len(candidate_bytes), "sha256": candidate_sha},
        "counts": {
            "entities_before": len(base_entities),
            "entities_after": len(entities),
            "claims_before": len(base_claims),
            "claims_after": len(claims),
            "source_records": source_record_count,
            "accepted": accepted_count,
            "conflicts": len(conflicts),
            "skipped": len(skipped),
        },
        "conflicts": conflicts,
        "skipped": skipped,
        "provenance": provenance,
        "write_plan": {
            "backup_same_directory": True,
            "atomic_replace": True,
            "fsync_file_and_directory": True,
            "requires_exact_precondition_sha256": True,
            "requires_confirm_token": CONFIRM_TOKEN,
            "requires_stopped_service_or_owner_lock": True,
        },
    }
    return PlanResult(candidate_bytes=candidate_bytes, manifest=manifest)


def write_plan(result: PlanResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    candidate_path = output_dir / "identity_registry.candidate.v1.json"
    manifest_path = output_dir / "identity_rebuild.manifest.v1.json"
    manifest = dict(result.manifest)
    manifest["candidate"]["path"] = str(candidate_path)
    manifest_path.write_bytes(_canonical_json_bytes(manifest))
    candidate_path.write_bytes(result.candidate_bytes)
    os.chmod(candidate_path, 0o600)
    os.chmod(manifest_path, 0o600)
    return candidate_path, manifest_path


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _owner_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    os.chmod(path, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RebuildError("owner lock is already held") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RebuildError("owner lock is already held") from exc
        yield
    finally:
        if os.name == "nt":
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _validate_candidate_bytes(raw: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="identity-candidate-") as temp_dir:
        path = Path(temp_dir) / "candidate.json"
        path.write_bytes(raw)
        registry = EntityRegistry(storage_path=path)
        if not registry.available:
            raise RebuildError("candidate failed EntityRegistry validation")


def _validate_apply_manifest(manifest_path: Path, candidate_path: Path, candidate: bytes, expected_sha256: str) -> None:
    try:
        manifest = json.loads(_read_bytes(manifest_path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebuildError("apply manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise RebuildError("apply manifest schema mismatch")
    if manifest.get("apply_blocked") is True:
        raise RebuildError("apply manifest is blocked by unresolved conflicts")
    candidate_meta = manifest.get("candidate")
    current_meta = manifest.get("current")
    if not isinstance(candidate_meta, dict) or not isinstance(current_meta, dict):
        raise RebuildError("apply manifest lacks current/candidate metadata")
    candidate_sha = _sha256_bytes(candidate)
    if candidate_meta.get("sha256") != candidate_sha:
        raise RebuildError("candidate hash does not match apply manifest")
    if current_meta.get("sha256") != expected_sha256:
        raise RebuildError("precondition hash does not match apply manifest")
    if not candidate_path.is_file():
        raise RebuildError("candidate path is not a regular file")


def _atomic_replace(target: Path, replacement: bytes) -> None:
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, target)
        _fsync_directory(target.parent)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _guarded_replace(
    *, target: Path, replacement: bytes, expected_sha256: str, lock_path: Path, confirm: str
) -> Path:
    if confirm != CONFIRM_TOKEN:
        raise RebuildError("exact CONFIRM token is required")
    if _sha256_bytes(replacement) == _sha256_bytes(_read_bytes(target)):
        raise RebuildError("candidate is byte-identical to target; refusing a no-op replace")
    current = _read_bytes(target)
    actual = _sha256_bytes(current)
    if actual != expected_sha256:
        raise RebuildError("target precondition hash does not match")
    backup = target.with_name(
        f"{target.name}.backup.{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
    )
    with _owner_lock(lock_path):
        if _sha256_bytes(_read_bytes(target)) != expected_sha256:
            raise RebuildError("target changed after precondition check")
        _validate_candidate_bytes(replacement)
        with backup.open("xb") as handle:
            handle.write(current)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(backup, 0o600)
        _fsync_directory(target.parent)
        _atomic_replace(target, replacement)
        try:
            readback = _read_bytes(target)
            if _sha256_bytes(readback) != _sha256_bytes(replacement):
                raise RebuildError("candidate read-back hash mismatch")
            _validate_candidate_bytes(readback)
        except Exception as exc:
            try:
                _atomic_replace(target, current)
                if _sha256_bytes(_read_bytes(target)) != expected_sha256:
                    raise RebuildError("rollback read-back hash mismatch")
            except Exception as rollback_exc:
                raise RebuildError("candidate verification failed and rollback was not proven") from rollback_exc
            raise RebuildError("candidate verification failed; original restored") from exc
    return backup


def _command_plan(args: argparse.Namespace) -> int:
    result = make_plan(Path(args.current), [Path(path) for path in args.source])
    candidate, manifest = write_plan(result, Path(args.output_dir))
    print(f"plan_status={'BLOCKED' if result.manifest['apply_blocked'] else 'READY'}")
    print(f"candidate={candidate}")
    print(f"manifest={manifest}")
    print(f"before_sha256={result.manifest['current']['sha256']}")
    print(f"candidate_sha256={result.manifest['candidate']['sha256']}")
    print(f"conflicts={result.manifest['counts']['conflicts']}")
    print(f"skipped={result.manifest['counts']['skipped']}")
    return 0


def _command_apply(args: argparse.Namespace) -> int:
    target = Path(args.target)
    candidate_path = Path(args.candidate)
    replacement = _read_bytes(candidate_path)
    _validate_apply_manifest(Path(args.manifest), candidate_path, replacement, args.expected_sha256)
    backup = _guarded_replace(
        target=target,
        replacement=replacement,
        expected_sha256=args.expected_sha256,
        lock_path=Path(args.owner_lock),
        confirm=args.confirm,
    )
    print("apply_status=APPLIED")
    print(f"target={target}")
    print(f"backup={backup}")
    print(f"candidate_sha256={_sha256_bytes(replacement)}")
    return 0


def _command_restore(args: argparse.Namespace) -> int:
    target = Path(args.target)
    backup = Path(args.backup)
    replacement = _read_bytes(backup)
    restored_backup = _guarded_replace(
        target=target,
        replacement=replacement,
        expected_sha256=args.expected_sha256,
        lock_path=Path(args.owner_lock),
        confirm=args.confirm,
    )
    print("restore_status=RESTORED")
    print(f"target={target}")
    print(f"pre_restore_backup={restored_backup}")
    print(f"restored_sha256={_sha256_bytes(replacement)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="build a private candidate and redacted manifest")
    plan.add_argument("--current", required=True)
    plan.add_argument("--source", action="append", default=[])
    plan.add_argument("--output-dir", required=True)
    plan.set_defaults(handler=_command_plan)
    for name, handler in (("apply", _command_apply), ("restore", _command_restore)):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--owner-lock", required=True)
        command.add_argument("--expected-sha256", required=True)
        command.add_argument("--confirm", required=True)
        if name == "apply":
            command.add_argument("--candidate", required=True)
            command.add_argument("--manifest", required=True)
        else:
            command.add_argument("--backup", required=True)
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except RebuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
