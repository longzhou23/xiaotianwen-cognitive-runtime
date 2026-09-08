"""Ingress normalization, deduplication and no-dispatch debounce state."""

from .debounce import (
    ShadowIngestResult,
    ShadowTurnCoordinator,
    ShadowTurnSnapshot,
    TurnState,
)
from .deduplicate import (
    EventDeduplicator,
    conversation_key_from_event,
    event_fingerprint,
    event_to_envelope,
)
from .ownership import (
    CanaryPolicy,
    OrchestratorMode,
    OwnershipDecision,
    PrimaryReplyOwnership,
)

__all__ = [
    "CanaryPolicy",
    "EventDeduplicator",
    "OrchestratorMode",
    "OwnershipDecision",
    "PrimaryReplyOwnership",
    "ShadowIngestResult",
    "ShadowTurnCoordinator",
    "ShadowTurnSnapshot",
    "TurnState",
    "conversation_key_from_event",
    "event_fingerprint",
    "event_to_envelope",
]
