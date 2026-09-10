"""Build a redacted, structure-only historical Identity rebuild export.

The exporter reads JSONL envelopes from explicitly selected historical stores,
but follows a small allowlist of identity fields.  It never reads message
content, display names, evidence text, or free-form model output.  Message
identity fields such as ``message_id``, ``trace_id`` and ``account_id`` in a
P2r0/P2r1 platform-message object are not user identity fields and cannot
produce an export record.

The result is an ``iris.identity-rebuild-source.v1`` document accepted by
``identity_rebuild.py``.  A separate private report carries anonymous counts,
input hashes, and bounded samples of conflict/skip categories.  Both outputs
are dry-run artifacts; this module never opens the production registry for
writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .identity_rebuild import (
        SOURCE_SCHEMA,
        TOOL_VERSION,
        _canonical_json_bytes,
        _load_current,
        _sha256_bytes,
    )
except ImportError:  # pragma: no cover - exercised by direct CLI execution
    from identity_rebuild import (  # type: ignore[no-redef]
        SOURCE_SCHEMA,
        TOOL_VERSION,
        _canonical_json_bytes,
        _load_current,
        _sha256_bytes,
    )

EXPORT_REPORT_SCHEMA = "iris.identity-rebuild-export-report.v1"
SELF_ENTITY = "agent:xiaotianwen"
_RECORD_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_ENTITY_ID_RE = re.compile(
    r"person:(?P<platform>[A-Za-z0-9][A-Za-z0-9_.-]*):(?P<uid>[A-Za-z0-9][A-Za-z0-9_.@-]*)\Z"
)
_SOURCE_TYPES = {
    "episodes": "episode_event_ref",
    "p2r0": "p2r0_archive",
    "p2r1": "p2r1_authority",
}
_EXPLICIT_IDENTITY_KEYS = (
    "sender",
    "user",
    "sender_identity",
    "user_identity",
    "self_identity",
    "self_binding",
    "bot_identity",
)
_MESSAGE_IDENTITY_KEYS = frozenset(
    {"platform_id", "conversation_id", "message_id", "source_event_id", "trace_id", "execution_record_id"}
)
_MAX_SAMPLES = 8


class ExportError(ValueError):
    """The selected historical input cannot be safely exported."""


@dataclass(frozen=True)
class ExportResult:
    """A normalized source document and its non-sensitive scan report."""

    document: dict[str, Any]
    report: dict[str, Any]


def _strict_json(raw: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ExportError(f"non-finite JSON value: {value}")

    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ExportError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8", "strict"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError("malformed JSON") from exc


def _component(value: object, label: str) -> str:
    if type(value) is int:
        value = str(value)
    if type(value) is not str:
        raise ExportError(f"{label} must be a string or integer")
    normalized = value.strip()
    if not normalized or any(char.isspace() or ord(char) < 32 for char in normalized):
        raise ExportError(f"{label} is not a concrete identity component")
    return normalized


def _path_hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", "strict")).hexdigest()


def _source_ref(source_type: str, record_hash: str, field_path: str) -> str:
    return f"{source_type}:{record_hash}:{_path_hash(field_path)}"


def _provenance(
    *,
    source_type: str,
    record_hash: str,
    field_path: str,
    role: str,
    account_id: str,
    platform: str,
    uid: str,
    basis: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    if not _RECORD_HASH_RE.fullmatch(record_hash):
        raise ExportError("internal record hash is not SHA-256")
    return {
        "source_type": source_type,
        "source_ref": _source_ref(source_type, record_hash, field_path),
        "basis": basis,
        "evidence_refs": sorted(set(evidence_refs)),
        "field_path": field_path,
        "record_hash": record_hash,
        "role": role,
        "account_id": account_id,
        "platform": platform,
        "uid": uid,
    }


def _record(
    *,
    kind: str,
    payload: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "record_ref": provenance["source_ref"],
        "payload": payload,
        "provenance": provenance,
    }


def _identity_object(
    value: object,
    *,
    field_path: str,
) -> tuple[dict[str, str] | None, str | None]:
    """Extract one explicitly shaped identity object, never by fuzzy walking."""

    if not isinstance(value, dict):
        return None, "IDENTITY_OBJECT_NOT_OBJECT"
    # A message object can contain account_id and platform_id.  Those are
    # deliberately not accepted as a user UID or a bot binding.
    if _MESSAGE_IDENTITY_KEYS.intersection(value) and "uid" not in value and "user_id" not in value:
        return None, "MESSAGE_IDENTITY_ONLY"
    role = value.get("role")
    if type(role) is not str or role not in {"user", "self"}:
        return None, "ROLE_UNDECLARED"
    platform_value = value.get("platform")
    account_value = value.get("account_id")
    uid_value = value.get("uid")
    if uid_value is None:
        uid_value = value.get("user_id")
    missing = [
        label
        for label, item in (
            ("platform", platform_value),
            ("account_id", account_value),
            ("uid", uid_value),
        )
        if item is None
    ]
    if missing:
        return None, "MISSING_" + "_".join(item.upper() for item in missing)
    try:
        platform = _component(platform_value, "platform").casefold()
        account_id = _component(account_value, "account_id")
        uid = _component(uid_value, "uid")
    except ExportError:
        return None, "IDENTITY_COMPONENT_INVALID"
    if ":" in uid or ":" in platform:
        return None, "IDENTITY_COMPONENT_INVALID"
    entity_id_value = value.get("entity_id")
    if role == "self":
        if type(entity_id_value) is not str or entity_id_value != SELF_ENTITY:
            return None, "SELF_ENTITY_UNDECLARED"
        return {
            "role": role,
            "platform": platform,
            "account_id": account_id,
            "uid": uid,
            "entity_id": SELF_ENTITY,
        }, None
    derived_id = f"person:{platform}:{uid}"
    if entity_id_value is not None and entity_id_value != derived_id:
        return None, "ENTITY_UID_MISMATCH"
    return {
        "role": role,
        "platform": platform,
        "account_id": account_id,
        "uid": uid,
        "entity_id": derived_id,
    }, None


def _iter_episode_objects(payload: object) -> Iterator[tuple[str, object]]:
    if not isinstance(payload, dict):
        return
    for key in ("participants", "event_refs"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            path = f"payload.{key}[{index}]"
            if key == "event_refs":
                if isinstance(item, dict):
                    yield f"{path}.actor_entity", item.get("actor_entity")
                else:
                    yield path, item
            else:
                yield path, item
    for key in _EXPLICIT_IDENTITY_KEYS:
        if key in payload:
            yield f"payload.{key}", payload[key]


def _iter_explicit_objects(envelope: dict[str, Any]) -> Iterator[tuple[str, object]]:
    for key in _EXPLICIT_IDENTITY_KEYS:
        if key in envelope:
            yield key, envelope[key]
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        for key in _EXPLICIT_IDENTITY_KEYS:
            if key in payload:
                yield f"payload.{key}", payload[key]


def _scan_line(
    *,
    source_type: str,
    envelope: object,
    record_hash: str,
) -> Iterator[tuple[str, object, str]]:
    if not isinstance(envelope, dict):
        yield "", None, "ENVELOPE_NOT_OBJECT"
        return
    if source_type == "episode_event_ref":
        candidates = list(_iter_episode_objects(envelope.get("payload")))
    else:
        candidates = list(_iter_explicit_objects(envelope))
    if not candidates:
        yield "", None, "NO_EXPLICIT_USER_UID_FIELD"
        return
    for field_path, value in candidates:
        yield field_path, value, ""


def _add_sample(samples: dict[str, list[dict[str, str]]], reason: str, item: dict[str, str]) -> None:
    values = samples.setdefault(reason, [])
    if len(values) < _MAX_SAMPLES:
        values.append(item)


def _observation(
    *,
    identity: dict[str, str],
    source_type: str,
    record_hash: str,
    field_path: str,
) -> dict[str, Any]:
    return {
        **identity,
        "source_type": source_type,
        "record_hash": record_hash,
        "field_path": field_path or "record",
    }


def _merge_provenance(observations: list[dict[str, Any]], *, basis: str) -> dict[str, Any]:
    first = observations[0]
    refs = [f"record:{item['record_hash']}" for item in observations]
    return _provenance(
        source_type=first["source_type"],
        record_hash=first["record_hash"],
        field_path=first["field_path"],
        role=first["role"],
        account_id=first["account_id"],
        platform=first["platform"],
        uid=first["uid"],
        basis=basis,
        evidence_refs=refs,
    )


def _confirmed_claim_records(path: Path, *, skipped: Counter[str], samples: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    try:
        raw, registry = _load_current(path)
    except Exception as exc:
        raise ExportError("identity registry input failed owner/schema validation") from exc
    raw_hash = _sha256_bytes(raw)
    entities = {entity.id: entity for entity in registry.entities()}
    result: list[dict[str, Any]] = []
    for index, claim in enumerate(registry.all_claims()):
        if claim.status.value != "CONFIRMED":
            skipped["UNCONFIRMED_ALIAS_SKIPPED"] += 1
            _add_sample(
                samples,
                "UNCONFIRMED_ALIAS_SKIPPED",
                {"record_hash": raw_hash, "field_path": f"payload.claims[{index}]"},
            )
            continue
        entity = entities.get(claim.candidate_entity)
        if entity is None or not entity.platform_ids:
            skipped["ALIAS_ENTITY_NO_PLATFORM_BINDING"] += 1
            _add_sample(
                samples,
                "ALIAS_ENTITY_NO_PLATFORM_BINDING",
                {"record_hash": raw_hash, "field_path": f"payload.claims[{index}]"},
            )
            continue
        platform, uid = min(entity.platform_ids.items())
        payload = {
            "mention": claim.mention,
            "candidate_entity": claim.candidate_entity,
            "evidence": list(claim.evidence),
            "confidence": claim.confidence,
            "source": claim.source,
            "status": claim.status.value,
            "created_at": claim.created_at.isoformat(),
        }
        provenance = _provenance(
            source_type="identity_export",
            record_hash=raw_hash,
            field_path=f"payload.claims[{index}]",
            role="user",
            account_id="",
            platform=str(platform),
            uid=str(uid),
            basis="manual_confirmed_alias",
            evidence_refs=[f"record:{raw_hash}"],
        )
        result.append(_record(kind="alias", payload=payload, provenance=provenance))
    return result


def export_history(
    *,
    episode_path: Path | None = None,
    p2r0_path: Path | None = None,
    p2r1_path: Path | None = None,
    identity_registry_path: Path | None = None,
    authorization_ref: str,
) -> ExportResult:
    """Scan selected stores and return a deterministic normalized export."""

    if type(authorization_ref) is not str or not authorization_ref.strip():
        raise ExportError("authorization_ref is required")
    selected = {
        "episodes": episode_path,
        "p2r0": p2r0_path,
        "p2r1": p2r1_path,
    }
    if not any(path is not None for path in selected.values()) and identity_registry_path is None:
        raise ExportError("at least one explicitly authorized input is required")
    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    conflict_counts: Counter[str] = Counter()
    skip_samples: dict[str, list[dict[str, str]]] = {}
    conflict_samples: dict[str, list[dict[str, str]]] = {}
    input_meta: list[dict[str, Any]] = []
    user_observations: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    self_observations: list[dict[str, Any]] = []

    for name, path in selected.items():
        if path is None:
            continue
        source_type = _SOURCE_TYPES[name]
        try:
            raw_file = path.read_bytes()
        except OSError as exc:
            raise ExportError(f"cannot read {name} input") from exc
        file_hash = _sha256_bytes(raw_file)
        lines = 0
        malformed = 0
        for raw_line in raw_file.splitlines(keepends=True):
            lines += 1
            counts["records_scanned"] += 1
            record_hash = _sha256_bytes(raw_line)
            try:
                envelope = _strict_json(raw_line)
            except ExportError:
                malformed += 1
                skipped["MALFORMED_RECORD"] += 1
                _add_sample(
                    skip_samples,
                    "MALFORMED_RECORD",
                    {"record_hash": record_hash, "field_path": "record"},
                )
                continue
            candidates = list(
                _scan_line(source_type=source_type, envelope=envelope, record_hash=record_hash)
            )
            for field_path, value, scan_reason in candidates:
                if scan_reason:
                    skipped[scan_reason] += 1
                    _add_sample(
                        skip_samples,
                        scan_reason,
                        {"record_hash": record_hash, "field_path": field_path or "record"},
                    )
                    continue
                identity, reason = _identity_object(value, field_path=field_path)
                if reason is not None or identity is None:
                    category = reason or "IDENTITY_NOT_EXTRACTED"
                    skipped[category] += 1
                    _add_sample(
                        skip_samples,
                        category,
                        {"record_hash": record_hash, "field_path": field_path},
                    )
                    continue
                observation = _observation(
                    identity=identity,
                    source_type=source_type,
                    record_hash=record_hash,
                    field_path=field_path,
                )
                if identity["role"] == "self":
                    self_observations.append(observation)
                else:
                    user_observations[(identity["platform"], identity["uid"])].append(observation)
                counts["explicit_identity_observations"] += 1
        input_meta.append(
            {
                "source_type": source_type,
                "path_sha256": _path_hash(path),
                "bytes": len(raw_file),
                "sha256": file_hash,
                "records": lines,
                "malformed": malformed,
            }
        )

    records: list[dict[str, Any]] = []
    for (platform, uid), observations in sorted(user_observations.items()):
        account_ids = {item["account_id"] for item in observations}
        entity_ids = {item["entity_id"] for item in observations}
        if len(account_ids) > 1:
            reason = "USER_ACCOUNT_CONFLICT"
            conflict_counts[reason] += len(observations)
            for item in observations:
                _add_sample(
                    conflict_samples,
                    reason,
                    {"record_hash": item["record_hash"], "field_path": item["field_path"]},
                )
            continue
        if len(entity_ids) > 1:
            reason = "USER_ENTITY_CONFLICT"
            conflict_counts[reason] += len(observations)
            for item in observations:
                _add_sample(
                    conflict_samples,
                    reason,
                    {"record_hash": item["record_hash"], "field_path": item["field_path"]},
                )
            continue
        first = observations[0]
        payload = {"id": first["entity_id"], "aliases": [], "platform_ids": {platform: uid}}
        records.append(
            _record(
                kind="entity",
                payload=payload,
                provenance=_merge_provenance(observations, basis="platform_uid"),
            )
        )
        counts["entities_emitted"] += 1

    if self_observations:
        self_keys = {
            (item["entity_id"], item["platform"], item["account_id"], item["uid"])
            for item in self_observations
        }
        if len(self_keys) > 1:
            reason = "SELF_BINDING_CONFLICT"
            conflict_counts[reason] += len(self_observations)
            for item in self_observations:
                _add_sample(
                    conflict_samples,
                    reason,
                    {"record_hash": item["record_hash"], "field_path": item["field_path"]},
                )
        elif len(self_observations) < 2:
            reason = "SELF_BINDING_INSUFFICIENT_OBSERVATIONS"
            skipped[reason] += 1
            item = self_observations[0]
            _add_sample(skip_samples, reason, {"record_hash": item["record_hash"], "field_path": item["field_path"]})
        else:
            first = self_observations[0]
            records.append(
                _record(
                    kind="self_binding",
                    payload={
                        "entity_id": SELF_ENTITY,
                        "platform": first["platform"],
                        "platform_id": first["uid"],
                    },
                    provenance=_merge_provenance(self_observations, basis="self_binding"),
                )
            )
            counts["self_bindings_emitted"] += 1
    else:
        skipped["SELF_BINDING_MISSING"] += 1

    if identity_registry_path is not None:
        records.extend(_confirmed_claim_records(identity_registry_path, skipped=skipped, samples=skip_samples))
        counts["confirmed_alias_records"] += sum(item["kind"] == "alias" for item in records)

    records.sort(key=lambda item: (item["kind"], item["payload"].get("id", item["payload"].get("mention", ""))))
    counts["accepted"] = len(records)
    counts["conflicts"] = sum(conflict_counts.values())
    counts["skipped"] = sum(skipped.values())
    document = {
        "schema": SOURCE_SCHEMA,
        "authorization": {
            "authorized": True,
            "scope": "identity-rebuild",
            "authorization_ref": authorization_ref.strip(),
        },
        "records": records,
        "scan": {
            "apply_blocked": bool(conflict_counts),
            "conflicts": [
                {"category": category, "count": conflict_counts[category]}
                for category in sorted(conflict_counts)
            ],
        },
    }
    report = {
        "schema": EXPORT_REPORT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "mode": "dry-run",
        "source_schema": SOURCE_SCHEMA,
        "apply_blocked": bool(conflict_counts),
        "inputs": input_meta,
        "counts": dict(sorted(counts.items())),
        "conflict_categories": dict(sorted(conflict_counts.items())),
        "skipped_categories": dict(sorted(skipped.items())),
        "conflicts": [item for reason in sorted(conflict_samples) for item in conflict_samples[reason]],
        "skipped": [item for reason in sorted(skip_samples) for item in skip_samples[reason]],
        "sample_limit_per_category": _MAX_SAMPLES,
        "safety": {
            "message_content_read": False,
            "message_identity_fields_used_as_user_uid": False,
            "natural_language_inference": False,
            "production_write": False,
        },
    }
    return ExportResult(document=document, report=report)


def _write_private(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def write_export(result: ExportResult, output: Path, report: Path | None = None) -> tuple[Path, Path]:
    report_path = report or output.with_name("identity_history_export.report.v1.json")
    _write_private(output, _canonical_json_bytes(result.document))
    _write_private(report_path, _canonical_json_bytes(result.report))
    return output, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", nargs="?", default="export", help=argparse.SUPPRESS)
    parser.add_argument("--episode", "--episodes", dest="episode")
    parser.add_argument("--p2r0")
    parser.add_argument("--p2r1")
    parser.add_argument("--identity-registry")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    parser.add_argument("--authorization-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = export_history(
            episode_path=Path(args.episode) if args.episode else None,
            p2r0_path=Path(args.p2r0) if args.p2r0 else None,
            p2r1_path=Path(args.p2r1) if args.p2r1 else None,
            identity_registry_path=Path(args.identity_registry) if args.identity_registry else None,
            authorization_ref=args.authorization_ref,
        )
        output, report = write_export(
            result,
            Path(args.output),
            Path(args.report) if args.report else None,
        )
        print(f"export_status={'BLOCKED' if result.report['apply_blocked'] else 'READY'}")
        print(f"export={output}")
        print(f"report={report}")
        print(f"accepted={result.report['counts']['accepted']}")
        print(f"conflicts={result.report['counts']['conflicts']}")
        print(f"skipped={result.report['counts']['skipped']}")
        return 0
    except (ExportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
