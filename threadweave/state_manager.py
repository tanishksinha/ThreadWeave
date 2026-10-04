"""
threadweave.state_manager
~~~~~~~~~~~~~~~~~~~~~~~~

Session State Snapshot Engine, Localized Slot Tracking,
and Transactional Rollback Log.
Guarantees session-scoped isolation and atomic multi-turn slot mutations.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from threadweave.models import StateSnapshot
from threadweave.utils import setup_logger

logger = setup_logger("threadweave.state_manager")


class SlotMutationRecord:
    """Audit entry for slot level mutations enabling fine-grained rollbacks."""

    def __init__(
        self,
        version: int,
        key: str,
        old_value: Any,
        new_value: Any,
        timestamp: float,
    ):
        self.version = version
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.timestamp = timestamp


class SessionStateManager:
    """
    Session-Scoped State Engine.
    Maintains an active snapshot, history of versions, and slot mutation log.
    Ensures that localized corrections (e.g. "Actually, tomorrow morning")
    mutate only the targeted slot while preserving established context.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self._current_snapshot = StateSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:8]}",
            session_id=self.session_id,
            version=1,
            intent=None,
            slot_values={},
            timestamp=time.time(),
        )
        self._snapshot_history: List[StateSnapshot] = [self._current_snapshot]
        self._mutation_log: List[SlotMutationRecord] = []

    @property
    def current_snapshot(self) -> StateSnapshot:
        """Read-only view of the latest active snapshot."""
        return self._current_snapshot

    @property
    def active_intent(self) -> Optional[str]:
        """Current active user intent."""
        return self._current_snapshot.intent

    @property
    def active_slots(self) -> Dict[str, Any]:
        """Dictionary copy of currently accumulated slots."""
        return dict(self._current_snapshot.slot_values)

    def update_intent(self, new_intent: str) -> StateSnapshot:
        """
        Transition or refine the current active intent.
        Increments the state snapshot version.
        """
        if self._current_snapshot.intent == new_intent:
            return self._current_snapshot

        new_snapshot = self._current_snapshot.copy_with_update(
            new_intent=new_intent,
            increment_version=True,
        )
        self._current_snapshot = new_snapshot
        self._snapshot_history.append(new_snapshot)
        logger.info(
            f"Intent updated: '{self._snapshot_history[-2].intent}' -> '{new_intent}' "
            f"(version {new_snapshot.version})"
        )
        return self._current_snapshot

    def update_slot(self, key: str, value: Any) -> StateSnapshot:
        """
        Perform a localized slot update.
        Preserves all other established slots and increments version.
        """
        old_value = self._current_snapshot.slot_values.get(key)
        if old_value == value:
            return self._current_snapshot

        new_slots = dict(self._current_snapshot.slot_values)
        new_slots[key] = value

        record = SlotMutationRecord(
            version=self._current_snapshot.version + 1,
            key=key,
            old_value=old_value,
            new_value=value,
            timestamp=time.time(),
        )
        self._mutation_log.append(record)

        new_snapshot = self._current_snapshot.copy_with_update(
            slot_updates={key: value},
            increment_version=True,
        )
        self._current_snapshot = new_snapshot
        self._snapshot_history.append(new_snapshot)
        logger.info(f"Slot '{key}' updated: '{old_value}' -> '{value}' (v{new_snapshot.version})")
        return self._current_snapshot

    def bulk_update_slots(
        self,
        updates: Dict[str, Any],
        new_intent: Optional[str] = None,
    ) -> StateSnapshot:
        """
        Atomically update multiple slots and/or intent in a single version bump.
        Logs each mutation record for audit and rollback.
        """
        if not updates and (new_intent is None or new_intent == self._current_snapshot.intent):
            return self._current_snapshot

        current_slots = dict(self._current_snapshot.slot_values)
        target_version = self._current_snapshot.version + 1

        for k, v in updates.items():
            old_v = current_slots.get(k)
            if old_v != v:
                record = SlotMutationRecord(
                    version=target_version,
                    key=k,
                    old_value=old_v,
                    new_value=v,
                    timestamp=time.time(),
                )
                self._mutation_log.append(record)

        new_snapshot = self._current_snapshot.copy_with_update(
            new_intent=new_intent,
            slot_updates=updates,
            increment_version=True,
        )
        self._current_snapshot = new_snapshot
        self._snapshot_history.append(new_snapshot)
        logger.info(
            f"Atomic state update: intent='{new_snapshot.intent}', "
            f"slots={new_snapshot.slot_values} (v{new_snapshot.version})"
        )
        return self._current_snapshot

    def rollback_to_version(self, target_version: int) -> Optional[StateSnapshot]:
        """
        Roll back the state snapshot to a specific previous version.
        Guarantees that speculative changes can be unwound on interruption.
        """
        for snap in reversed(self._snapshot_history):
            if snap.version == target_version:
                # Create a new version that restores previous values
                restored = snap.copy_with_update(increment_version=True)
                self._current_snapshot = restored
                self._snapshot_history.append(restored)
                logger.warning(
                    f"Rolled back state to version {target_version} -> created restored v{restored.version}"
                )
                return self._current_snapshot
        logger.error(f"Cannot rollback: version {target_version} not found in history")
        return None

    def get_snapshot(self) -> StateSnapshot:
        """Return the current serialized state snapshot."""
        return self._current_snapshot

    def clear_session(self) -> None:
        """Reset session memory. Enforces session-scoped isolation."""
        self.session_id = f"sess_{uuid.uuid4().hex[:8]}"
        self._current_snapshot = StateSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:8]}",
            session_id=self.session_id,
            version=1,
            intent=None,
            slot_values={},
            timestamp=time.time(),
        )
        self._snapshot_history = [self._current_snapshot]
        self._mutation_log.clear()
        logger.info(f"Session memory cleared. New session_id={self.session_id}")
