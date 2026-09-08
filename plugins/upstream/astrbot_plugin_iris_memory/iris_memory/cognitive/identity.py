"""Identity-owned durable Entity Registry and deterministic resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from .contracts import (
    CanonicalEntity,
    CognitiveContractError,
    EntityReference,
    IdentityClaim,
    IdentityClaimStatus,
    IdentityConfig,
    IdentityStore,
)


def _mention_key(mention: str) -> str:
    return mention.strip().casefold()


def _normalized_platform_ids(platform_ids: Mapping[str, str]) -> dict[str, str]:
    """Normalize platform bindings at the registry's identity boundary."""
    normalized: dict[str, str] = {}
    for platform, platform_id in platform_ids.items():
        platform_key = str(platform).strip().casefold()
        stable_id = str(platform_id).strip()
        if not platform_key or not stable_id:
            raise CognitiveContractError("platform identity requires a platform and UID")
        existing = normalized.get(platform_key)
        if existing is not None and existing != stable_id:
            raise CognitiveContractError(f"conflicting platform bindings for {platform_key}")
        normalized[platform_key] = stable_id
    return normalized


class EntityRegistry(IdentityStore):
    """Identity-owned, reversible registry with optional durable ownership."""

    owner = "Identity"

    _SCHEMA = "iris.identity-registry.v1"

    def __init__(
        self,
        config: IdentityConfig | None = None,
        *,
        storage_path: str | Path | None = None,
    ) -> None:
        self.config = config or IdentityConfig()
        self._entities: dict[str, CanonicalEntity] = {}
        self._claims: list[IdentityClaim] = []
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._lock = RLock()
        self._available = True
        if self._storage_path is not None and self._storage_path.exists():
            try:
                self._load()
            except (OSError, ValueError, TypeError, KeyError, CognitiveContractError):
                self._available = False
                self._entities.clear()
                self._claims.clear()
        else:
            self.register_entity(
                CanonicalEntity(
                    id=self.config.self_entity,
                    aliases=self.config.self_aliases,
                ),
                source="self_binding",
            )

    @property
    def self_entity(self) -> str:
        return self.config.self_entity

    @property
    def available(self) -> bool:
        return self._available

    def _payload(self) -> dict[str, object]:
        return {
            "schema": self._SCHEMA,
            "self_entity": self.self_entity,
            "entities": [
                {
                    "id": entity.id,
                    "aliases": list(entity.aliases),
                    "platform_ids": dict(entity.platform_ids),
                }
                for entity in sorted(self._entities.values(), key=lambda item: item.id)
            ],
            "claims": [
                {
                    "mention": claim.mention,
                    "candidate_entity": claim.candidate_entity,
                    "evidence": list(claim.evidence),
                    "confidence": claim.confidence,
                    "source": claim.source,
                    "status": claim.status.value,
                    "created_at": claim.created_at.isoformat(),
                }
                for claim in self._claims
            ],
        }

    @staticmethod
    def _digest(payload: object) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def _load(self) -> None:
        envelope = json.loads(self._storage_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
            raise ValueError("invalid identity registry envelope")
        payload = envelope["payload"]
        if self._digest(payload) != envelope["sha256"]:
            raise ValueError("identity registry checksum mismatch")
        if not isinstance(payload, dict) or set(payload) != {
            "schema", "self_entity", "entities", "claims"
        }:
            raise ValueError("invalid identity registry payload")
        if payload["schema"] != self._SCHEMA or payload["self_entity"] != self.self_entity:
            raise ValueError("identity registry owner mismatch")
        entities: dict[str, CanonicalEntity] = {}
        for raw in payload["entities"]:
            if not isinstance(raw, dict) or set(raw) != {"id", "aliases", "platform_ids"}:
                raise ValueError("invalid entity record")
            entity = CanonicalEntity(raw["id"], tuple(raw["aliases"]), raw["platform_ids"])
            if entity.id in entities:
                raise ValueError("duplicate entity")
            entities[entity.id] = entity
        if self.self_entity not in entities:
            raise ValueError("identity registry lacks SELF")
        claims = []
        for raw in payload["claims"]:
            if not isinstance(raw, dict) or set(raw) != {
                "mention", "candidate_entity", "evidence", "confidence", "source", "status", "created_at"
            }:
                raise ValueError("invalid identity claim")
            if raw["candidate_entity"] not in entities:
                raise ValueError("identity claim targets an unknown entity")
            claims.append(IdentityClaim(
                mention=raw["mention"],
                candidate_entity=raw["candidate_entity"],
                evidence=tuple(raw["evidence"]),
                confidence=raw["confidence"],
                source=raw["source"],
                status=IdentityClaimStatus(raw["status"]),
                created_at=datetime.fromisoformat(raw["created_at"]),
            ))
        # Validate platform uniqueness before publishing the loaded snapshot.
        seen: dict[tuple[str, str], str] = {}
        for entity in entities.values():
            for platform, uid in entity.platform_ids.items():
                key = (platform, uid)
                if key in seen and seen[key] != entity.id:
                    raise ValueError("platform identity collision")
                seen[key] = entity.id
        self._entities = entities
        self._claims = claims

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        if not self._available:
            raise CognitiveContractError("identity registry persistence is unavailable")
        payload = self._payload()
        encoded = json.dumps(
            {"payload": payload, "sha256": self._digest(payload)},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        path = self._storage_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            self._available = False
            raise

    def register_entity(self, entity: CanonicalEntity, *, source: str) -> None:
        """Register an entity and its explicitly supplied aliases/bindings."""
        if not source:
            raise CognitiveContractError("entity registration source is required")
        entity = replace(entity, platform_ids=_normalized_platform_ids(entity.platform_ids))
        with self._lock:
            existing = self._entities.get(entity.id)
            if existing and existing != entity:
                raise CognitiveContractError(f"entity already exists with different data: {entity.id}")
            if existing == entity:
                return
            for platform, platform_id in entity.platform_ids.items():
                for registered in self._entities.values():
                    if registered.id != entity.id and registered.platform_ids.get(platform) == platform_id:
                        raise CognitiveContractError(
                            f"platform identity already belongs to another entity: {platform}:{platform_id}"
                        )
            before_entities = dict(self._entities)
            before_claims = list(self._claims)
            self._entities[entity.id] = entity
            for alias in entity.aliases:
                self._claims.append(
                    IdentityClaim(
                        mention=alias,
                        candidate_entity=entity.id,
                        evidence=(f"entity registration: {entity.id}",),
                        confidence=1.0,
                        source=source,
                        status=IdentityClaimStatus.CONFIRMED,
                    )
                )
            try:
                self._persist()
            except Exception:
                self._entities = before_entities
                self._claims = before_claims
                raise

    def add_claim(self, claim: IdentityClaim) -> None:
        """Store evidence.  Only CONFIRMED claims participate in resolution."""
        if claim.candidate_entity not in self._entities:
            raise CognitiveContractError(
                f"claim candidate entity is not registered: {claim.candidate_entity}"
            )
        with self._lock:
            # Exact replay is idempotent; conflicting confirmed claims remain
            # visible and make alias resolution fail closed.
            if claim in self._claims:
                return
            self._claims.append(claim)
            try:
                self._persist()
            except Exception:
                self._claims.pop()
                raise

    def claims_for(self, mention: str) -> tuple[IdentityClaim, ...]:
        key = _mention_key(mention)
        return tuple(claim for claim in self._claims if _mention_key(claim.mention) == key)

    @classmethod
    def claim_id(cls, claim: IdentityClaim) -> str:
        """Return a stable opaque ID for exact administrative revocation."""
        return cls._digest(
            {
                "mention": claim.mention,
                "candidate_entity": claim.candidate_entity,
                "evidence": list(claim.evidence),
                "confidence": claim.confidence,
                "source": claim.source,
                "created_at": claim.created_at.isoformat(),
            }
        )[:24]

    def confirm_alias(
        self,
        *,
        mention: str,
        candidate_entity: str,
        evidence_ref: str,
        admin_id: str,
    ) -> IdentityClaim:
        """Add one explicit administrator-confirmed alias claim."""
        if not mention.strip() or not evidence_ref.strip() or not admin_id.strip():
            raise CognitiveContractError("alias, evidence reference and administrator are required")
        claim = IdentityClaim(
            mention=mention.strip(),
            candidate_entity=candidate_entity,
            evidence=(evidence_ref.strip(),),
            confidence=1.0,
            source=f"admin:{admin_id.strip()}",
            status=IdentityClaimStatus.CONFIRMED,
        )
        self.add_claim(claim)
        return claim

    def revoke_claim_id(self, claim_id: str) -> IdentityClaim:
        """Revoke exactly one claim selected from the administrative listing."""
        matches = [claim for claim in self._claims if self.claim_id(claim) == claim_id]
        if len(matches) != 1:
            raise CognitiveContractError("identity claim ID is missing or ambiguous")
        return self.revoke_claim(matches[0])

    def resolve_alias(self, mention: str) -> EntityReference | None:
        """Resolve only an unambiguous confirmed alias; otherwise fail closed."""
        confirmed = {
            claim.candidate_entity
            for claim in self.claims_for(mention)
            if claim.status is IdentityClaimStatus.CONFIRMED
        }
        if len(confirmed) != 1:
            return None
        entity_id = next(iter(confirmed))
        return EntityReference(
            entity_id=entity_id,
            source="confirmed_alias",
            confidence=1.0,
            evidence=(f"confirmed alias: {mention.strip()}",),
        )

    def resolve_platform_id(self, platform: str, platform_id: str) -> EntityReference | None:
        """Resolve a stable platform ID, creating only its deterministic entity."""
        normalized_platform = platform.strip().casefold()
        normalized_id = platform_id.strip()
        if not normalized_platform or not normalized_id:
            return None
        for entity in self._entities.values():
            if entity.platform_ids.get(normalized_platform) == normalized_id:
                return EntityReference(
                    entity.id,
                    "platform_uid",
                    1.0,
                    (f"{normalized_platform}:{normalized_id}",),
                )

        entity_id = f"person:{normalized_platform}:{normalized_id}"
        self.register_entity(
            CanonicalEntity(
                id=entity_id,
                platform_ids={normalized_platform: normalized_id},
            ),
            source="platform_uid",
        )
        return EntityReference(
            entity_id,
            "platform_uid",
            1.0,
            (f"{normalized_platform}:{normalized_id}",),
        )

    def resolve_mention(
        self,
        mention: str,
        *,
        platform: str = "",
        platform_id: str = "",
    ) -> EntityReference | None:
        """Apply the frozen priority order without any LLM fallback."""
        if platform and platform_id:
            platform_result = self.resolve_platform_id(platform, platform_id)
            if platform_result is not None:
                return platform_result
        return self.resolve_alias(mention)

    def resolve_coreference(
        self,
        mention: str,
        *,
        actor: EntityReference | None,
    ) -> EntityReference | None:
        """Conservative P0 coreference: only speaker ``我`` and confirmed aliases."""
        cleaned = mention.strip()
        if cleaned == "我":
            if actor is None:
                return None
            return EntityReference(
                actor.entity_id,
                "speaker_coreference",
                actor.confidence,
                ("first-person reference resolved to event actor",),
            )
        return self.resolve_alias(cleaned)

    def revoke_claim(self, claim: IdentityClaim) -> IdentityClaim:
        """Return the revoked record and remove its resolution authority."""
        with self._lock:
            for index, current in enumerate(self._claims):
                if current == claim:
                    revoked = replace(current, status=IdentityClaimStatus.REVOKED)
                    self._claims[index] = revoked
                    try:
                        self._persist()
                        return revoked
                    except Exception:
                        self._claims[index] = current
                        raise
        raise CognitiveContractError("identity claim is not registered")

    def entities(self) -> tuple[CanonicalEntity, ...]:
        return tuple(self._entities.values())

    def all_claims(self) -> tuple[IdentityClaim, ...]:
        return tuple(self._claims)


class IdentityResolver:
    """Thin resolver façade; Identity is the only writer of the registry."""

    owner = "Identity"

    def __init__(self, registry: EntityRegistry) -> None:
        self.registry = registry

    @property
    def self_entity(self) -> str:
        return self.registry.self_entity

    def resolve_actor(self, platform: str, platform_id: str, display_name: str = "") -> EntityReference | None:
        return self.registry.resolve_mention(
            display_name,
            platform=platform,
            platform_id=platform_id,
        )

    def resolve_event_self(self, platform: str, platform_id: str) -> EntityReference | None:
        """Bind SELF only from this event's explicit bot UID, never from text."""
        if not platform.strip() or not platform_id.strip():
            return None
        return EntityReference(
            self.self_entity,
            "event_self_uid",
            1.0,
            (f"{platform.strip().casefold()}:{platform_id.strip()}",),
        )

    def resolve_mentions(self, mentions: Iterable[tuple[str, str]]) -> tuple[EntityReference, ...]:
        resolved: list[EntityReference] = []
        for platform_id, display_name in mentions:
            entity = self.registry.resolve_mention(
                display_name,
                platform="qq",
                platform_id=platform_id,
            )
            if entity is not None:
                resolved.append(entity)
        return tuple(resolved)
