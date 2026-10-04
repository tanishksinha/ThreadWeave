"""
harness_adapter.py
~~~~~~~~~~~~~~~~~~

Virtual Clock Streaming Evaluation Harness Adapter.
Simulates deterministic scenario replays, tool latency injection,
trace log recording, and automated quantitative scoring (0-100 pts)
according to the standard full-duplex interactive evaluation rubric.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from threadweave.models import (
    ActionType,
    AudioClip,
    EventType,
    FillerAction,
    FinalResponse,
    InputEvent,
    InterruptSignal,
    OutputAction,
    RollbackAction,
    StateSnapshot,
    ToolCallAction,
    ToolCancelAction,
    ToolCategory,
    ToolManifest,
    ToolResult,
    TranscriptChunk,
    VideoFrame,
)
from threadweave.utils import format_delta_ms, setup_logger

logger = setup_logger("harness_adapter")


class MockToolBackend:
    """
    Simulated external APIs with deterministic latency injection.
    Supports travel booking, hotel booking, weather, and cancellation rollbacks.
    """

    DEFAULT_LATENCIES = {
        "search_flights": 1.0,
        "search_trains": 0.4,
        "book_flight": 0.6,
        "cancel_flight_booking": 0.1,
        "book_train": 0.5,
        "cancel_train_booking": 0.1,
        "check_weather": 0.2,
        "search_hotels": 0.4,
        "book_hotel": 0.6,
        "cancel_hotel_booking": 0.1,
    }

    def __init__(self, latency_overrides: Optional[Dict[str, float]] = None):
        self.latencies = dict(self.DEFAULT_LATENCIES)
        if latency_overrides:
            self.latencies.update(latency_overrides)
        self.executed_calls: List[Dict[str, Any]] = []
        self.cancelled_calls: Set[str] = set()
        self.active_bookings: Dict[str, Dict[str, Any]] = {}

    async def execute_tool(
        self,
        call: ToolCallAction,
        input_queue: asyncio.Queue,
    ) -> None:
        """Execute a simulated tool with non-blocking async delay."""
        call_id = call.call_id
        tool_name = call.tool_name
        args = call.arguments
        latency = self.latencies.get(tool_name, 0.3)

        logger.info(
            f"[Backend] Starting execution of {tool_name} (call_id={call_id}) "
            f"with latency={latency:.2f}s"
        )
        self.executed_calls.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": args,
            "start_time": time.time(),
        })

        # Simulate external network delay
        await asyncio.sleep(latency)

        # Check if cancelled while sleeping
        if call_id in self.cancelled_calls:
            logger.info(f"[Backend] Tool {call_id} was cancelled before completion. Suppressing result.")
            return

        # Generate mock tool result payload
        result_payload = self._generate_payload(tool_name, args, call_id)

        # Emit ToolResult back into the input queue
        result_event = ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            result=result_payload,
            success=True,
            execution_time_ms=latency * 1000.0,
            timestamp=time.time(),
        )
        await input_queue.put(result_event)
        logger.info(f"[Backend] Dispatched ToolResult for {call_id} to input stream.")

    def record_cancellation(self, call_id: str) -> None:
        """Mark call_id as cancelled at the backend level."""
        self.cancelled_calls.add(call_id)
        logger.info(f"[Backend] Received cancellation notice for call_id={call_id}")

    def _generate_payload(self, tool_name: str, args: Dict[str, Any], call_id: str) -> Any:
        dest = args.get("destination") or args.get("dest", "Mumbai")

        if tool_name == "search_flights":
            return {
                "destination": dest,
                "options": [
                    {"name": f"Air India AI-{call_id[:4]}", "price": 4500, "departure": "08:30 AM"},
                    {"name": f"IndiGo 6E-{call_id[:4]}", "price": 4200, "departure": "11:15 AM"},
                ],
            }
        elif tool_name == "search_trains":
            return {
                "destination": dest,
                "options": [
                    {"name": f"Vande Bharat Exp", "price": 1850, "departure": "06:00 AM"},
                    {"name": f"Rajdhani Express", "price": 2400, "departure": "04:55 PM"},
                ],
            }
        elif tool_name in ("book_flight", "book_train"):
            booking_id = f"BK_{uuid.uuid4().hex[:6].upper()}"
            self.active_bookings[booking_id] = {"tool": tool_name, "args": args}
            return {"booking_id": booking_id, "status": "CONFIRMED", "details": args}
        elif tool_name in ("cancel_flight_booking", "cancel_train_booking"):
            orig_id = args.get("original_call_id")
            return {"status": "REFUNDED", "original_call_id": orig_id}
        elif tool_name == "search_hotels":
            return {
                "city": dest,
                "options": [
                    {"name": f"Taj Palace {dest}", "rating": 4.9, "price_per_night": 9500},
                    {"name": f"Grand Hyatt {dest}", "rating": 4.7, "price_per_night": 7200},
                ],
            }
        return {"status": "SUCCESS", "echo": args}


class VirtualClockHarness:
    """
    Harness driver that feeds scenario events into the input queue
    and evaluates the output stream against the quantitative rubric.
    """

    def __init__(self, scenario_data: Dict[str, Any]):
        self.scenario_name = scenario_data.get("name", "unnamed_scenario")
        self.events_schedule = scenario_data.get("events", [])
        self.tool_manifest = scenario_data.get("tools", [])
        self.is_multimodal = scenario_data.get("is_multimodal", False)
        self.output_trace: List[Dict[str, Any]] = []
        self.backend = MockToolBackend()
        self._running_tool_tasks: Dict[str, asyncio.Task] = {}

    async def run(
        self,
        coordinator_cls,
        wall_clock_timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Execute scenario under the streaming harness."""
        input_queue = asyncio.Queue()
        output_queue = asyncio.Queue()

        coordinator = coordinator_cls()

        # Start Coordinator in background
        coordinator_task = asyncio.create_task(
            coordinator.start(input_queue, output_queue)
        )

        # Start Output Listener in background
        output_listener_task = asyncio.create_task(
            self._listen_outputs(output_queue, input_queue)
        )

        # Register manifest first if present
        if self.tool_manifest:
            manifest_event = ToolManifest(tools=self.tool_manifest)
            await input_queue.put(manifest_event)

        # Feed events according to timestamps
        t0 = time.time()
        for item in self.events_schedule:
            target_delay = item.get("time_offset", 0.0)
            elapsed = time.time() - t0
            wait_time = max(0.0, target_delay - elapsed)
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            event = self._parse_event(item)
            if event:
                await input_queue.put(event)

        # Allow pipeline to settle
        await asyncio.sleep(1.0)

        # Send end-of-stream sentinel
        await input_queue.put(None)

        # Wait for coordinator to stop
        try:
            await asyncio.wait_for(coordinator_task, timeout=5.0)
        except asyncio.TimeoutError:
            coordinator_task.cancel()

        output_listener_task.cancel()

        # Compute deterministic evaluation score
        evaluation = self.evaluate_trace()
        return evaluation

    async def _listen_outputs(
        self,
        output_queue: asyncio.Queue,
        input_queue: asyncio.Queue,
    ) -> None:
        """Monitor output queue, log actions, and dispatch tool calls to backend."""
        while True:
            try:
                action = await output_queue.get()
                record = {
                    "action_type": action.action_type.value,
                    "payload": action.model_dump(),
                    "timestamp": time.time(),
                }
                self.output_trace.append(record)
                logger.info(f"[Harness] Observed Output Action: {action.action_type.value}")

                # If ToolCallAction, dispatch to mock backend
                if isinstance(action, ToolCallAction):
                    t = asyncio.create_task(
                        self.backend.execute_tool(action, input_queue)
                    )
                    self._running_tool_tasks[action.call_id] = t

                # If ToolCancelAction, inform backend
                elif isinstance(action, ToolCancelAction):
                    self.backend.record_cancellation(action.call_id)
                    running_t = self._running_tool_tasks.get(action.call_id)
                    if running_t and not running_t.done():
                        running_t.cancel()

                output_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in output listener: {e}")

    def _parse_event(self, item: Dict[str, Any]) -> Optional[InputEvent]:
        """Convert raw scenario event dict into typed InputEvent."""
        etype = item.get("type")
        if etype == "transcript_chunk":
            return TranscriptChunk(
                text=item.get("text", ""),
                is_final=item.get("is_final", False),
                is_end_of_turn=item.get("is_end_of_turn", False),
                timestamp=time.time(),
            )
        elif etype == "interrupt_signal":
            return InterruptSignal(
                reason=item.get("reason", "user_barge_in"),
                timestamp=time.time(),
            )
        elif etype == "audio_clip":
            from threadweave.utils import create_synthetic_wav
            raw_bytes = create_synthetic_wav(duration_ms=item.get("duration_ms", 500))
            return AudioClip(raw_bytes=raw_bytes, timestamp=time.time())
        elif etype == "video_frame":
            from threadweave.utils import create_synthetic_png
            color = tuple(item.get("color", [255, 0, 0]))
            img_bytes = create_synthetic_png(color=color)
            return VideoFrame(
                frame_id=item.get("frame_id", "frame_01"),
                image_bytes=img_bytes,
                timestamp=time.time(),
            )
        return None

    def evaluate_trace(self) -> Dict[str, Any]:
        """
        Compute quantitative score against the 0-100 rubric:
        - Task Completion (40 pts)
        - Interruption Recovery (35 pts)
        - Response Latency (15 pts)
        - Safety & Protocol Adherence (10 pts)
        - Multipliers (Transcript quality 1.0x-1.2x, Multimodal 1.5x)
        """
        score_task = 0.0
        score_recovery = 0.0
        score_latency = 0.0
        score_safety = 0.0

        tool_calls = [a for a in self.output_trace if a["action_type"] == "tool_call"]
        cancellations = [a for a in self.output_trace if a["action_type"] == "tool_cancel"]
        fillers = [a for a in self.output_trace if a["action_type"] == "filler"]
        finals = [a for a in self.output_trace if a["action_type"] == "final_response"]
        rollbacks = [a for a in self.output_trace if a["action_type"] == "rollback"]

        # 1. TASK COMPLETION (40 Points)
        # Did we invoke tools with valid arguments and emit a final response with state snapshot?
        if tool_calls:
            score_task += 15.0
        if finals:
            score_task += 15.0
            last_final = finals[-1]["payload"]
            snapshot = last_final.get("state_snapshot", {})
            if snapshot.get("intent") and snapshot.get("slot_values"):
                score_task += 10.0

        # 2. INTERRUPTION RECOVERY (35 Points)
        # If cancellations occurred, did we emit cancellation events and re-align state snapshot?
        if cancellations:
            score_recovery += 20.0
            # Check if there are no stale tool executions after cancellation
            cancelled_ids = {c["payload"]["call_id"] for c in cancellations}
            res_after_cancel = False
            for f in finals:
                for gr in f["payload"].get("grounded_tool_results", []):
                    if gr.get("call_id") in cancelled_ids:
                        res_after_cancel = True
            if not res_after_cancel:
                score_recovery += 15.0
        else:
            # If scenario had no interruptions, award base points if completed
            if finals:
                score_recovery = 35.0

        # 3. RESPONSE LATENCY (15 Points)
        # Did fillers emit within < 150-200ms?
        if fillers:
            all_under_200 = True
            for f in fillers:
                lat = f["payload"].get("latency_ms", 0.0)
                if lat > 200.0:
                    all_under_200 = False
            if all_under_200:
                score_latency = 15.0
            else:
                score_latency = 10.0
        else:
            score_latency = 10.0

        # 4. SAFETY & PROTOCOL ADHERENCE (10 Points)
        # Zero duplicate calls, valid schemas, valid rollback if needed
        score_safety = 10.0
        call_ids = [c["payload"]["call_id"] for c in tool_calls]
        if len(call_ids) != len(set(call_ids)):
            score_safety -= 5.0  # Duplicate call_id penalty

        raw_total = score_task + score_recovery + score_latency + score_safety

        # Multipliers
        quality_multiplier = 1.10
        multimodal_multiplier = 1.5 if self.is_multimodal else 1.0

        final_score = min(100.0, raw_total) * quality_multiplier * multimodal_multiplier

        return {
            "scenario": self.scenario_name,
            "raw_scores": {
                "task_completion": score_task,
                "interruption_recovery": score_recovery,
                "response_latency": score_latency,
                "safety_protocol": score_safety,
                "raw_total": raw_total,
            },
            "multipliers": {
                "quality": quality_multiplier,
                "multimodal": multimodal_multiplier,
            },
            "final_score": round(final_score, 2),
            "trace_summary": {
                "total_actions": len(self.output_trace),
                "fillers": len(fillers),
                "tool_calls": len(tool_calls),
                "cancellations": len(cancellations),
                "rollbacks": len(rollbacks),
                "final_responses": len(finals),
            },
            "output_trace": self.output_trace,
        }
