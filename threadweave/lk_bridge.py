"""
ThreadWeave LiveKit Bridge

Connects the LiveKit Agents Framework to the ThreadWeave Full-Duplex Architecture:
1. FastPath Disfluency & Intent-Shift Interception:
   - Detects self-corrections ("actually", "wait no", "scratch that", "instead")
   - Automatically triggers CancellationToken cancellation for any in-flight speculative calls
2. Dual-Loop Coordination:
   - Fast Path: Instant intent-shift classification and disfluency filtering
   - Slow Path: Asynchronous tool execution with speculative execution and dynamic reference resolution
3. Idempotency & Clean Recovery:
   - Prevents stale or duplicate state-modifying tool calls
"""

import re
import time
import logging
from typing import Optional, Tuple, Dict, Any, List

from threadweave.cancellation import CancellationTokenSource, CancellationToken
from threadweave.fast_path import FastPathProcessor, IntentShiftResult
from threadweave.tool_registry import AssistantFnc, LatencyTracker

# Common pivot phrases in human speech indicating self-correction
PIVOT_PATTERNS = [
    r"\bactually\b",
    r"\bwait\b",
    r"\bno wait\b",
    r"\bscratch that\b",
    r"\bnever mind\b",
    r"\binstead\b",
    r"\bi meant\b",
    r"\bmake that\b",
    r"\bchange that to\b",
    r"\bnot\s+([a-zA-Z0-9]+)\b",
]

PIVOT_REGEX = re.compile("|".join(PIVOT_PATTERNS), re.IGNORECASE)


class FastPathTranscriptFilter:
    """
    Real-time transcript filter that catches self-corrections and false starts
    before or as they reach the reasoning layer.
    """
    def __init__(self):
        self.fast_path = FastPathProcessor()
        self.current_cts: Optional[CancellationTokenSource] = None

    def new_turn(self) -> CancellationToken:
        """Starts a new user turn and returns the associated cancellation token."""
        if self.current_cts and not self.current_cts.is_cancelled():
            self.current_cts.cancel("new_turn_started")
        self.current_cts = CancellationTokenSource()
        return self.current_cts.token

    def inspect_transcript(self, transcript: str) -> Tuple[bool, str, Optional[str]]:
        """
        Inspects incoming transcript chunk.
        Returns:
            (has_self_correction: bool, clean_text: str, pivot_detected: Optional[str])
        """
        match = PIVOT_REGEX.search(transcript)
        if match:
            pivot = match.group(0)
            logging.info(f"⚡ FastPath Intent Shift / Self-Correction detected: '{pivot}' in '{transcript}'")
            # If an in-flight tool call was triggered on earlier partial speech, cancel it
            if self.current_cts and not self.current_cts.is_cancelled():
                self.current_cts.cancel(f"self_correction:{pivot}")
                # Spawn a fresh token for the corrected clause
                self.current_cts = CancellationTokenSource()
            return True, transcript, pivot
        return False, transcript, None


class ThreadWeaveSessionBridge:
    """
    Bridge connecting a LiveKit AgentSession to the ThreadWeave runtime.
    """
    def __init__(self, room_name: str, tracker: LatencyTracker):
        self.room_name = room_name
        self.tracker = tracker
        self.fnc = AssistantFnc(tracker, room_name)
        self.filter = FastPathTranscriptFilter()
        self.last_transcript = ""

    def on_transcript(self, transcript: str, is_final: bool) -> CancellationToken:
        token = self.filter.new_turn() if not self.last_transcript else (self.filter.current_cts.token if self.filter.current_cts else self.filter.new_turn())
        has_correction, clean_text, pivot = self.filter.inspect_transcript(transcript)
        self.last_transcript = transcript
        return token
