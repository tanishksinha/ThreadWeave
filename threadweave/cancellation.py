"""
threadweave.cancellation
~~~~~~~~~~~~~~~~~~~~~~~

Cooperative Cancellation Token Protocol and Task Lifecycle Manager.
Handles sub-millisecond cancellation propagation, state purging,
idempotency key generation, and compensating rollback transactions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from threadweave.models import (
    ActionType,
    RollbackAction,
    TaskStatus,
    ToolCallAction,
    ToolCancelAction,
    ToolCategory,
)
from threadweave.utils import now_ms, setup_logger

logger = setup_logger("threadweave.cancellation")


# ---------------------------------------------------------------------------
# Cancellation Token
# ---------------------------------------------------------------------------

class CancellationToken:
    """
    Cooperative cancellation token bound to a specific tool execution call_id.
    Yields control and enables non-blocking checks at every async step.
    """

    def __init__(self, call_id: str):
        self.call_id = call_id
        self._event = asyncio.Event()
        self.created_at: float = time.time()
        self.cancelled_at: Optional[float] = None
        self.cancel_reason: Optional[str] = None

    @property
    def is_cancelled(self) -> bool:
        """Instant non-blocking cancellation check."""
        return self._event.is_set()

    def cancel(self, reason: str = "interrupted") -> None:
        """Signal cancellation immediately."""
        if not self._event.is_set():
            self.cancelled_at = time.time()
            self.cancel_reason = reason
            self._event.set()

    async def wait_for_cancel(self) -> None:
        """Await until cancellation is signaled."""
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        """Raise asyncio.CancelledError if cancellation was requested."""
        if self.is_cancelled:
            raise asyncio.CancelledError(f"Task {self.call_id} was cancelled: {self.cancel_reason}")


class CancellationTokenSource:
    """Convenience source that manages a CancellationToken."""

    def __init__(self, call_id: Optional[str] = None):
        self.call_id = call_id or f"cts_{time.time()}"
        self.token = CancellationToken(call_id=self.call_id)

    def cancel(self, reason: str = "cancelled") -> None:
        self.token.cancel(reason=reason)

    def is_cancelled(self) -> bool:
        return self.token.is_cancelled


# ---------------------------------------------------------------------------
# Managed Task Wrapper
# ---------------------------------------------------------------------------

class ManagedTask:
    """Tracks state, idempotency, and lifecycle of a running tool task."""

    def __init__(
        self,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        category: ToolCategory,
        token: CancellationToken,
        idempotency_key: str,
        is_speculative: bool = False,
    ):
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.category = category
        self.token = token
        self.idempotency_key = idempotency_key
        self.is_speculative = is_speculative
        self.status: TaskStatus = TaskStatus.PENDING
        self.asyncio_task: Optional[asyncio.Task] = None
        self.start_time: float = time.time()
        self.completion_time: Optional[float] = None
        self.result: Any = None
        self.error: Optional[str] = None
        self.rolled_back: bool = False

    def mark_running(self, task: asyncio.Task) -> None:
        self.status = TaskStatus.RUNNING
        self.asyncio_task = task

    def mark_completed(self, result: Any) -> None:
        self.status = TaskStatus.COMPLETED
        self.completion_time = time.time()
        self.result = result

    def mark_cancelled(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.completion_time = time.time()

    def mark_rolled_back(self) -> None:
        self.status = TaskStatus.ROLLED_BACK
        self.rolled_back = True


# ---------------------------------------------------------------------------
# Task Lifecycle Manager
# ---------------------------------------------------------------------------

class TaskLifecycleManager:
    """
    Central manager for in-flight async tool tasks.
    Coordinates graceful cancellation, stale response purging,
    and automatic compensating rollback on state-modifying actions.
    """

    # Mapping of forward state-modifying tools to their compensating rollback tools
    COMPENSATING_TOOLS: Dict[str, str] = {
        "book_flight": "cancel_flight_booking",
        "book_train": "cancel_train_booking",
        "book_hotel": "cancel_hotel_booking",
        "create_booking": "cancel_booking",
        "confirm_ticket": "void_ticket",
        "charge_card": "refund_charge",
    }

    def __init__(self, output_queue: asyncio.Queue):
        self.output_queue = output_queue
        self.tasks: Dict[str, ManagedTask] = {}
        self.idempotency_log: Set[str] = set()
        self._stale_call_ids: Set[str] = set()

    @staticmethod
    def generate_idempotency_key(tool_name: str, arguments: Dict[str, Any]) -> str:
        """Create deterministic SHA-256 idempotency key for arguments."""
        normalized_args = json.dumps(arguments, sort_keys=True)
        raw = f"{tool_name}:{normalized_args}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_stale(self, call_id: str) -> bool:
        """Return True if a call_id has been cancelled or invalidated."""
        return call_id in self._stale_call_ids

    def register_task(
        self,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        category: ToolCategory,
        is_speculative: bool = False,
    ) -> Tuple[ManagedTask, CancellationToken]:
        """
        Create a ManagedTask and CancellationToken before dispatching.
        Generates and logs an idempotency key.
        """
        idempotency_key = self.generate_idempotency_key(tool_name, arguments)
        token = CancellationToken(call_id=call_id)
        managed = ManagedTask(
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            category=category,
            token=token,
            idempotency_key=idempotency_key,
            is_speculative=is_speculative,
        )
        self.tasks[call_id] = managed
        self.idempotency_log.add(idempotency_key)
        return managed, token

    async def cancel_task(
        self,
        call_id: str,
        reason: str = "interrupted",
    ) -> Optional[ToolCancelAction]:
        """
        Cancel an individual in-flight task with grace-period handling.
        If the task already completed and is state-modifying, triggers compensating rollback!
        """
        managed = self.tasks.get(call_id)
        if not managed or managed.status == TaskStatus.CANCELLED:
            return None

        self._stale_call_ids.add(call_id)
        managed.token.cancel(reason=reason)

        # Emit formal ToolCancelAction to Output Queue
        cancel_action = ToolCancelAction(
            call_id=call_id,
            tool_name=managed.tool_name,
            reason=reason,
            timestamp=time.time(),
        )
        await self.output_queue.put(cancel_action)
        logger.info(f"Emitted cancel action for call_id={call_id}, reason='{reason}'")

        # Cancel the active asyncio.Task if still running
        if managed.asyncio_task and not managed.asyncio_task.done():
            managed.asyncio_task.cancel()
            managed.mark_cancelled()
            logger.debug(f"Cancelled asyncio.Task for call_id={call_id}")
        elif managed.status in (TaskStatus.RUNNING, TaskStatus.PENDING):
            managed.mark_cancelled()
        elif managed.status == TaskStatus.COMPLETED:
            # The tool already completed before cancel arrived!
            # Check if it was state-modifying -> trigger compensating rollback
            if managed.category == ToolCategory.STATE_MODIFYING and not managed.rolled_back:
                logger.warning(
                    f"State-modifying task {call_id} ({managed.tool_name}) executed before cancel! "
                    f"Triggering compensating rollback transaction."
                )
                await self.trigger_compensating_rollback(managed, reason)

        return cancel_action

    async def cancel_all_in_flight(
        self,
        reason: str = "user_interruption",
        exempt_call_ids: Optional[Set[str]] = None,
    ) -> List[ToolCancelAction]:
        """
        Grace-period bulk cancellation of all active/speculative tasks.
        Instantly purges in-flight pipeline upon user barge-in.
        """
        exempt = exempt_call_ids or set()
        cancelled_actions: List[ToolCancelAction] = []

        for call_id, managed in list(self.tasks.items()):
            if call_id in exempt:
                continue
            if managed.status in (TaskStatus.RUNNING, TaskStatus.PENDING):
                action = await self.cancel_task(call_id, reason=reason)
                if action:
                    cancelled_actions.append(action)

        return cancelled_actions

    async def trigger_compensating_rollback(
        self,
        managed: ManagedTask,
        reason: str,
    ) -> Optional[RollbackAction]:
        """
        Emit a compensating rollback action to undo state changes from a prematurely executed tool.
        """
        rollback_tool = self.COMPENSATING_TOOLS.get(
            managed.tool_name,
            f"rollback_{managed.tool_name}",
        )
        
        # Build rollback arguments using original result or booking id
        rollback_args: Dict[str, Any] = {"original_call_id": managed.call_id}
        if isinstance(managed.result, dict):
            if "booking_id" in managed.result:
                rollback_args["booking_id"] = managed.result["booking_id"]
            if "ticket_id" in managed.result:
                rollback_args["ticket_id"] = managed.result["ticket_id"]
        rollback_args.update(managed.arguments)

        rollback_action = RollbackAction(
            original_call_id=managed.call_id,
            rollback_tool_name=rollback_tool,
            rollback_arguments=rollback_args,
            reason=reason,
            timestamp=time.time(),
        )

        managed.mark_rolled_back()
        await self.output_queue.put(rollback_action)
        logger.info(f"Emitted compensating rollback: {rollback_tool} for call_id={managed.call_id}")
        return rollback_action

    def get_in_flight_tasks(self) -> List[ManagedTask]:
        """Retrieve all currently executing or pending tasks."""
        return [
            t for t in self.tasks.values()
            if t.status in (TaskStatus.RUNNING, TaskStatus.PENDING)
        ]
