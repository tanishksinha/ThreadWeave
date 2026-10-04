"""
threadweave.coordinator
~~~~~~~~~~~~~~~~~~~~~~

Central Event Loop and Dual-Queue Orchestrator.
Manages concurrent async task groups, coordinates fast-path verbal fillers
with slow-path speculative tool execution, enforces sub-millisecond cancellation,
and maintains optimistic state synchronization.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from threadweave.cancellation import TaskLifecycleManager
from threadweave.fast_path import FastPathProcessor
from threadweave.models import (
    ActionType,
    AudioClip,
    EventType,
    FillerAction,
    FinalResponse,
    InputEvent,
    InterruptSignal,
    OutputAction,
    StateSnapshot,
    TaskStatus,
    ToolCallAction,
    ToolCancelAction,
    ToolCategory,
    ToolManifest,
    ToolResult,
    TranscriptChunk,
    VideoFrame,
)
from threadweave.multimodal import MultimodalPipeline
from threadweave.slow_path import SlowPathDispatcher
from threadweave.state_manager import SessionStateManager
from threadweave.utils import now_ms, setup_logger

logger = setup_logger("threadweave.coordinator")


class ThreadWeaveCoordinator:
    """
    Central Asynchronous Orchestration Loop for ThreadWeave.
    Connects strictly to the Input Stream and Output Stream asynchronous queues.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        enable_secondary_llm: bool = False,
    ):
        self.state_manager = SessionStateManager(session_id=session_id)
        self.fast_path = FastPathProcessor()
        self.multimodal = MultimodalPipeline()
        self.enable_secondary_llm = enable_secondary_llm

        # Coordination state
        self.input_queue: Optional[asyncio.Queue] = None
        self.output_queue: Optional[asyncio.Queue] = None
        self.task_manager: Optional[TaskLifecycleManager] = None
        self.slow_path: Optional[SlowPathDispatcher] = None

        self._accumulated_transcript: str = ""
        self._grounded_results: List[Dict[str, Any]] = []
        self._interaction_start_time: float = time.time()
        self._running: bool = False

    async def start(
        self,
        input_queue: asyncio.Queue,
        output_queue: asyncio.Queue,
    ) -> None:
        """
        Initialize and run the dual-loop concurrency architecture.
        Spawns non-blocking coroutines for stream processing.
        """
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.task_manager = TaskLifecycleManager(output_queue=self.output_queue)
        self.slow_path = SlowPathDispatcher(
            task_manager=self.task_manager,
            enable_secondary_llm=self.enable_secondary_llm,
        )
        self._running = True
        self._interaction_start_time = time.time()

        logger.info("ThreadWeave Coordinator started. Listening on Dual Queues...")
        try:
            await self._event_loop()
        except asyncio.CancelledError:
            logger.info("Coordinator main loop cancelled. Performing clean shutdown.")
        finally:
            self._running = False
            # Clean up all remaining in-flight tasks
            if self.task_manager:
                await self.task_manager.cancel_all_in_flight(reason="system_shutdown")

    async def stop(self) -> None:
        """Signal clean stop of the coordinator."""
        self._running = False

    async def _event_loop(self) -> None:
        """Continuous event consumption from input queue."""
        assert self.input_queue is not None
        assert self.output_queue is not None

        while self._running:
            event = await self.input_queue.get()

            # None is sentinel for end of scenario
            if event is None:
                logger.info("Received end-of-stream sentinel. Exiting event loop.")
                self.input_queue.task_done()
                break

            try:
                await self._handle_input_event(event)
            except Exception as exc:
                logger.exception(f"Error handling input event {type(event)}: {exc}")
            finally:
                self.input_queue.task_done()

    async def _handle_input_event(self, event: InputEvent) -> None:
        """Route event to appropriate Fast Path, Slow Path, or Multimodal handler."""
        assert self.output_queue is not None
        assert self.task_manager is not None
        assert self.slow_path is not None

        t_start = now_ms()

        # 1. TOOL MANIFEST (Dynamic Schema Registration)
        if isinstance(event, ToolManifest):
            self.slow_path.register_manifest(event)
            return

        # 2. AUDIO CLIP (Acoustic Energy & VAD)
        if isinstance(event, AudioClip):
            audio_info = self.multimodal.process_audio(event)
            if audio_info.get("is_speech"):
                self.fast_path.user_has_floor = True
            return

        # 3. VIDEO FRAME (Visual Grounding & Scene Change Detection)
        if isinstance(event, VideoFrame):
            scene_change = self.multimodal.process_frame(event)
            if scene_change:
                # Visual change detected! Check if active tasks should be invalidated
                logger.warning(
                    f"Visual scene shift detected (distance={scene_change.distance}). "
                    f"Invalidating visual parameters."
                )
                await self.task_manager.cancel_all_in_flight(reason="visual_scene_change")
            return

        # 4. EXPLICIT INTERRUPT SIGNAL (Barge-In)
        if isinstance(event, InterruptSignal):
            logger.warning(f"Barge-in signal received: {event.reason}")
            self.fast_path.user_has_floor = True
            # Cancel all in-flight tools within grace period (< 20ms)
            await self.task_manager.cancel_all_in_flight(reason="user_barge_in")
            return

        # 5. ASYNC TOOL RESULT (Execution Feedback)
        if isinstance(event, ToolResult):
            await self._handle_tool_result(event)
            return

        # 6. STREAMING TRANSCRIPT CHUNK
        if isinstance(event, TranscriptChunk):
            await self._handle_transcript_chunk(event)
            return

    async def _handle_transcript_chunk(self, chunk: TranscriptChunk) -> None:
        """Process streaming transcript chunks with dual-loop concurrency."""
        assert self.output_queue is not None
        assert self.task_manager is not None
        assert self.slow_path is not None

        # Update floor state
        self.fast_path.update_floor(chunk)

        # FAST PATH: Check for intent shift or barge-in negation
        shift_result = self.fast_path.detect_intent_shift(chunk.text)

        if shift_result.is_shift:
            # === INTERUPTION & PIVOT FLOW ===
            logger.warning(
                f"Fast Path detected intent shift: type='{shift_result.shift_type}', "
                f"pivot_target='{shift_result.pivot_target}'"
            )

            # 1. Sub-millisecond Task Cancellation & State Purging:
            # Cancel active in-flight calls (e.g. flight search 101)
            cancelled_actions = await self.task_manager.cancel_all_in_flight(
                reason=f"intent_shift_{shift_result.shift_type}"
            )
            # Purge any previously accumulated grounded results from invalidated intent
            self._grounded_results.clear()

            # 2. Extract new intent and slots from the pivot text
            # E.g. "...find trains to Delhi instead"
            new_intent, new_slots = self.slow_path.extract_slots(chunk.text)
            dest_hint = new_slots.get("destination") or self.state_manager.active_slots.get("destination")

            # 3. Emit verbal filler in < 150ms to hold the floor
            filler = self.fast_path.generate_filler(
                text=chunk.text,
                shift_result=shift_result,
                speculative_intent=new_intent,
                destination_hint=dest_hint,
            )
            if filler:
                await self.output_queue.put(filler)

            # 4. Atomic State Snapshot Realignment
            if new_intent:
                self.state_manager.update_intent(new_intent)
            if new_slots:
                self.state_manager.bulk_update_slots(new_slots)

            # Update accumulated transcript to reflect the new direction
            self._accumulated_transcript = chunk.text

            # 5. Dispatch new tool call for pivoted intent (e.g. search_trains call_id: 102)
            tool_call = self.slow_path.plan_tool_call(
                intent=self.state_manager.active_intent,
                slots=self.state_manager.active_slots,
                is_end_of_turn=chunk.is_end_of_turn,
            )
            if tool_call:
                await self.output_queue.put(tool_call)

            return

        # === REGULAR STREAMING / ACCUMULATION FLOW ===
        self._accumulated_transcript = (
            f"{self._accumulated_transcript} {chunk.text}".strip()
            if self._accumulated_transcript else chunk.text
        )

        # Extract current intent and slots from accumulated text
        intent, extracted_slots = self.slow_path.extract_slots(
            self._accumulated_transcript,
            current_slots=self.state_manager.active_slots,
        )

        dest_hint = extracted_slots.get("destination")

        # Emit conversational filler for first substantive query
        if intent and not self._grounded_results:
            filler = self.fast_path.generate_filler(
                text=chunk.text,
                shift_result=None,
                speculative_intent=intent,
                destination_hint=dest_hint,
            )
            if filler:
                await self.output_queue.put(filler)

        # State updates
        if intent and intent != self.state_manager.active_intent:
            self.state_manager.update_intent(intent)
        if extracted_slots:
            self.state_manager.bulk_update_slots(extracted_slots)

        # SLOW PATH: Plan speculative or confirmed tool execution
        tool_call = self.slow_path.plan_tool_call(
            intent=self.state_manager.active_intent,
            slots=self.state_manager.active_slots,
            is_end_of_turn=chunk.is_end_of_turn,
        )
        if tool_call:
            await self.output_queue.put(tool_call)

    async def _handle_tool_result(self, result_event: ToolResult) -> None:
        """Handle incoming asynchronous tool execution result."""
        assert self.output_queue is not None
        assert self.task_manager is not None
        assert self.slow_path is not None

        call_id = result_event.call_id

        # PURGE CHECK: Did cancellation occur while the tool was running?
        if self.task_manager.is_stale(call_id):
            logger.warning(
                f"Purging stale tool result for cancelled call_id={call_id} "
                f"({result_event.tool_name}). State mutation blocked!"
            )
            # Result is discarded without updating state or triggering response
            return

        # Mark completed in lifecycle manager
        managed = self.task_manager.tasks.get(call_id)
        if managed:
            managed.mark_completed(result_event.result)

        # Accumulate grounded tool result
        self._grounded_results.append({
            "call_id": call_id,
            "tool_name": result_event.tool_name,
            "result": result_event.result,
            "success": result_event.success,
        })

        # Synthesize final response grounded in tool result and active state snapshot
        snapshot = self.state_manager.get_snapshot()
        final_response = self.slow_path.synthesize_response(
            state_snapshot=snapshot,
            grounded_results=self._grounded_results,
            start_time=self._interaction_start_time,
        )
        await self.output_queue.put(final_response)
        logger.info(
            f"Emitted FinalResponse for snapshot v{snapshot.version} "
            f"(intent='{snapshot.intent}', total_latency={final_response.total_latency_ms:.1f}ms)"
        )
