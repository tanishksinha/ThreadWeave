"""
threadweave.fast_path
~~~~~~~~~~~~~~~~~~~~

Ultra-low-latency Fast Path Engine (< 150ms budget).
Provides real-time intent shift detection, conversational floor management,
acoustic energy thresholding, and instantaneous verbal filler generation.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from threadweave.models import (
    ActionType,
    AudioClip,
    EventType,
    FillerAction,
    InterruptSignal,
    TranscriptChunk,
)
from threadweave.utils import format_delta_ms, now_ms, setup_logger

logger = setup_logger("threadweave.fast_path")


class IntentShiftResult:
    """Detection output for rapid stream classification."""

    def __init__(
        self,
        is_shift: bool,
        shift_type: str,
        detected_keywords: List[str],
        pivot_target: Optional[str] = None,
        confidence: float = 1.0,
    ):
        self.is_shift = is_shift
        self.shift_type = shift_type  # 'negation', 'pivot', 'correction', 'abort'
        self.detected_keywords = detected_keywords
        self.pivot_target = pivot_target
        self.confidence = confidence


class FastPathProcessor:
    """
    Fast Path Engine running on the edge / client side of the dual-loop architecture.
    Operates strictly within a < 150ms latency budget.
    """

    # High-priority interruption & pivot trigger patterns
    INTERRUPT_PATTERNS = [
        (r"\b(wait|hold on|stop|cancel that|forget that|never mind|scratch that)\b", "abort"),
        (r"\b(no no|no wait|actually no|not that)\b", "negation"),
        (r"\b(instead|switch to|make it|change to|change that to|rather than)\b", "pivot"),
        (r"\b(actually|meant to say|correction)\b", "correction"),
    ]

    # Contextual filler templates keyed by intent / pivot category
    FILLER_TEMPLATES: Dict[str, List[str]] = {
        "pivot_train": [
            "Got it, switching to trains.",
            "Understood, checking train options instead.",
            "Switching over to trains for you.",
        ],
        "pivot_flight": [
            "Got it, looking into flights instead.",
            "Switching over to flights.",
        ],
        "pivot_hotel": [
            "Understood, switching to hotel accommodations.",
            "Looking up hotels instead.",
        ],
        "abort": [
            "Stopping that right away.",
            "Cancelled that, what should we do instead?",
            "Hold on, stopped previous request.",
        ],
        "generic_shift": [
            "Got it, changing course.",
            "Understood, updating that right now.",
            "One second, switching gears.",
        ],
        "search_flight": [
            "Looking up flights for you...",
            "Searching available flights now...",
        ],
        "search_train": [
            "Checking available trains...",
            "Searching train schedules right now...",
        ],
        "search_hotel": [
            "Finding hotel listings...",
            "Checking available hotels now...",
        ],
        "generic_search": [
            "Checking that right now...",
            "Looking that up for you...",
        ],
    }

    def __init__(self, energy_threshold: float = 0.05):
        self.energy_threshold = energy_threshold
        self.user_has_floor: bool = False
        self.last_speech_time: float = 0.0
        self.last_filler_time: float = 0.0
        self.filler_cooldown_ms: float = 800.0  # Prevent back-to-back filler spam

    def check_audio_energy(self, clip: AudioClip) -> bool:
        """
        Instant acoustic energy evaluation for voice activity detection (VAD).
        Returns True if voice activity exceeds silence threshold.
        """
        # If precomputed duration and bytes are provided
        if clip.raw_bytes:
            from threadweave.utils import calculate_wav_energy
            rms, _, _ = calculate_wav_energy(audio_bytes=clip.raw_bytes)
            is_active = rms > self.energy_threshold
            if is_active:
                self.user_has_floor = True
                self.last_speech_time = time.time()
            return is_active
        return False

    def detect_intent_shift(self, text: str) -> IntentShiftResult:
        """
        Regex-based ultra-fast (< 5ms) intent shift detection on transcript fragments.
        Detects negations, pivots, and corrections mid-stream.
        """
        normalized = text.lower().strip()
        detected_keywords = []

        # Check for explicit interruption phrases
        for pattern, shift_type in self.INTERRUPT_PATTERNS:
            matches = re.findall(pattern, normalized)
            if matches:
                detected_keywords.extend(matches if isinstance(matches[0], str) else [m[0] for m in matches])
                
                # Check for pivot target (e.g. "train", "flight", "hotel", "delhi", "mumbai")
                pivot_target = None
                if "train" in normalized:
                    pivot_target = "train"
                elif "flight" in normalized or "plane" in normalized:
                    pivot_target = "flight"
                elif "hotel" in normalized:
                    pivot_target = "hotel"

                return IntentShiftResult(
                    is_shift=True,
                    shift_type=shift_type,
                    detected_keywords=detected_keywords,
                    pivot_target=pivot_target,
                    confidence=0.95,
                )

        return IntentShiftResult(
            is_shift=False,
            shift_type="none",
            detected_keywords=[],
            pivot_target=None,
            confidence=0.0,
        )

    def generate_filler(
        self,
        text: str,
        shift_result: Optional[IntentShiftResult] = None,
        speculative_intent: Optional[str] = None,
        destination_hint: Optional[str] = None,
    ) -> Optional[FillerAction]:
        """
        Generate a conversational verbal filler within < 150ms.
        Emits targeted presence fillers without making false task completion claims.
        """
        start_ms = now_ms()
        curr_time = time.time() * 1000.0
        # Rate limit fillers to prevent repetitive chatter, but urgent interruptions MUST bypass cooldown
        is_urgent_interruption = shift_result is not None and shift_result.is_shift
        if not is_urgent_interruption and (curr_time - self.last_filler_time) < self.filler_cooldown_ms:
            return None

        filler_text: Optional[str] = None

        if shift_result and shift_result.is_shift:
            # Context-aware interruption filler
            if shift_result.pivot_target == "train":
                if destination_hint:
                    filler_text = f"Switching to trains for {destination_hint}."
                else:
                    filler_text = "Got it, switching to trains."
            elif shift_result.pivot_target == "flight":
                if destination_hint:
                    filler_text = f"Switching to flights for {destination_hint}."
                else:
                    filler_text = "Got it, switching over to flights."
            elif shift_result.pivot_target == "hotel":
                filler_text = "Understood, switching to hotel accommodations."
            elif shift_result.shift_type == "abort":
                filler_text = "Cancelled that, what should we do instead?"
            else:
                filler_text = "Got it, updating that right now."
        elif speculative_intent:
            if speculative_intent in ("search_flight", "book_flight"):
                filler_text = (
                    f"Looking up flights to {destination_hint}..."
                    if destination_hint else "Looking up flights for you..."
                )
            elif speculative_intent in ("search_train", "book_train"):
                filler_text = (
                    f"Checking trains to {destination_hint}..."
                    if destination_hint else "Checking available trains..."
                )
            elif speculative_intent in ("search_hotel", "book_hotel"):
                filler_text = "Finding hotel listings..."
            else:
                filler_text = "Checking that right now..."

        if not filler_text:
            return None

        latency_ms = now_ms() - start_ms
        self.last_filler_time = curr_time

        logger.info(f"Emitting filler: '{filler_text}' (computed in {latency_ms:.2f}ms)")
        return FillerAction(
            text=filler_text,
            trigger_intent=speculative_intent,
            latency_ms=latency_ms,
            timestamp=time.time(),
        )

    def update_floor(self, event: Any) -> None:
        """Manage conversational floor state based on incoming events."""
        if isinstance(event, TranscriptChunk):
            if not event.is_end_of_turn:
                self.user_has_floor = True
            else:
                self.user_has_floor = False
        elif isinstance(event, InterruptSignal):
            self.user_has_floor = True
