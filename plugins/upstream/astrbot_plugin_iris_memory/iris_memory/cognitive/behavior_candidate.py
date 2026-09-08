"""P2b Shadow Candidate V1 contracts and append-only journal.

The evaluator in this module only creates reviewable candidates.  It never
publishes a preference, calls ProfileStorage, changes Persona, changes
participation, or grants a tool permission.  The journal accepts identifiers
and lifecycle metadata only; message bodies are not part of any contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import ClassVar

SCHEMA_VERSION = "p2b-shadow-candidate.v1"
JOURNAL_SCHEMA_VERSION = 1
DEFAULT_TTL = timedelta(days=30)


class BehaviorCandidateError(ValueError):
    """Base error for the closed P2b candidate contract."""


class BehaviorCandidateValidationError(BehaviorCandidateError):
    """Raised when a candidate or scope violates the frozen contract."""


class BehaviorCandidateStorageError(BehaviorCandidateError):
    """Raised when the journal cannot be read or durably appended."""


class BehaviorCandidateIntegrityError(BehaviorCandidateStorageError):
    """Raised when journal bytes, checksums, or lifecycle order are invalid."""


class BehaviorCandidateStateError(BehaviorCandidateError):
    """Raised when a requested lifecycle transition is not permitted."""


class BehaviorParameter(str, Enum):
    """The complete, intentionally small P2b parameter allow-list."""

    RESPONSE_LENGTH = "response_length"
    ANSWER_STRUCTURE = "answer_structure"
    FORMAT_DENSITY = "format_density"
    RELATIONSHIP_FAMILIARITY = "relationship_familiarity"
    MEMORY_RETRIEVAL_STYLE = "memory_retrieval_style"


class CandidateStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    CONFLICTED = "CONFLICTED"
    EXPIRED = "EXPIRED"


class PermissionEffect(str, Enum):
    """P2b V1 can never change permissions or tool policy."""

    NONE = "none"


class TransitionReason(str, Enum):
    """Closed lifecycle reasons; free-form message text is never accepted."""

    MANUAL_APPROVAL = "manual_approval"
    MANUAL_REJECTION = "manual_rejection"
    MANUAL_REVOCATION = "manual_revocation"
    TTL_ELAPSED = "ttl_elapsed"


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_VALUE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or not value or not _TOKEN_RE.fullmatch(value):
        raise BehaviorCandidateValidationError(
            f"{field_name} must be a non-empty opaque token"
        )
    return value


def _value_token(value: object) -> str:
    if type(value) is not str:
        raise BehaviorCandidateValidationError("proposed_value must be a string token")
    normalized = value.strip().upper()
    if not _VALUE_RE.fullmatch(normalized):
        raise BehaviorCandidateValidationError(
            "proposed_value must be a closed uppercase token"
        )
    return normalized


def _transition_reason(value: object) -> str:
    try:
        return TransitionReason(value).value  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise BehaviorCandidateValidationError(
            "reason must be a closed TransitionReason"
        ) from exc


def _utc_datetime(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BehaviorCandidateValidationError(
            f"{field_name} must be an aware datetime"
        )
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object, field_name: str) -> datetime:
    if type(value) is not str:
        raise BehaviorCandidateIntegrityError(f"{field_name} must be an ISO datetime")
    try:
        return _utc_datetime(datetime.fromisoformat(value), field_name)
    except (TypeError, ValueError) as exc:
        raise BehaviorCandidateIntegrityError(
            f"{field_name} must be a valid aware ISO datetime"
        ) from exc


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError) as exc:
        raise BehaviorCandidateIntegrityError("value is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def exact_chain_evidence_id(ref: tuple[str, str, str, str]) -> str:
    """Return one opaque ID for the complete exact reply-feedback chain."""
    if type(ref) is not tuple or len(ref) != 4 or any(type(item) is not str or not item for item in ref):
        raise BehaviorCandidateValidationError("exact chain requires four non-empty identifiers")
    return "evidence:p2b:" + hashlib.sha256(_canonical_bytes(list(ref))).hexdigest()[:32]


def _required_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise BehaviorCandidateIntegrityError(f"invalid {label} keys")
    return value


@dataclass(frozen=True, slots=True)
class PrivateUIDScope:
    """One private, one-user scope identified only by trusted UIDs."""

    platform_id: str
    account_id: str
    user_id: str
    conversation_id: str
    scope_kind: str = "PRIVATE"

    def __post_init__(self) -> None:
        for field_name in (
            "platform_id",
            "account_id",
            "user_id",
            "conversation_id",
        ):
            object.__setattr__(
                self, field_name, _token(getattr(self, field_name), field_name)
            )
        if self.scope_kind != "PRIVATE":
            raise BehaviorCandidateValidationError(
                "scope_kind must be PRIVATE"
            )
        # A trusted private conversation UID may be namespaced differently
        # from its user UID.  Privacy comes from the explicit scope kind and
        # the existing scope owner, not from string equality between IDs.

    def to_payload(self) -> dict[str, str]:
        return {
            "platform_id": self.platform_id,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "scope_kind": self.scope_kind,
        }

    @classmethod
    def from_payload(cls, value: object) -> PrivateUIDScope:
        data = _required_keys(
            value,
            {"platform_id", "account_id", "user_id", "conversation_id", "scope_kind"},
            "private UID scope",
        )
        try:
            return cls(**data)  # type: ignore[arg-type]
        except BehaviorCandidateValidationError as exc:
            raise BehaviorCandidateIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """A message-free reference to one ReviewEvidence item and its Episode."""

    episode_id: str
    evidence_id: str
    scope: PrivateUIDScope
    parameter: BehaviorParameter
    proposed_value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _token(self.episode_id, "episode_id"))
        object.__setattr__(self, "evidence_id", _token(self.evidence_id, "evidence_id"))
        if type(self.scope) is not PrivateUIDScope:
            raise BehaviorCandidateValidationError(
                "evidence scope must be PrivateUIDScope"
            )
        if type(self.parameter) is str:
            try:
                object.__setattr__(self, "parameter", BehaviorParameter(self.parameter))
            except ValueError as exc:
                raise BehaviorCandidateValidationError(
                    "evidence parameter is outside the P2b allow-list"
                ) from exc
        if type(self.parameter) is not BehaviorParameter:
            raise BehaviorCandidateValidationError(
                "evidence parameter must be BehaviorParameter"
            )
        object.__setattr__(self, "proposed_value", _value_token(self.proposed_value))

    def to_payload(self) -> dict[str, str]:
        return {
            "episode_id": self.episode_id,
            "evidence_id": self.evidence_id,
            "scope": self.scope.to_payload(),
            "parameter": self.parameter.value,
            "proposed_value": self.proposed_value,
        }

    @classmethod
    def from_payload(cls, value: object) -> CandidateEvidence:
        data = _required_keys(
            value,
            {"episode_id", "evidence_id", "scope", "parameter", "proposed_value"},
            "candidate evidence",
        )
        try:
            return cls(
                episode_id=data["episode_id"],  # type: ignore[arg-type]
                evidence_id=data["evidence_id"],  # type: ignore[arg-type]
                scope=PrivateUIDScope.from_payload(data["scope"]),
                parameter=data["parameter"],  # type: ignore[arg-type]
                proposed_value=data["proposed_value"],  # type: ignore[arg-type]
            )
        except BehaviorCandidateValidationError as exc:
            raise BehaviorCandidateIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class BehaviorCandidate:
    """Immutable candidate contract shared by shadow evaluation and storage."""

    candidate_id: str
    scope: PrivateUIDScope
    parameter: BehaviorParameter
    proposed_value: str
    evidence: tuple[CandidateEvidence, ...]
    created_at: datetime
    expires_at: datetime | None = None
    status: CandidateStatus = CandidateStatus.PENDING
    permission_effect: PermissionEffect = PermissionEffect.NONE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _token(self.candidate_id, "candidate_id"))
        if type(self.scope) is not PrivateUIDScope:
            raise BehaviorCandidateValidationError("scope must be PrivateUIDScope")
        if type(self.parameter) is str:
            try:
                object.__setattr__(self, "parameter", BehaviorParameter(self.parameter))
            except ValueError as exc:
                raise BehaviorCandidateValidationError(
                    "parameter is outside the P2b allow-list"
                ) from exc
        if type(self.parameter) is not BehaviorParameter:
            raise BehaviorCandidateValidationError("parameter must be BehaviorParameter")
        if type(self.status) is str:
            try:
                object.__setattr__(self, "status", CandidateStatus(self.status))
            except ValueError as exc:
                raise BehaviorCandidateValidationError("unknown candidate status") from exc
        if type(self.status) is not CandidateStatus:
            raise BehaviorCandidateValidationError("status must be CandidateStatus")
        object.__setattr__(self, "proposed_value", _value_token(self.proposed_value))
        evidence = tuple(
            sorted(
                self.evidence,
                key=lambda item: (item.episode_id, item.evidence_id)
                if type(item) is CandidateEvidence
                else ("", ""),
            )
        )
        if not evidence or any(type(item) is not CandidateEvidence for item in evidence):
            raise BehaviorCandidateValidationError(
                "candidate evidence must contain CandidateEvidence items"
            )
        if len({item.episode_id for item in evidence}) < 2:
            raise BehaviorCandidateValidationError(
                "candidate requires evidence from at least two distinct Episodes"
            )
        if len({(item.episode_id, item.evidence_id) for item in evidence}) != len(evidence):
            raise BehaviorCandidateValidationError("candidate evidence must be unique")
        if any(item.scope != self.scope for item in evidence):
            raise BehaviorCandidateValidationError(
                "candidate evidence must use one private UID scope"
            )
        if any(item.parameter is not self.parameter for item in evidence):
            raise BehaviorCandidateValidationError(
                "candidate evidence must use one allowed parameter"
            )
        evidence_values = {item.proposed_value for item in evidence}
        if len(evidence_values) > 1:
            if self.status not in {
                CandidateStatus.CONFLICTED,
                CandidateStatus.REJECTED,
                CandidateStatus.EXPIRED,
            }:
                raise BehaviorCandidateValidationError(
                    "competing evidence may only be CONFLICTED, REJECTED, or EXPIRED"
                )
            if self.proposed_value != "UNRESOLVED":
                raise BehaviorCandidateValidationError(
                    "CONFLICTED candidate proposed_value must be UNRESOLVED"
                )
        elif evidence_values != {self.proposed_value}:
            raise BehaviorCandidateValidationError(
                "candidate value must match every evidence value"
            )
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "created_at", _utc_datetime(self.created_at, "created_at"))
        if self.expires_at is not None:
            expires_at = _utc_datetime(self.expires_at, "expires_at")
            if expires_at <= self.created_at:
                raise BehaviorCandidateValidationError(
                    "expires_at must be later than created_at"
                )
            object.__setattr__(self, "expires_at", expires_at)
        if type(self.permission_effect) is str:
            try:
                object.__setattr__(
                    self, "permission_effect", PermissionEffect(self.permission_effect)
                )
            except ValueError as exc:
                raise BehaviorCandidateValidationError(
                    "permission_effect must be none"
                ) from exc
        if self.permission_effect is not PermissionEffect.NONE:
            raise BehaviorCandidateValidationError("permission_effect must be none")
        if self.schema_version != SCHEMA_VERSION:
            raise BehaviorCandidateValidationError("unknown candidate schema")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "scope": self.scope.to_payload(),
            "parameter": self.parameter.value,
            "proposed_value": self.proposed_value,
            "evidence": [item.to_payload() for item in self.evidence],
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status.value,
            "permission_effect": self.permission_effect.value,
        }

    @classmethod
    def from_payload(cls, value: object) -> BehaviorCandidate:
        data = _required_keys(
            value,
            {
                "schema_version",
                "candidate_id",
                "scope",
                "parameter",
                "proposed_value",
                "evidence",
                "created_at",
                "expires_at",
                "status",
                "permission_effect",
            },
            "candidate payload",
        )
        if data["schema_version"] != SCHEMA_VERSION:
            raise BehaviorCandidateIntegrityError("unknown candidate schema")
        if not isinstance(data["evidence"], list):
            raise BehaviorCandidateIntegrityError("candidate evidence must be a list")
        try:
            return cls(
                candidate_id=data["candidate_id"],  # type: ignore[arg-type]
                scope=PrivateUIDScope.from_payload(data["scope"]),
                parameter=data["parameter"],  # type: ignore[arg-type]
                proposed_value=data["proposed_value"],  # type: ignore[arg-type]
                evidence=tuple(CandidateEvidence.from_payload(item) for item in data["evidence"]),
                created_at=_parse_datetime(data["created_at"], "created_at"),
                expires_at=(
                    None
                    if data["expires_at"] is None
                    else _parse_datetime(data["expires_at"], "expires_at")
                ),
                status=data["status"],  # type: ignore[arg-type]
                permission_effect=data["permission_effect"],  # type: ignore[arg-type]
                schema_version=data["schema_version"],  # type: ignore[arg-type]
            )
        except BehaviorCandidateError as exc:
            raise BehaviorCandidateIntegrityError(str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise BehaviorCandidateIntegrityError("invalid candidate payload") from exc


class ShadowCandidateEvaluator:
    """Pure evaluator returning PENDING or CONFLICTED without performing writes."""

    def evaluate(
        self,
        *,
        scope: PrivateUIDScope,
        parameter: BehaviorParameter | str,
        evidence: tuple[CandidateEvidence, ...] | list[CandidateEvidence],
        proposed_value: str | None = None,
        now: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> BehaviorCandidate:
        if type(scope) is not PrivateUIDScope:
            raise BehaviorCandidateValidationError(
                "shadow evaluation requires private UID scope"
            )
        current = _utc_datetime(now or datetime.now(timezone.utc), "now")
        expiry = expires_at or current + DEFAULT_TTL
        try:
            parameter_enum = (
                parameter if type(parameter) is BehaviorParameter else BehaviorParameter(parameter)
            )
        except (TypeError, ValueError) as exc:
            raise BehaviorCandidateValidationError(
                "parameter is outside the P2b allow-list"
            ) from exc
        evidence_tuple = tuple(
            sorted(
                evidence,
                key=lambda item: (item.episode_id, item.evidence_id)
                if type(item) is CandidateEvidence
                else ("", ""),
            )
        )
        if any(type(item) is not CandidateEvidence for item in evidence_tuple):
            raise BehaviorCandidateValidationError(
                "shadow evidence must contain CandidateEvidence items"
            )
        if any(item.scope != scope for item in evidence_tuple):
            raise BehaviorCandidateValidationError(
                "shadow evidence crosses private UID scopes"
            )
        if any(item.parameter is not parameter_enum for item in evidence_tuple):
            raise BehaviorCandidateValidationError(
                "shadow evidence crosses behavior parameters"
            )
        values = {item.proposed_value for item in evidence_tuple}
        status = CandidateStatus.CONFLICTED if len(values) > 1 else CandidateStatus.PENDING
        resolved_value = "UNRESOLVED" if status is CandidateStatus.CONFLICTED else next(iter(values), "")
        if proposed_value is not None and status is CandidateStatus.PENDING:
            if _value_token(proposed_value) != resolved_value:
                raise BehaviorCandidateValidationError(
                    "requested value does not match the evidence"
                )
        parameter_value = parameter_enum.value
        identity_payload = {
            "schema_version": SCHEMA_VERSION,
            "scope": scope.to_payload(),
            "parameter": parameter_value,
            "proposed_value": resolved_value,
            "evidence": [item.to_payload() for item in evidence_tuple],
        }
        candidate_id = "candidate:p2b:" + hashlib.sha256(
            _canonical_bytes(identity_payload)
        ).hexdigest()[:32]
        return BehaviorCandidate(
            candidate_id=candidate_id,
            scope=scope,
            parameter=parameter_enum,
            proposed_value=resolved_value,
            evidence=evidence_tuple,
            created_at=current,
            expires_at=expiry,
            status=status,
            permission_effect=PermissionEffect.NONE,
        )


_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.PENDING: frozenset(
        {
            CandidateStatus.APPROVED,
            CandidateStatus.REJECTED,
            CandidateStatus.EXPIRED,
        }
    ),
    CandidateStatus.APPROVED: frozenset(
        {CandidateStatus.REVOKED, CandidateStatus.EXPIRED}
    ),
    CandidateStatus.REJECTED: frozenset(),
    CandidateStatus.REVOKED: frozenset(),
    CandidateStatus.CONFLICTED: frozenset(
        {CandidateStatus.REJECTED, CandidateStatus.EXPIRED}
    ),
    CandidateStatus.EXPIRED: frozenset(),
}


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Acquire a non-blocking cross-process lock or fail closed."""

    lock_path = Path(str(path) + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (ImportError, OSError) as exc:
                raise BehaviorCandidateStorageError(
                    "behavior candidate journal lock unavailable"
                ) from exc
            try:
                yield
            finally:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError) as exc:
                    raise BehaviorCandidateStorageError(
                        "behavior candidate journal unlock failed"
                    ) from exc
    except BehaviorCandidateStorageError:
        raise
    except OSError as exc:
        raise BehaviorCandidateStorageError(
            "behavior candidate journal lock file unavailable"
        ) from exc


