"""MemoryAction Enum + Typed KnowledgeUnit Mutations.

Replaces ad-hoc consolidation logic with typed, structured memory operations:
INSERT, UPDATE, MERGE, RETIRE — each with explicit preconditions and postconditions.

Inspired by EvolveMem's architectural insight:
memory mutations as a structured action space that a reasoning agent can plan against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryActionType(Enum):
    """Structured memory mutation types."""
    INSERT_UNIT = "insert_unit"    # add a new fact/knowledge unit
    UPDATE_FACTS = "update_facts"  # revise content of an existing unit
    MERGE_UNITS = "merge_units"    # combine two units into one
    RETIRE_STALE = "retire_stale"  # mark a unit inactive (soft-delete)


@dataclass
class MemoryAction:
    """A proposed memory mutation with metadata and provenance.

    Agents propose MemoryAction objects; the service validates and executes them.
    History is preserved in each knowledge unit's action_history field.
    """
    action_type: MemoryActionType
    target_ids: List[str] = field(default_factory=list)
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    proposed_by: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        # Normalize action_type from string if needed
        if isinstance(self.action_type, str):
            self.action_type = MemoryActionType(self.action_type)

    def validate(self) -> None:
        """Validate action preconditions. Raises ValueError on failure."""
        t = self.action_type
        ids = self.target_ids

        if t == MemoryActionType.INSERT_UNIT:
            # content required; target_ids empty or contains new ID
            if not self.content:
                raise ValueError("INSERT_UNIT requires content")

        elif t == MemoryActionType.UPDATE_FACTS:
            # exactly 1 existing ID; content required
            if len(ids) != 1:
                raise ValueError(f"UPDATE_FACTS requires exactly 1 target_id, got {len(ids)}")
            if not self.content:
                raise ValueError("UPDATE_FACTS requires content")

        elif t == MemoryActionType.MERGE_UNITS:
            # exactly 2 existing IDs; content optional
            if len(ids) != 2:
                raise ValueError(f"MERGE_UNITS requires exactly 2 target_ids, got {len(ids)}")

        elif t == MemoryActionType.RETIRE_STALE:
            # 1+ existing IDs; content not required
            if not ids:
                raise ValueError("RETIRE_STALE requires at least 1 target_id")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "target_ids": self.target_ids,
            "content": self.content,
            "metadata": self.metadata,
            "reason": self.reason,
            "proposed_by": self.proposed_by,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryAction":
        return cls(
            action_type=MemoryActionType(data["action_type"]),
            target_ids=data.get("target_ids", []),
            content=data.get("content"),
            metadata=data.get("metadata", {}),
            reason=data.get("reason", ""),
            proposed_by=data.get("proposed_by", ""),
            timestamp=data.get("timestamp", ""),
        )


# Validation rules summary:
# | Action        | target_ids       | content required |
# |---------------|-----------------|-----------------|
# | INSERT_UNIT   | empty or new ID | yes             |
# | UPDATE_FACTS  | exactly 1 ID    | yes             |
# | MERGE_UNITS   | exactly 2 IDs   | optional        |
# | RETIRE_STALE  | 1+ IDs          | no              |
