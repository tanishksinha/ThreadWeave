"""
tests.test_cancellation
~~~~~~~~~~~~~~~~~~~~~~~

Unit and integration tests for the Cooperative Cancellation Token Protocol,
Task Lifecycle Manager, Idempotency Keys, and Compensating Rollbacks.
"""

import asyncio
import pytest
import time
from threadweave.cancellation import (
    CancellationToken,
    ManagedTask,
    TaskLifecycleManager,
)
from threadweave.models import (
    ActionType,
    RollbackAction,
    TaskStatus,
    ToolCallAction,
    ToolCancelAction,
    ToolCategory,
)


@pytest.mark.asyncio
async def test_cancellation_token_basic():
    """Verify instant cooperative cancellation signaling."""
    token = CancellationToken(call_id="call_test_01")
    assert not token.is_cancelled

    token.cancel(reason="user_interrupted")
    assert token.is_cancelled
    assert token.cancel_reason == "user_interrupted"

    with pytest.raises(asyncio.CancelledError):
        token.raise_if_cancelled()


@pytest.mark.asyncio
async def test_task_lifecycle_manager_cancel_in_flight():
    """Verify grace-period cancellation of active async task."""
    output_queue = asyncio.Queue()
    manager = TaskLifecycleManager(output_queue=output_queue)

    managed, token = manager.register_task(
        call_id="call_flight_101",
        tool_name="search_flights",
        arguments={"destination": "Mumbai"},
        category=ToolCategory.READ_ONLY,
        is_speculative=True,
    )

    async def dummy_work():
        await asyncio.sleep(1.0)
        return "done"

    asyncio_task = asyncio.create_task(dummy_work())
    managed.mark_running(asyncio_task)

    # Issue cancellation
    cancel_action = await manager.cancel_task(
        call_id="call_flight_101",
        reason="intent_shift_abort",
    )

    assert cancel_action is not None
    assert cancel_action.call_id == "call_flight_101"
    assert token.is_cancelled
    assert manager.is_stale("call_flight_101")
    assert managed.status == TaskStatus.CANCELLED

    # Check action delivered to output queue
    action = await output_queue.get()
    assert isinstance(action, ToolCancelAction)
    assert action.call_id == "call_flight_101"


@pytest.mark.asyncio
async def test_compensating_rollback_on_completed_state_modifying_tool():
    """
    Test Idempotency & Rollback Protocol:
    When a state-modifying tool (book_flight) completed before cancellation arrived,
    the manager must immediately emit a compensating rollback transaction (cancel_flight_booking).
    """
    output_queue = asyncio.Queue()
    manager = TaskLifecycleManager(output_queue=output_queue)

    managed, token = manager.register_task(
        call_id="call_book_202",
        tool_name="book_flight",
        arguments={"destination": "Mumbai", "passenger": "Alice"},
        category=ToolCategory.STATE_MODIFYING,
        is_speculative=False,
    )

    # Tool finishes before cancel arrives!
    managed.mark_completed({"booking_id": "BK_9999", "status": "CONFIRMED"})

    # Now user changes mind and cancels!
    cancel_action = await manager.cancel_task(
        call_id="call_book_202",
        reason="user_changed_mind",
    )

    assert cancel_action is not None
    assert managed.rolled_back

    # Output queue should contain: 1) ToolCancelAction, 2) RollbackAction
    act1 = await output_queue.get()
    assert isinstance(act1, ToolCancelAction)

    act2 = await output_queue.get()
    assert isinstance(act2, RollbackAction)
    assert act2.rollback_tool_name == "cancel_flight_booking"
    assert act2.original_call_id == "call_book_202"
    assert act2.rollback_arguments.get("booking_id") == "BK_9999"


def test_idempotency_key_generation():
    """Verify deterministic SHA-256 idempotency key generation."""
    args1 = {"destination": "Delhi", "transport": "train"}
    args2 = {"transport": "train", "destination": "Delhi"}  # Key order reversed

    k1 = TaskLifecycleManager.generate_idempotency_key("search_trains", args1)
    k2 = TaskLifecycleManager.generate_idempotency_key("search_trains", args2)

    assert k1 == k2
    assert len(k1) == 16