class AppendOnlyBehaviorCandidateStore:
    """Checksummed JSONL store with fail-closed replay and lifecycle APIs."""

    _RECORD_KEYS: ClassVar[set[str]] = {
        "schema_version",
        "record_type",
        "operation_id",
        "recorded_at",
        "candidate_id",
        "payload",
        "payload_sha256",
        "previous_record_sha256",
        "record_sha256",
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._poisoned = False
        with _exclusive_file_lock(self.path):
            self._candidates, self._last_record_sha256 = self._read_locked()

    @property
    def available(self) -> bool:
        return not self._poisoned

    def _ensure_available(self) -> None:
        if self._poisoned:
            raise BehaviorCandidateStorageError(
                "behavior candidate journal is unavailable after an uncertain write"
            )

    def _read_locked(self) -> tuple[dict[str, BehaviorCandidate], str | None]:
        if not self.path.exists():
            return {}, None
        try:
            raw_lines = self.path.read_bytes().splitlines(keepends=True)
        except OSError as exc:
            raise BehaviorCandidateStorageError(
                "behavior candidate journal cannot be read"
            ) from exc
        candidates: dict[str, BehaviorCandidate] = {}
        operation_ids: set[str] = set()
        previous_hash: str | None = None
        for line_number, raw_line in enumerate(raw_lines, 1):
            if not raw_line.endswith(b"\n") or raw_line.endswith(b"\r\n"):
                raise BehaviorCandidateIntegrityError(
                    f"journal line {line_number} is not canonical newline-terminated"
                )
            try:
                record = json.loads(raw_line[:-1].decode("utf-8", "strict"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BehaviorCandidateIntegrityError(
                    f"invalid JSON at journal line {line_number}"
                ) from exc
            if _canonical_bytes(record) + b"\n" != raw_line:
                raise BehaviorCandidateIntegrityError(
                    f"non-canonical JSON at journal line {line_number}"
                )
            data = _required_keys(record, self._RECORD_KEYS, "journal record")
            if data["schema_version"] != JOURNAL_SCHEMA_VERSION:
                raise BehaviorCandidateIntegrityError("unknown journal schema")
            operation_id = _token(data["operation_id"], "operation_id")
            if operation_id in operation_ids:
                raise BehaviorCandidateIntegrityError("duplicate journal operation_id")
            operation_ids.add(operation_id)
            _parse_datetime(data["recorded_at"], "recorded_at")
            candidate_id = _token(data["candidate_id"], "candidate_id")
            if data["previous_record_sha256"] != previous_hash:
                raise BehaviorCandidateIntegrityError(
                    f"journal hash chain mismatch at line {line_number}"
                )
            payload = data["payload"]
            if not isinstance(payload, dict) or data["payload_sha256"] != _sha256(payload):
                raise BehaviorCandidateIntegrityError(
                    f"payload checksum mismatch at journal line {line_number}"
                )
            record_without_hash = dict(data)
            record_without_hash.pop("record_sha256")
            if data["record_sha256"] != _sha256(record_without_hash):
                raise BehaviorCandidateIntegrityError(
                    f"record checksum mismatch at journal line {line_number}"
                )
            record_type = data["record_type"]
            if record_type == "CANDIDATE_CREATED":
                if candidate_id in candidates:
                    raise BehaviorCandidateIntegrityError("candidate created twice")
                candidate = BehaviorCandidate.from_payload(payload)
                if candidate.candidate_id != candidate_id or candidate.status not in {
                    CandidateStatus.PENDING,
                    CandidateStatus.CONFLICTED,
                }:
                    raise BehaviorCandidateIntegrityError(
                        "created candidate identity or status is invalid"
                    )
                candidates[candidate_id] = candidate
            elif record_type == "CANDIDATE_STATUS_CHANGED":
                transition = _required_keys(
                    payload,
                    {
                        "candidate_id",
                        "from_status",
                        "to_status",
                        "actor",
                        "occurred_at",
                        "reason",
                    },
                    "candidate transition",
                )
                if transition["candidate_id"] != candidate_id:
                    raise BehaviorCandidateIntegrityError(
                        "transition candidate identity mismatch"
                    )
                current = candidates.get(candidate_id)
                if current is None:
                    raise BehaviorCandidateIntegrityError(
                        "transition targets unknown candidate"
                    )
                try:
                    prior = CandidateStatus(transition["from_status"])
                    target = CandidateStatus(transition["to_status"])
                except ValueError as exc:
                    raise BehaviorCandidateIntegrityError(
                        "unknown candidate transition status"
                    ) from exc
                if current.status is not prior or target not in _TRANSITIONS[prior]:
                    raise BehaviorCandidateIntegrityError(
                        "invalid candidate transition order"
                    )
                _token(transition["actor"], "actor")
                try:
                    _transition_reason(transition["reason"])
                except BehaviorCandidateValidationError as exc:
                    raise BehaviorCandidateIntegrityError(str(exc)) from exc
                occurred_at = _parse_datetime(transition["occurred_at"], "occurred_at")
                candidates[candidate_id] = BehaviorCandidate(
                    candidate_id=current.candidate_id,
                    scope=current.scope,
                    parameter=current.parameter,
                    proposed_value=current.proposed_value,
                    evidence=current.evidence,
                    created_at=current.created_at,
                    expires_at=current.expires_at,
                    status=target,
                    permission_effect=current.permission_effect,
                )
                del occurred_at
            else:
                raise BehaviorCandidateIntegrityError(
                    f"unknown journal record type at line {line_number}"
                )
            previous_hash = data["record_sha256"]  # type: ignore[assignment]
        return candidates, previous_hash

    def _append_locked(
        self,
        *,
        record_type: str,
        candidate_id: str,
        payload: dict[str, object],
        previous_hash: str | None,
    ) -> str:
        body: dict[str, object] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "record_type": record_type,
            "operation_id": uuid.uuid4().hex,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "candidate_id": candidate_id,
            "payload": payload,
            "payload_sha256": _sha256(payload),
            "previous_record_sha256": previous_hash,
        }
        record = {**body, "record_sha256": _sha256(body)}
        encoded = _canonical_bytes(record) + b"\n"
        try:
            with self.path.open("ab") as handle:
                written = handle.write(encoded)
                if written != len(encoded):
                    raise OSError("short behavior candidate journal write")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            self._poisoned = True
            raise BehaviorCandidateStorageError(
                "behavior candidate journal append failed; store is now fail-closed"
            ) from exc
        return record["record_sha256"]  # type: ignore[return-value]

    @staticmethod
    def _transition_payload(
        candidate_id: str,
        from_status: CandidateStatus,
        to_status: CandidateStatus,
        actor: str,
        occurred_at: datetime,
        reason: TransitionReason | str,
    ) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "from_status": from_status.value,
            "to_status": to_status.value,
            "actor": _token(actor, "actor"),
            "occurred_at": _utc_datetime(occurred_at, "occurred_at").isoformat(),
            "reason": _transition_reason(reason),
        }

    @staticmethod
    def _same_candidate_identity(
        left: BehaviorCandidate, right: BehaviorCandidate
    ) -> bool:
        return (
            left.candidate_id == right.candidate_id
            and left.scope == right.scope
            and left.parameter is right.parameter
            and left.proposed_value == right.proposed_value
            and left.evidence == right.evidence
            and left.permission_effect is PermissionEffect.NONE
            and right.permission_effect is PermissionEffect.NONE
            and left.schema_version == right.schema_version
        )

    def append_candidate(self, candidate: BehaviorCandidate) -> BehaviorCandidate:
        self._ensure_available()
        if type(candidate) is not BehaviorCandidate:
            raise BehaviorCandidateValidationError("expected BehaviorCandidate")
        if candidate.status not in {
            CandidateStatus.PENDING,
            CandidateStatus.CONFLICTED,
        }:
            raise BehaviorCandidateStateError(
                "only shadow PENDING or CONFLICTED candidates can be appended"
            )
        with _exclusive_file_lock(self.path):
            candidates, previous_hash = self._read_locked()
            existing = candidates.get(candidate.candidate_id)
            if existing is not None:
                if not self._same_candidate_identity(existing, candidate):
                    raise BehaviorCandidateIntegrityError(
                        "candidate identity has conflicting payload"
                    )
                self._candidates, self._last_record_sha256 = candidates, previous_hash
                return existing
            last_hash = self._append_locked(
                record_type="CANDIDATE_CREATED",
                candidate_id=candidate.candidate_id,
                payload=candidate.to_payload(),
                previous_hash=previous_hash,
            )
            candidates[candidate.candidate_id] = candidate
            self._candidates, self._last_record_sha256 = candidates, last_hash
            return candidate

    def _transition(
        self,
        candidate_id: str,
        target: CandidateStatus,
        *,
        actor: str,
        reason: TransitionReason | str,
        now: datetime | None,
    ) -> BehaviorCandidate:
        self._ensure_available()
        candidate_id = _token(candidate_id, "candidate_id")
        actor = _token(actor, "actor")
        reason = _transition_reason(reason)
        occurred_at = _utc_datetime(now or datetime.now(timezone.utc), "now")
        with _exclusive_file_lock(self.path):
            candidates, previous_hash = self._read_locked()
            current = candidates.get(candidate_id)
            if current is None:
                raise BehaviorCandidateStateError("unknown candidate")
            if current.status is target:
                self._candidates, self._last_record_sha256 = candidates, previous_hash
                return current
            if (
                current.expires_at is not None
                and occurred_at >= current.expires_at
                and current.status in {
                    CandidateStatus.PENDING,
                    CandidateStatus.APPROVED,
                    CandidateStatus.CONFLICTED,
                }
                and target is not CandidateStatus.EXPIRED
            ):
                expiry_payload = self._transition_payload(
                    candidate_id,
                    current.status,
                    CandidateStatus.EXPIRED,
                    "system:expiry",
                    occurred_at,
                    TransitionReason.TTL_ELAPSED,
                )
                previous_hash = self._append_locked(
                    record_type="CANDIDATE_STATUS_CHANGED",
                    candidate_id=candidate_id,
                    payload=expiry_payload,
                    previous_hash=previous_hash,
                )
                current = BehaviorCandidate(
                    candidate_id=current.candidate_id,
                    scope=current.scope,
                    parameter=current.parameter,
                    proposed_value=current.proposed_value,
                    evidence=current.evidence,
                    created_at=current.created_at,
                    expires_at=current.expires_at,
                    status=CandidateStatus.EXPIRED,
                    permission_effect=current.permission_effect,
                )
                candidates[candidate_id] = current
            if target not in _TRANSITIONS[current.status]:
                raise BehaviorCandidateStateError(
                    f"cannot transition {current.status.value} to {target.value}"
                )
            payload = self._transition_payload(
                candidate_id, current.status, target, actor, occurred_at, reason
            )
            last_hash = self._append_locked(
                record_type="CANDIDATE_STATUS_CHANGED",
                candidate_id=candidate_id,
                payload=payload,
                previous_hash=previous_hash,
            )
            updated = BehaviorCandidate(
                candidate_id=current.candidate_id,
                scope=current.scope,
                parameter=current.parameter,
                proposed_value=current.proposed_value,
                evidence=current.evidence,
                created_at=current.created_at,
                expires_at=current.expires_at,
                status=target,
                permission_effect=current.permission_effect,
            )
            candidates[candidate_id] = updated
            self._candidates, self._last_record_sha256 = candidates, last_hash
            return updated

    def approve(
        self,
        candidate_id: str,
        *,
        actor: str,
        now: datetime | None = None,
        reason: TransitionReason | str = TransitionReason.MANUAL_APPROVAL,
    ) -> BehaviorCandidate:
        return self._transition(
            candidate_id, CandidateStatus.APPROVED, actor=actor, reason=reason, now=now
        )

    def reject(
        self,
        candidate_id: str,
        *,
        actor: str,
        now: datetime | None = None,
        reason: TransitionReason | str = TransitionReason.MANUAL_REJECTION,
    ) -> BehaviorCandidate:
        return self._transition(
            candidate_id, CandidateStatus.REJECTED, actor=actor, reason=reason, now=now
        )

    def revoke(
        self,
        candidate_id: str,
        *,
        actor: str,
        now: datetime | None = None,
        reason: TransitionReason | str = TransitionReason.MANUAL_REVOCATION,
    ) -> BehaviorCandidate:
        return self._transition(
            candidate_id, CandidateStatus.REVOKED, actor=actor, reason=reason, now=now
        )

    def expire_due(self, *, now: datetime | None = None) -> tuple[BehaviorCandidate, ...]:
        current_time = _utc_datetime(now or datetime.now(timezone.utc), "now")
        expired: list[BehaviorCandidate] = []
        self._ensure_available()
        with _exclusive_file_lock(self.path):
            candidates, previous_hash = self._read_locked()
            for candidate_id in sorted(candidates):
                current = candidates[candidate_id]
                if (
                    current.expires_at is None
                    or current.expires_at > current_time
                    or current.status not in {
                        CandidateStatus.PENDING,
                        CandidateStatus.APPROVED,
                        CandidateStatus.CONFLICTED,
                    }
                ):
                    continue
                payload = self._transition_payload(
                    candidate_id,
                    current.status,
                    CandidateStatus.EXPIRED,
                    "system:expiry",
                    current_time,
                    TransitionReason.TTL_ELAPSED,
                )
                previous_hash = self._append_locked(
                    record_type="CANDIDATE_STATUS_CHANGED",
                    candidate_id=candidate_id,
                    payload=payload,
                    previous_hash=previous_hash,
                )
                updated = BehaviorCandidate(
                    candidate_id=current.candidate_id,
                    scope=current.scope,
                    parameter=current.parameter,
                    proposed_value=current.proposed_value,
                    evidence=current.evidence,
                    created_at=current.created_at,
                    expires_at=current.expires_at,
                    status=CandidateStatus.EXPIRED,
                    permission_effect=current.permission_effect,
                )
                candidates[candidate_id] = updated
                expired.append(updated)
            self._candidates, self._last_record_sha256 = candidates, previous_hash
        return tuple(expired)

    def get(self, candidate_id: str) -> BehaviorCandidate | None:
        self._ensure_available()
        candidate_id = _token(candidate_id, "candidate_id")
        with _exclusive_file_lock(self.path):
            candidates, previous_hash = self._read_locked()
            self._candidates, self._last_record_sha256 = candidates, previous_hash
            return candidates.get(candidate_id)

    def all_candidates(self) -> tuple[BehaviorCandidate, ...]:
        self._ensure_available()
        with _exclusive_file_lock(self.path):
            candidates, previous_hash = self._read_locked()
            self._candidates, self._last_record_sha256 = candidates, previous_hash
            return tuple(candidates[key] for key in sorted(candidates))


BehaviorCandidateStore = AppendOnlyBehaviorCandidateStore


__all__ = [
    "DEFAULT_TTL",
    "SCHEMA_VERSION",
    "AppendOnlyBehaviorCandidateStore",
    "BehaviorCandidate",
    "BehaviorCandidateError",
    "BehaviorCandidateIntegrityError",
    "BehaviorCandidateStateError",
    "BehaviorCandidateStorageError",
    "BehaviorCandidateStore",
    "BehaviorCandidateValidationError",
    "BehaviorParameter",
    "CandidateEvidence",
    "CandidateStatus",
    "PermissionEffect",
    "PrivateUIDScope",
    "ShadowCandidateEvaluator",
    "TransitionReason",
    "exact_chain_evidence_id",
]
