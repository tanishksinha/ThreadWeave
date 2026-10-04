"""
threadweave.slow_path
~~~~~~~~~~~~~~~~~~~~

Slow Path Execution Engine (Cloud / Core Reasoning Layer).
Features:
  - Dynamic tool manifest parsing at runtime
  - Auto-classification of read-only vs state-modifying tools
  - Speculative tool execution with locking policies
  - Robust rule/regex slot extraction with optional secondary LLM hook
  - Final response synthesis and state grounding
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from threadweave.cancellation import CancellationToken, TaskLifecycleManager
from threadweave.models import (
    ActionType,
    FinalResponse,
    StateSnapshot,
    TaskStatus,
    ToolCallAction,
    ToolCategory,
    ToolDefinition,
    ToolManifest,
    ToolResult,
)
from threadweave.utils import format_delta_ms, setup_logger

logger = setup_logger("threadweave.slow_path")


class SlowPathDispatcher:
    """
    Core reasoning and asynchronous tool dispatcher.
    Governs speculative execution policies and schema compliance.
    """

    # Destination and transport extraction patterns
    CITIES = [
        "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad",
        "chennai", "kolkata", "pune", "ahmedabad", "jaipur", "goa",
        "new york", "london", "singapore", "tokyo", "paris"
    ]

    def __init__(
        self,
        task_manager: TaskLifecycleManager,
        enable_secondary_llm: bool = False,
    ):
        self.task_manager = task_manager
        self.enable_secondary_llm = enable_secondary_llm
        self.tool_manifest: Dict[str, ToolDefinition] = {}
        self._last_speculative_call_id: Optional[str] = None
        self._confirmed_call_ids: Set[str] = set()

    def register_manifest(self, manifest: ToolManifest) -> Dict[str, ToolDefinition]:
        """
        Dynamically register tools from incoming ToolManifest at runtime.
        Auto-classifies tools into READ_ONLY or STATE_MODIFYING.
        """
        for item in manifest.tools:
            tool_def = ToolDefinition.from_manifest_dict(item)
            self.tool_manifest[tool_def.name] = tool_def
            logger.info(
                f"Registered tool: '{tool_def.name}' [{tool_def.category.value}] "
                f"(idempotent={tool_def.idempotent}, timeout={tool_def.timeout_ms}ms)"
            )
        return self.tool_manifest

    def extract_slots(
        self,
        accumulated_text: str,
        current_slots: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Extract intent and slot entities from accumulated transcript.
        Applies non-destructive extraction preserving existing established slots.
        """
        text = accumulated_text.lower().strip()
        slots: Dict[str, Any] = dict(current_slots or {})
        detected_intent: Optional[str] = None

        # Detect Transport & Target Intent
        if "flight" in text or "fly" in text or "plane" in text:
            slots["transport"] = "flight"
            detected_intent = "search_flights" if "search" in text or "find" in text else "book_flight"
        elif "train" in text or "railway" in text:
            slots["transport"] = "train"
            detected_intent = "search_trains" if "search" in text or "find" in text else "book_train"
        elif "hotel" in text or "room" in text or "stay" in text:
            slots["transport"] = "hotel"
            detected_intent = "search_hotels"

        # Detect Cities / Destinations
        for city in self.CITIES:
            # Check "to <city>", "in <city>", "for <city>"
            if re.search(rf"\b(to|in|for|at)\s+{city}\b", text):
                slots["destination"] = city.capitalize()
            elif city in text and "destination" not in slots:
                slots["destination"] = city.capitalize()

        # Detect Origin
        for city in self.CITIES:
            if re.search(rf"\b(from)\s+{city}\b", text):
                slots["origin"] = city.capitalize()

        # Detect Time / Date hints
        if "tomorrow morning" in text:
            slots["departure_time"] = "tomorrow morning"
        elif "tomorrow" in text:
            slots["departure_time"] = "tomorrow"
        elif "morning" in text:
            slots["departure_time"] = "morning"
        elif "evening" in text or "tonight" in text:
            slots["departure_time"] = "evening"

        # Fallback to secondary LLM if enabled and slots are ambiguous
        if self.enable_secondary_llm and (not detected_intent or "destination" not in slots):
            detected_intent, llm_slots = self._secondary_llm_extract(accumulated_text)
            slots.update(llm_slots)

        return detected_intent, slots

    def _secondary_llm_extract(self, text: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Secondary option for complex disambiguation when keyword heuristics are ambiguous.
        Stays deterministic and local when no external cloud credentials exist.
        """
        logger.debug(f"Secondary LLM fallback invoked for text: '{text}'")
        # In a production environment with cloud credentials, call OpenAI/Claude/Gemini API here.
        # For headless hermetic execution, return extracted entities safely.
        return None, {}

    def plan_tool_call(
        self,
        intent: Optional[str],
        slots: Dict[str, Any],
        is_end_of_turn: bool = False,
    ) -> Optional[ToolCallAction]:
        """
        Evaluate current conversational context and emit a non-blocking ToolCallAction.
        Enforces:
          - Speculative dispatch for READ_ONLY search tools
          - Strict locking policy for STATE_MODIFYING tools (must wait for end_of_turn & all slots)
        """
        if not intent:
            return None

        # In speculative mode (partial utterance), prefer read-only search tool if available
        if not is_end_of_turn:
            search_equivalents = {
                "book_flight": "search_flights",
                "book_train": "search_trains",
                "book_hotel": "search_hotels",
            }
            spec_tool = search_equivalents.get(intent)
            if spec_tool and spec_tool in self.tool_manifest:
                target_tool = spec_tool
            else:
                target_tool = self._resolve_tool_name(intent)
        else:
            target_tool = self._resolve_tool_name(intent)

        if not target_tool:
            return None

        tool_def = self.tool_manifest.get(target_tool)
        category = tool_def.category if tool_def else ToolCategory.READ_ONLY

        # Build arguments matching tool parameters
        arguments = self._build_tool_arguments(target_tool, slots)

        # Apply Execution Policies:
        if category == ToolCategory.STATE_MODIFYING:
            # Strict Locking Policy: Only fire when user finished speaking (is_end_of_turn=True)
            # and all required arguments are present!
            if not is_end_of_turn:
                logger.debug(
                    f"State-modifying tool '{target_tool}' locked: waiting for end of turn confirmation."
                )
                return None

            if not self._validate_required_arguments(target_tool, arguments):
                logger.debug(f"State-modifying tool '{target_tool}' missing required arguments.")
                return None

            is_speculative = False
        else:
            # Read-Only tools can be launched speculatively on partial intent!
            is_speculative = not is_end_of_turn

        call_id = f"call_{uuid.uuid4().hex[:6]}"
        if is_speculative:
            self._last_speculative_call_id = call_id
        else:
            self._confirmed_call_ids.add(call_id)

        # Register task in TaskLifecycleManager
        managed_task, token = self.task_manager.register_task(
            call_id=call_id,
            tool_name=target_tool,
            arguments=arguments,
            category=category,
            is_speculative=is_speculative,
        )

        logger.info(
            f"Planned tool call: {target_tool} (call_id={call_id}, "
            f"category={category.value}, speculative={is_speculative})"
        )

        return ToolCallAction(
            call_id=call_id,
            tool_name=target_tool,
            arguments=arguments,
            category=category,
            is_speculative=is_speculative,
            idempotency_key=managed_task.idempotency_key,
            timestamp=time.time(),
        )

    def _resolve_tool_name(self, intent: str) -> Optional[str]:
        """Match intent name to registered manifest tool names."""
        if intent in self.tool_manifest:
            return intent

        # Mapping aliases
        mapping = {
            "book_flight": "search_flights",  # Speculatively search first
            "book_train": "search_trains",    # Speculatively search first
            "book_hotel": "search_hotels",
            "confirm_flight": "book_flight",
            "confirm_train": "book_train",
            "confirm_hotel": "book_hotel",
        }
        candidate = mapping.get(intent)
        if candidate and candidate in self.tool_manifest:
            return candidate

        for tool_name in self.tool_manifest:
            if tool_name in intent or intent in tool_name:
                return tool_name

        return None

    def _build_tool_arguments(self, tool_name: str, slots: Dict[str, Any]) -> Dict[str, Any]:
        """Construct arguments dict complying with tool definition schema."""
        args: Dict[str, Any] = {}
        tool_def = self.tool_manifest.get(tool_name)
        if not tool_def:
            return dict(slots)

        for param_name in tool_def.parameters:
            if param_name in slots:
                args[param_name] = slots[param_name]
            elif param_name == "destination" and "destination" in slots:
                args["destination"] = slots["destination"]
            elif param_name == "dest" and "destination" in slots:
                args["dest"] = slots["destination"]
            elif param_name == "origin" and "origin" in slots:
                args["origin"] = slots["origin"]
            elif param_name == "date" and "departure_time" in slots:
                args["date"] = slots["departure_time"]

        # If no arguments matched specifically, pass along destination if available
        if not args and "destination" in slots:
            args["destination"] = slots["destination"]

        return args

    def _validate_required_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Ensure all required parameters in manifest are populated."""
        tool_def = self.tool_manifest.get(tool_name)
        if not tool_def:
            return True
        for param_name, param in tool_def.parameters.items():
            if param.required and param_name not in arguments:
                return False
        return True

    def synthesize_response(
        self,
        state_snapshot: StateSnapshot,
        grounded_results: List[Dict[str, Any]],
        start_time: float,
    ) -> FinalResponse:
        """
        Synthesize grounded conversational response with embedded State Snapshot.
        Ensures response accuracy and strict schema adherence.
        """
        intent = state_snapshot.intent or "request"
        slots = state_snapshot.slot_values
        dest = slots.get("destination", "your destination")
        transport = slots.get("transport", "travel")

        # Construct grounded response text based on tool results
        if grounded_results:
            latest_res = grounded_results[-1].get("result")
            if isinstance(latest_res, dict) and "options" in latest_res:
                options = latest_res["options"]
                text = (
                    f"I found {len(options)} {transport} options to {dest}. "
                    f"Top option: {options[0].get('name', 'Direct')} departing at "
                    f"{options[0].get('departure', 'scheduled time')} for INR {options[0].get('price', 'N/A')}."
                )
            elif isinstance(latest_res, dict) and "booking_id" in latest_res:
                b_id = latest_res["booking_id"]
                text = f"Successfully confirmed your {transport} booking to {dest}. Confirmation ID is {b_id}."
            else:
                text = f"Here are the details for your {transport} to {dest}: {latest_res}."
        else:
            text = f"I have noted your request for {transport} to {dest}."

        total_latency_ms = (time.time() - start_time) * 1000.0

        return FinalResponse(
            text=text,
            state_snapshot=state_snapshot,
            grounded_tool_results=grounded_results,
            total_latency_ms=total_latency_ms,
            timestamp=time.time(),
        )
