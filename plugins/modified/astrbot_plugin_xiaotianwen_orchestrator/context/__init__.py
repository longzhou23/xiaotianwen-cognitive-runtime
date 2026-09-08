"""Read-only context adapters and deterministic shadow assembly."""

from .assembler import ContextAssembler, ContextAssemblyResult, PayloadStructuralDiff
from .bridge import ContextBridgeV1
from .budgets import DEFAULT_SOURCE_PRIORITIES, ContextAssemblyPolicy
from .memory import (
    AsyncSingleFlightCache,
    MemoryBudgetPolicy,
    MemoryQueryKey,
    TurnContextMemo,
    deduplicate_relationship_sections,
    is_low_information,
    normalize_memory_query,
)
from .providers import (
    ContextAwareAdapter,
    ImageContextPoolAdapter,
    IrisMemoryAdapter,
    SharedContextAdapter,
)

__all__ = [
    "DEFAULT_SOURCE_PRIORITIES",
    "AsyncSingleFlightCache",
    "ContextAssembler",
    "ContextAssemblyPolicy",
    "ContextAssemblyResult",
    "ContextAwareAdapter",
    "ContextBridgeV1",
    "ImageContextPoolAdapter",
    "IrisMemoryAdapter",
    "MemoryBudgetPolicy",
    "MemoryQueryKey",
    "PayloadStructuralDiff",
    "SharedContextAdapter",
    "TurnContextMemo",
    "deduplicate_relationship_sections",
    "is_low_information",
    "normalize_memory_query",
]
