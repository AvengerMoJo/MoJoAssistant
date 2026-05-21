"""
Bonsai — Assistant Growth Architecture

Manages assistant personality evolution through:
1. Growth reports (before/after comparison)
2. DNA updates (NineChapter dimension drift)
3. Snapshot versioning (pinnable personality states)
4. Presentation patterns (domain-specific taste)
"""
# [mojo-integration]

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)


class GrowthSnapshot:
    """Represents a point-in-time snapshot of an assistant's personality state."""

    def __init__(
        self,
        role_id: str,
        version: int,
        dimensions: Dict[str, Dict[str, Any]],
        system_prompt: str,
        presentation_patterns: Optional[Dict[str, str]] = None,
        communication_style: Optional[List[str]] = None,
        trigger: str = "manual",
        approved_by: Optional[str] = None,
    ):
        self.role_id = role_id
        self.version = version
        self.dimensions = dimensions
        self.system_prompt = system_prompt
        self.presentation_patterns = presentation_patterns or {}
        self.communication_style = communication_style or []
        self.trigger = trigger
        self.approved_by = approved_by
        self.created_at = datetime.now().isoformat()
        self.system_prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "role_id": self.role_id,
            "created_at": self.created_at,
            "trigger": self.trigger,
            "dimensions": self.dimensions,
            "system_prompt_hash": self.system_prompt_hash,
            "communication_style": self.communication_style,
            "presentation_patterns": self.presentation_patterns,
            "approved_by": self.approved_by,
            "approved_at": self.created_at if self.approved_by else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], system_prompt: str = "") -> "GrowthSnapshot":
        return cls(
            role_id=data.get("role_id", "unknown"),
            version=data.get("version", 0),
            dimensions=data.get("dimensions", {}),
            system_prompt=system_prompt,
            presentation_patterns=data.get("presentation_patterns", {}),
            communication_style=data.get("communication_style", []),
            trigger=data.get("trigger", "unknown"),
            approved_by=data.get("approved_by"),
        )


class SnapshotManager:
    """Manages growth snapshots for an assistant role."""

    def __init__(self, role_id: str):
        self.role_id = role_id
        self.snapshots_dir = (
            Path(get_memory_subpath("roles")) / role_id / "growth_snapshots"
        )
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, version: int) -> Path:
        return self.snapshots_dir / f"v{version}.json"

    def _current_path(self) -> Path:
        return self.snapshots_dir / "current.json"

    def _pinned_path(self) -> Path:
        return self.snapshots_dir / "pinned.json"

    def get_current(self) -> Optional[GrowthSnapshot]:
        """Get the current growth snapshot."""
        path = self._current_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GrowthSnapshot.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load current snapshot: {e}")
            return None

    def get_pinned(self) -> Optional[GrowthSnapshot]:
        """Get the pinned (owner-approved) growth snapshot."""
        path = self._pinned_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GrowthSnapshot.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load pinned snapshot: {e}")
            return None

    def get_snapshot(self, version: int) -> Optional[GrowthSnapshot]:
        """Get a specific snapshot version."""
        path = self._snapshot_path(version)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GrowthSnapshot.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load snapshot v{version}: {e}")
            return None

    def save_snapshot(self, snapshot: GrowthSnapshot) -> Path:
        """Save a growth snapshot and update current."""
        path = self._snapshot_path(snapshot.version)
        path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Update current symlink
        current = self._current_path()
        if current.exists() or current.is_symlink():
            current.unlink()
        current.symlink_to(path.name)

        logger.info(f"Saved snapshot v{snapshot.version} for {self.role_id}")
        return path

    def pin_snapshot(self, version: int) -> bool:
        """Pin a specific version as the owner-approved state."""
        path = self._snapshot_path(version)
        if not path.exists():
            return False

        pinned = self._pinned_path()
        if pinned.exists() or pinned.is_symlink():
            pinned.unlink()
        pinned.symlink_to(path.name)

        logger.info(f"Pinned snapshot v{version} for {self.role_id}")
        return True

    def activate_snapshot(self, version: int, *, pin: bool = False) -> bool:
        """Switch current snapshot pointer to a specific version.

        This is the operational rollback/recall primitive used by GrowthProvider.
        If pin=True, also updates pinned.json to the same version.
        """
        path = self._snapshot_path(version)
        if not path.exists():
            return False

        current = self._current_path()
        if current.exists() or current.is_symlink():
            current.unlink()
        current.symlink_to(path.name)

        if pin:
            self.pin_snapshot(version)

        logger.info(
            "Activated snapshot v%s for %s (pin=%s)",
            version,
            self.role_id,
            pin,
        )
        return True

    def get_latest_version(self) -> int:
        """Get the latest snapshot version number."""
        versions = []
        for f in self.snapshots_dir.glob("v*.json"):
            try:
                v = int(f.stem[1:])
                versions.append(v)
            except ValueError:
                continue
        return max(versions) if versions else 0

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """List all snapshots with metadata."""
        snapshots = []
        for f in sorted(self.snapshots_dir.glob("v*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snapshots.append({
                    "version": data.get("version"),
                    "created_at": data.get("created_at"),
                    "trigger": data.get("trigger"),
                    "approved_by": data.get("approved_by"),
                })
            except Exception:
                continue
        return snapshots


