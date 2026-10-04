"""
threadweave.multimodal
~~~~~~~~~~~~~~~~~~~~~

Multimodal Grounding Pipeline for streaming Audio clips (.wav)
and Video/Camera frames (.png).
Features perceptual frame-diffing (dHash), scene change detection,
and automated tool parameter invalidation upon visual shifts.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from threadweave.models import AudioClip, VideoFrame
from threadweave.utils import (
    calculate_wav_energy,
    compute_dhash,
    hamming_distance,
    setup_logger,
)

logger = setup_logger("threadweave.multimodal")


class SceneChangeEvent:
    """Represents a significant visual shift detected in video stream."""

    def __init__(
        self,
        frame_id: str,
        prev_hash: int,
        curr_hash: int,
        distance: int,
        timestamp: float,
        visual_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.frame_id = frame_id
        self.prev_hash = prev_hash
        self.curr_hash = curr_hash
        self.distance = distance
        self.timestamp = timestamp
        self.visual_metadata = visual_metadata or {}


class MultimodalPipeline:
    """
    Real-time multimodal ingestion and visual grounding engine.
    Detects scene shifts, extracts acoustic features, and produces grounding context.
    """

    def __init__(
        self,
        scene_change_threshold: int = 12,
        energy_threshold: float = 0.05,
    ):
        self.scene_change_threshold = scene_change_threshold
        self.energy_threshold = energy_threshold
        self.last_frame_hash: Optional[int] = None
        self.last_frame_id: Optional[str] = None
        self.frame_history: List[Tuple[str, int, float]] = []
        self.latest_visual_context: Dict[str, Any] = {}

    def process_audio(self, clip: AudioClip) -> Dict[str, Any]:
        """
        Process incoming .wav audio clip.
        Computes RMS energy, duration, and voice activity indicator.
        """
        rms, duration_ms, sample_rate = calculate_wav_energy(
            audio_bytes=clip.raw_bytes,
            audio_path=clip.audio_path,
        )
        is_speech = rms > self.energy_threshold
        logger.debug(
            f"AudioClip processed: RMS={rms:.4f}, duration={duration_ms:.1f}ms, "
            f"is_speech={is_speech}"
        )
        return {
            "rms_energy": rms,
            "duration_ms": duration_ms,
            "sample_rate": sample_rate,
            "is_speech": is_speech,
            "timestamp": clip.timestamp,
        }

    def process_frame(self, frame: VideoFrame) -> Optional[SceneChangeEvent]:
        """
        Ingest a video/camera frame (.png) and evaluate visual stability.
        If perceptual visual difference exceeds threshold, emits SceneChangeEvent.
        """
        curr_hash = compute_dhash(
            image_bytes=frame.image_bytes,
            image_path=frame.image_path,
        )
        curr_time = frame.timestamp or time.time()

        scene_change: Optional[SceneChangeEvent] = None

        if self.last_frame_hash is not None:
            dist = hamming_distance(self.last_frame_hash, curr_hash)
            logger.debug(
                f"Frame {frame.frame_id} evaluated: dHash={curr_hash:x}, "
                f"Hamming distance from prev={dist} (threshold={self.scene_change_threshold})"
            )

            if dist >= self.scene_change_threshold:
                logger.warning(
                    f"Scene change detected! Frame {frame.frame_id} diff={dist} "
                    f">= {self.scene_change_threshold}"
                )
                scene_change = SceneChangeEvent(
                    frame_id=frame.frame_id,
                    prev_hash=self.last_frame_hash,
                    curr_hash=curr_hash,
                    distance=dist,
                    timestamp=curr_time,
                )

        self.last_frame_hash = curr_hash
        self.last_frame_id = frame.frame_id
        self.frame_history.append((frame.frame_id, curr_hash, curr_time))

        return scene_change

    def ground_visual_slots(
        self,
        frame_text_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract groundable context from the latest camera frame.
        Simulates on-device visual grounding (e.g. boarding pass, device screen).
        """
        slots: Dict[str, Any] = {}
        if frame_text_hint:
            lower = frame_text_hint.lower()
            if "gate" in lower or "terminal" in lower:
                slots["visual_location"] = frame_text_hint
            if "delhi" in lower:
                slots["visual_destination"] = "Delhi"
            elif "mumbai" in lower:
                slots["visual_destination"] = "Mumbai"
        return slots
