"""
threadweave.models
~~~~~~~~~~~~~~~~~

Pydantic data models defining the non-negotiable interface contract for ThreadWeave:
Dual Asynchronous Queues (Input Stream & Output Stream), State Snapshots,
Tool Schemas, and Cancellation Tokens.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Enumeration of all input event types."""
    TRANSCRIPT_CHUNK = "transcript_chunk"
    INTERRUPT_SIGNAL = "interrupt_signal"
    AUDIO_CLIP = "audio_clip"
    VIDEO_FRAME = "video_frame"
    TOOL_RESULT = "tool_result"
    TOOL_MANIFEST = "tool_manifest"


class ActionType(str, Enum):
    """Enumeration of all output action types."""
    FILLER = "filler"
    TOOL_CALL = "tool_call"
    TOOL_CANCEL = "tool_cancel"
    CLARIFICATION = "clarification"
    FINAL_RESPONSE = "final_response"
    ROLLBACK = "rollback"


class ToolCategory(str, Enum):
    """Classification of tool execution side-effects."""
    READ_ONLY = "read_only"
    STATE_MODIFYING = "state_modifying"


class TaskStatus(str, Enum):
    """Lifecycle state of an asynchronous tool invocation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Session State Snapshot
# ---------------------------------------------------------------------------

class StateSnapshot(BaseModel):
    """
    Session-scoped conversational state snapshot.
    Immutable record of current intent and resolved slot values.
    """
    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}")
    session_id: str = Field(default="default_session")
    version: int = Field(default=1, description="Monotonically increasing state version")
    intent: Optional[str] = Field(default=None, description="Active user intent (e.g. 'book_flight')")
    slot_values: Dict[str, Any] = Field(default_factory=dict, description="Accumulated key-value slots")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: float = Field(default_factory=time.time)

    def copy_with_update(
        self,
        new_intent: Optional[str] = None,
        slot_updates: Optional[Dict[str, Any]] = None,
        increment_version: bool = True,
    ) -> StateSnapshot:
        """Create a new snapshot with localized slot updates, preserving existing slots."""
        updated_slots = dict(self.slot_values)
        if slot_updates:
            updated_slots.update(slot_updates)
        return StateSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:8]}",
            session_id=self.session_id,
            version=self.version + (1 if increment_version else 0),
            intent=new_intent if new_intent is not None else self.intent,
            slot_values=updated_slots,
            confidence=self.confidence,
            timestamp=time.time(),
        )


# ---------------------------------------------------------------------------
# Tool Manifest & Definition
# ---------------------------------------------------------------------------

class ToolParameter(BaseModel):
    """Definition of an individual tool argument."""
    type: str = Field(..., description="Data type: 'string', 'integer', 'number', 'boolean', 'object'")
    description: str = Field(default="")
    required: bool = Field(default=False)
    default: Optional[Any] = None


class ToolDefinition(BaseModel):
    """Dynamic tool definition parsed from scenario tool manifest."""
    name: str
    description: str = ""
    parameters: Dict[str, ToolParameter] = Field(default_factory=dict)
    category: ToolCategory = ToolCategory.READ_ONLY
    idempotent: bool = True
    timeout_ms: int = 5000

    @classmethod
    def from_manifest_dict(cls, raw: Dict[str, Any]) -> ToolDefinition:
        """Parse raw manifest item and auto-classify tool side-effects."""
        name = raw.get("name", "")
        desc = raw.get("description", "").lower()
        params_raw = raw.get("parameters", {})
        
        # Determine category automatically if not explicitly specified
        raw_cat = raw.get("category")
        if raw_cat:
            cat = ToolCategory(raw_cat)
        else:
            state_modifying_keywords = (
                "book", "confirm", "create", "charge", "pay", "cancel",
                "reserve", "delete", "update", "modify", "transfer", "submit"
            )
            is_modifying = any(kw in name.lower() or kw in desc for kw in state_modifying_keywords)
            cat = ToolCategory.STATE_MODIFYING if is_modifying else ToolCategory.READ_ONLY

        params = {}
        for p_name, p_info in params_raw.items():
            if isinstance(p_info, dict):
                params[p_name] = ToolParameter(
                    type=p_info.get("type", "string"),
                    description=p_info.get("description", ""),
                    required=p_info.get("required", False),
                    default=p_info.get("default"),
                )
            else:
                params[p_name] = ToolParameter(type=str(p_info))

        return cls(
            name=name,
            description=raw.get("description", ""),
            parameters=params,
            category=cat,
            idempotent=raw.get("idempotent", cat == ToolCategory.READ_ONLY),
            timeout_ms=raw.get("timeout_ms", 5000),
        )


# ---------------------------------------------------------------------------
# Input Stream Events (Dual Asynchronous Queue - Input Side)
# ---------------------------------------------------------------------------

class TranscriptChunk(BaseModel):
    """Streaming speech-to-text partial or final transcript segment."""
    event_type: Literal[EventType.TRANSCRIPT_CHUNK] = EventType.TRANSCRIPT_CHUNK
    text: str
    is_final: bool = False
    is_end_of_turn: bool = False
    speaker: str = "user"
    timestamp: float = Field(default_factory=time.time)
    confidence: float = 1.0


class InterruptSignal(BaseModel):
    """Explicit barge-in or interruption signal from client/VAD layer."""
    event_type: Literal[EventType.INTERRUPT_SIGNAL] = EventType.INTERRUPT_SIGNAL
    reason: str = "user_barge_in"
    energy_level: Optional[float] = None
    timestamp: float = Field(default_factory=time.time)


class AudioClip(BaseModel):
    """Raw audio packet (.wav) for acoustic energy / multimodal evaluation."""
    event_type: Literal[EventType.AUDIO_CLIP] = EventType.AUDIO_CLIP
    audio_path: Optional[str] = None
    raw_bytes: Optional[bytes] = None
    sample_rate: int = 16000
    channels: int = 1
    duration_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class VideoFrame(BaseModel):
    """Camera/video frame (.png) for multimodal visual grounding."""
    event_type: Literal[EventType.VIDEO_FRAME] = EventType.VIDEO_FRAME
    frame_id: str = Field(default_factory=lambda: f"frame_{uuid.uuid4().hex[:6]}")
    image_path: Optional[str] = None
    image_bytes: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    timestamp: float = Field(default_factory=time.time)


class ToolResult(BaseModel):
    """Asynchronous tool execution result delivered back to input stream."""
    event_type: Literal[EventType.TOOL_RESULT] = EventType.TOOL_RESULT
    call_id: str
    tool_name: str
    result: Any
    success: bool = True
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class ToolManifest(BaseModel):
    """Scenario tool manifest defining available tools dynamically."""
    event_type: Literal[EventType.TOOL_MANIFEST] = EventType.TOOL_MANIFEST
    tools: List[Dict[str, Any]]
    timestamp: float = Field(default_factory=time.time)


# Discriminated Union for Input Stream
InputEvent = Union[
    TranscriptChunk,
    InterruptSignal,
    AudioClip,
    VideoFrame,
    ToolResult,
    ToolManifest,
]


# ---------------------------------------------------------------------------
# Output Stream Actions (Dual Asynchronous Queue - Output Side)
# ---------------------------------------------------------------------------

class FillerAction(BaseModel):
    """Ultra-low latency spoken conversational filler emitted in < 150ms."""
    action_type: Literal[ActionType.FILLER] = ActionType.FILLER
    text: str
    trigger_intent: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class ToolCallAction(BaseModel):
    """Non-blocking tool call dispatched to execution layer with explicit call_id."""
    action_type: Literal[ActionType.TOOL_CALL] = ActionType.TOOL_CALL
    call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")
    tool_name: str
    arguments: Dict[str, Any]
    category: ToolCategory = ToolCategory.READ_ONLY
    is_speculative: bool = False
    idempotency_key: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class ToolCancelAction(BaseModel):
    """Formal cancellation event signaling cancellation of in-flight call_id."""
    action_type: Literal[ActionType.TOOL_CANCEL] = ActionType.TOOL_CANCEL
    call_id: str
    tool_name: Optional[str] = None
    reason: str = "interruption"
    timestamp: float = Field(default_factory=time.time)


class ClarificationAction(BaseModel):
    """Targeted clarification request when required slots are missing or ambiguous."""
    action_type: Literal[ActionType.CLARIFICATION] = ActionType.CLARIFICATION
    missing_slots: List[str]
    question: str
    state_snapshot: StateSnapshot
    timestamp: float = Field(default_factory=time.time)


class RollbackAction(BaseModel):
    """Compensating transaction emitted when a state-modifying call executed before cancel arrived."""
    action_type: Literal[ActionType.ROLLBACK] = ActionType.ROLLBACK
    original_call_id: str
    rollback_tool_name: str
    rollback_arguments: Dict[str, Any]
    reason: str = "cancelled_after_execution"
    timestamp: float = Field(default_factory=time.time)


class FinalResponse(BaseModel):
    """Final synthesized grounded response carrying structured State Snapshot."""
    action_type: Literal[ActionType.FINAL_RESPONSE] = ActionType.FINAL_RESPONSE
    text: str
    state_snapshot: StateSnapshot
    grounded_tool_results: List[Dict[str, Any]] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


# Union of all Output Stream Actions
OutputAction = Union[
    FillerAction,
    ToolCallAction,
    ToolCancelAction,
    ClarificationAction,
    RollbackAction,
    FinalResponse,
]