class BonsaiEngine:
    """Core engine for assistant growth management."""

    def __init__(self, role_id: str):
        self.role_id = role_id
        self.snapshot_manager = SnapshotManager(role_id)

    def generate_growth_report(
        self,
        old_snapshot: Optional[GrowthSnapshot],
        new_dimensions: Dict[str, Dict[str, Any]],
        new_presentation_patterns: Optional[Dict[str, str]] = None,
        signals: Optional[List[str]] = None,
    ) -> str:
        """Generate a human-readable growth report comparing old vs new state."""
        lines = [
            f"# Assistant Growth Report: {self.role_id}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        if not old_snapshot:
            lines.append("## Initial State (No Previous Snapshot)")
            lines.append("")
            lines.append("This is the first growth snapshot for this assistant.")
            lines.append("")
            lines.append("## Current Dimensions")
            for dim_name, dim_data in new_dimensions.items():
                score = dim_data.get("score", 0)
                summary = dim_data.get("summary", "")
                lines.append(f"- **{dim_name}**: {score} — \"{summary}\"")
            return "\n".join(lines)

        # Before section
        lines.append("## Before (Previous State)")
        lines.append("")
        for dim_name, dim_data in old_snapshot.dimensions.items():
            score = dim_data.get("score", 0)
            summary = dim_data.get("summary", "")
            lines.append(f"- **{dim_name}**: {score} — \"{summary}\"")
        if old_snapshot.presentation_patterns:
            lines.append("")
            lines.append("**Presentation Patterns:**")
            for domain, pattern in old_snapshot.presentation_patterns.items():
                lines.append(f"- {domain}: {pattern}")
        lines.append("")

        # After section
        lines.append("## After (Proposed State)")
        lines.append("")
        for dim_name, dim_data in new_dimensions.items():
            score = dim_data.get("score", 0)
            summary = dim_data.get("summary", "")
            lines.append(f"- **{dim_name}**: {score} — \"{summary}\"")
        if new_presentation_patterns:
            lines.append("")
            lines.append("**Presentation Patterns:**")
            for domain, pattern in new_presentation_patterns.items():
                lines.append(f"- {domain}: {pattern}")
        lines.append("")

        # What changed
        changes = []
        for dim_name in new_dimensions:
            old_score = old_snapshot.dimensions.get(dim_name, {}).get("score", 0)
            new_score = new_dimensions.get(dim_name, {}).get("score", 0)
            if old_score != new_score:
                direction = "↑" if new_score > old_score else "↓"
                changes.append(f"- **{dim_name}**: {old_score} → {new_score} {direction}")

        if changes:
            lines.append("## What Changed")
            lines.append("")
            lines.extend(changes)
            lines.append("")

        # Signals
        if signals:
            lines.append("## Signals (What Drove This Change)")
            lines.append("")
            for signal in signals:
                lines.append(f"- {signal}")
            lines.append("")

        # Recommendation
        lines.append("## Recommendation")
        lines.append("")
        if changes:
            lines.append("This growth reflects accumulated signals from recent interactions.")
            lines.append("Review the changes above and decide whether to accept or adjust.")
        else:
            lines.append("No significant changes detected. Assistant personality is stable.")

        lines.append("")
        lines.append("---")
        lines.append("**Action Required:**")
        lines.append("- [ ] Accept growth (pin snapshot, update DNA)")
        lines.append("- [ ] Reject (revert to previous snapshot)")
        lines.append("- [ ] Adjust (modify direction, re-dream)")

        return "\n".join(lines)

    def compute_dimension_drift(
        self,
        current_dimensions: Dict[str, Dict[str, Any]],
        signals: List[Dict[str, Any]],
        max_drift: int = 5,
    ) -> Dict[str, Dict[str, Any]]:
        """Compute gradual dimension drift based on signals.

        Signals are dicts with:
        - dimension: which dimension to adjust
        - direction: "up" or "down"
        - strength: 0.0-1.0 how strong the signal is
        - reason: why this signal exists
        """
        new_dimensions = {}
        for dim_name, dim_data in current_dimensions.items():
            new_dim = dict(dim_data)
            current_score = dim_data.get("score", 75)

            # Apply signals for this dimension
            total_drift = 0
            for signal in signals:
                if signal.get("dimension") == dim_name:
                    direction = 1 if signal.get("direction") == "up" else -1
                    strength = signal.get("strength", 0.5)
                    drift = direction * min(max_drift, int(strength * max_drift))
                    total_drift += drift

            # Clamp drift
            total_drift = max(-max_drift, min(max_drift, total_drift))
            new_score = max(0, min(100, current_score + total_drift))

            if new_score != current_score:
                new_dim["score"] = new_score
                new_dim["drift_from"] = current_score
                new_dim["drift_reason"] = [
                    s.get("reason", "") for s in signals
                    if s.get("dimension") == dim_name
                ]

            new_dimensions[dim_name] = new_dim

        return new_dimensions

    def create_snapshot(
        self,
        dimensions: Dict[str, Dict[str, Any]],
        system_prompt: str,
        presentation_patterns: Optional[Dict[str, str]] = None,
        communication_style: Optional[List[str]] = None,
        trigger: str = "dreaming",
        approved_by: Optional[str] = None,
    ) -> GrowthSnapshot:
        """Create and save a new growth snapshot."""
        version = self.snapshot_manager.get_latest_version() + 1
        snapshot = GrowthSnapshot(
            role_id=self.role_id,
            version=version,
            dimensions=dimensions,
            system_prompt=system_prompt,
            presentation_patterns=presentation_patterns,
            communication_style=communication_style,
            trigger=trigger,
            approved_by=approved_by,
        )
        self.snapshot_manager.save_snapshot(snapshot)
        return snapshot

    def validate_growth(
        self,
        old_dimensions: Dict[str, Dict[str, Any]],
        new_dimensions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate that growth is internally consistent.

        Returns dict with:
        - valid: bool
        - issues: list of consistency issues
        - warnings: list of potential concerns
        """
        issues = []
        warnings = []

        # Check for contradictions
        cv = new_dimensions.get("core_values", {}).get("score", 75)
        cs = new_dimensions.get("cognitive_style", {}).get("score", 75)

        if cv >= 90 and cs < 60:
            issues.append(
                "High core_values but low cognitive_style is contradictory. "
                "Evidence rigor requires analytical capability."
            )

        so = new_dimensions.get("social_orientation", {}).get("score", 75)
        er = new_dimensions.get("emotional_reaction", {}).get("score", 75)

        if so >= 90 and er < 50:
            warnings.append(
                "High social_orientation with low emotional_reaction may lead to "
                "inconsistent interpersonal behavior."
            )

        # Check for dramatic shifts
        for dim_name in new_dimensions:
            old_score = old_dimensions.get(dim_name, {}).get("score", 75)
            new_score = new_dimensions.get(dim_name, {}).get("score", 75)
            diff = abs(new_score - old_score)
            if diff > 15:
                warnings.append(
                    f"{dim_name}: {old_score} → {new_score} is a large shift ({diff} points). "
                    "Consider gradual adjustment."
                )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
        }
