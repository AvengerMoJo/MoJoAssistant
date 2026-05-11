"""Default GrowthModule implementation (Bonsai/BonsaiEngine backed)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.roles.role_manager import RoleManager
from app.scheduler.bonsai import BonsaiEngine, SnapshotManager
from app.services.provider_contracts import (
    GrowthProvider,
    GrowthSnapshot,
    ProviderVersion,
)

_role_manager = RoleManager()


class BonsaiGrowthModule(GrowthProvider):
    PROVIDER_NAME = "bonsai_growth"
    PROVIDER_VERSION = "1.0.0"
    CONTRACT_VERSION = "1.0"

    def __init__(self, hitl_callback: Optional[Callable] = None):
        # hitl_callback(role_id, proposal) -> decision str — injected by Core
        # when the HITL validation pillar is wired. None = no blocking validation.
        self._hitl_callback = hitl_callback

    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name=self.PROVIDER_NAME,
            provider_version=self.PROVIDER_VERSION,
            contract_version=self.CONTRACT_VERSION,
        )

    def snapshot(
        self, role_id: str, context: Optional[Dict[str, Any]] = None
    ) -> GrowthSnapshot:
        """Return current growth state for the role.

        Dimensions come from the live bonsai snapshot if one exists, otherwise
        fall back to the dimensions stored in the role file itself.
        """
        role = _role_manager.get(role_id) or {}
        sm = SnapshotManager(role_id)
        current = sm.get_current()

        if current is not None:
            dims = current.dimensions
            metadata: Dict[str, Any] = {
                "version": current.version,
                "trigger": current.trigger,
                "approved_by": current.approved_by,
                "presentation_patterns": current.presentation_patterns,
            }
        else:
            dims = role.get("dimensions") or {}
            metadata = {"version": 0, "source": "role_file"}

        return GrowthSnapshot(
            role_id=role_id,
            timestamp=datetime.now().isoformat(),
            dimensions=dims,
            metadata=metadata,
        )

    def evaluate(
        self, role_id: str, signals: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute dimension drift from signals.

        signals may be:
          {"signals": [{dimension, direction, strength, reason}, ...]}
          or a single signal dict {dimension, direction, strength, reason}
          or a list (also accepted for convenience).
        """
        if isinstance(signals, list):
            signal_list: List[Dict[str, Any]] = signals
        elif "signals" in signals:
            signal_list = signals["signals"]
        else:
            signal_list = [signals]

        current_snap = self.snapshot(role_id)
        current_dims = current_snap.dimensions

        engine = BonsaiEngine(role_id)
        new_dims = engine.compute_dimension_drift(current_dims, signal_list)
        validation = engine.validate_growth(current_dims, new_dims)

        return {
            "role_id": role_id,
            "current_dimensions": current_dims,
            "proposed_dimensions": new_dims,
            "validation": validation,
            "signal_count": len(signal_list),
        }

    def propose(
        self, role_id: str, evaluation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a candidate snapshot from an evaluation result and generate a growth report.

        Returns a proposal dict that can be passed to validate().
        """
        new_dims = evaluation.get("proposed_dimensions", {})
        role = _role_manager.get(role_id) or {}
        system_prompt = role.get("system_prompt", "")

        engine = BonsaiEngine(role_id)
        sm = SnapshotManager(role_id)
        current = sm.get_current()

        report = engine.generate_growth_report(
            old_snapshot=current,
            new_dimensions=new_dims,
            signals=None,
        )
        snapshot = engine.create_snapshot(
            dimensions=new_dims,
            system_prompt=system_prompt,
            trigger="growth_propose",
        )

        return {
            "role_id": role_id,
            "snapshot_version": snapshot.version,
            "report": report,
            "proposed_dimensions": new_dims,
            "validation": evaluation.get("validation", {}),
        }

    def validate(
        self, role_id: str, proposal: Dict[str, Any], decision: str
    ) -> Dict[str, Any]:
        """Accept or reject a growth proposal.

        decision: "accept" | "reject"

        "accept" pins the snapshot version from the proposal.
        "reject" leaves the current snapshot unchanged.

        When self._hitl_callback is set, it is called before persisting so the
        owner can confirm interactively (PRESENT pillar — future wiring point).
        """
        snapshot_version = proposal.get("snapshot_version")

        if self._hitl_callback is not None:
            decision = self._hitl_callback(role_id, proposal) or decision

        if decision == "accept" and snapshot_version is not None:
            sm = SnapshotManager(role_id)
            pinned = sm.pin_snapshot(int(snapshot_version))
            return {
                "status": "accepted",
                "role_id": role_id,
                "snapshot_version": snapshot_version,
                "pinned": pinned,
                "decision": decision,
            }

        return {
            "status": "rejected",
            "role_id": role_id,
            "snapshot_version": snapshot_version,
            "decision": decision,
        }

    def health_check(self) -> Dict[str, Any]:
        try:
            # Attempt a lightweight registry lookup with no file I/O
            from app.scheduler.bonsai import BonsaiEngine as _B  # noqa: F401
            return {
                "status": "ok",
                "details": {
                    "provider": self.PROVIDER_NAME,
                    "hitl_callback": self._hitl_callback is not None,
                },
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
