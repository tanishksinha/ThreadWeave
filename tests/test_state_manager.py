"""
tests.test_state_manager
~~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for Session State Snapshot Engine, Localized Slot Correction,
and Rollback Log.
"""

from threadweave.state_manager import SessionStateManager


def test_session_scoped_isolation():
    """Verify session-scoped boundary and memory reset."""
    manager = SessionStateManager(session_id="session_01")
    manager.update_intent("book_flight")
    manager.update_slot("destination", "Mumbai")

    snap = manager.get_snapshot()
    assert snap.session_id == "session_01"
    assert snap.intent == "book_flight"
    assert snap.slot_values["destination"] == "Mumbai"

    # Reset session
    manager.clear_session()
    snap_after = manager.get_snapshot()
    assert snap_after.session_id != "session_01"
    assert snap_after.intent is None
    assert snap_after.slot_values == {}


def test_localized_slot_correction():
    """
    Test localized slot correction:
    When user corrects one slot ("Actually, tomorrow morning"),
    only that slot is updated while preserving all other established entities.
    """
    manager = SessionStateManager()

    # Turn 1: User says "Find trains to Delhi"
    manager.bulk_update_slots(
        updates={"transport": "train", "destination": "Delhi"},
        new_intent="search_trains",
    )
    snap1 = manager.get_snapshot()
    assert snap1.slot_values == {"transport": "train", "destination": "Delhi"}
    assert snap1.version == 2

    # Turn 2: User says "Actually, tomorrow morning"
    manager.update_slot("departure_time", "tomorrow morning")
    snap2 = manager.get_snapshot()

    # 'transport' and 'destination' MUST be strictly preserved!
    assert snap2.slot_values["transport"] == "train"
    assert snap2.slot_values["destination"] == "Delhi"
    assert snap2.slot_values["departure_time"] == "tomorrow morning"
    assert snap2.version == 3


def test_state_rollback_to_version():
    """Verify time-travel state rollback unwinds speculative mutations."""
    manager = SessionStateManager()
    manager.update_slot("destination", "Mumbai")  # v2
    manager.update_slot("transport", "flight")    # v3

    assert manager.current_snapshot.version == 3
    assert manager.current_snapshot.slot_values["transport"] == "flight"

    # Speculative mutation that gets aborted
    manager.update_slot("transport", "train")     # v4
    assert manager.current_snapshot.slot_values["transport"] == "train"

    # Roll back to version 3
    restored = manager.rollback_to_version(3)
    assert restored is not None
    assert restored.slot_values["transport"] == "flight"
    assert restored.slot_values["destination"] == "Mumbai"
