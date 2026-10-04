"""
threadweave.utils
~~~~~~~~~~~~~~~~

High-resolution timing, structured logging, acoustic energy computation,
and visual difference hashing utilities.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import time
import wave
from typing import Any, Dict, Optional, Tuple
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# High-Resolution Time Helpers
# ---------------------------------------------------------------------------

def now_ms() -> float:
    """Return high-resolution current time in milliseconds."""
    return time.perf_counter() * 1000.0


def format_delta_ms(start_time: float) -> float:
    """Compute elapsed milliseconds since start_time (seconds or ms)."""
    return round((time.time() - start_time) * 1000.0, 2)


# ---------------------------------------------------------------------------
# Structured Logger
# ---------------------------------------------------------------------------

def setup_logger(name: str = "threadweave", level: int = logging.INFO) -> logging.Logger:
    """Configure a clean, high-precision console logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# ---------------------------------------------------------------------------
# Audio Processing Utilities (Acoustic Energy & VAD)
# ---------------------------------------------------------------------------

def calculate_wav_energy(
    audio_bytes: Optional[bytes] = None,
    audio_path: Optional[str] = None,
) -> Tuple[float, float, int]:
    """
    Compute RMS energy, duration, and sample rate of a WAV clip.

    Returns:
        Tuple of (rms_energy, duration_ms, sample_rate)
    """
    try:
        if audio_bytes is not None:
            wav_file = wave.open(io.BytesIO(audio_bytes), "rb")
        elif audio_path is not None:
            wav_file = wave.open(audio_path, "rb")
        else:
            return 0.0, 0.0, 16000

        with wav_file as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            duration_ms = (n_frames / framerate) * 1000.0

            raw_data = wf.readframes(n_frames)
            if not raw_data:
                return 0.0, duration_ms, framerate

            # Handle 16-bit PCM (standard streaming audio benchmark format)
            if sample_width == 2:
                fmt = f"<{n_frames * n_channels}h"
                samples = struct.unpack(fmt, raw_data)
                arr = np.array(samples, dtype=np.float32) / 32768.0
            elif sample_width == 1:
                # 8-bit unsigned
                samples = struct.unpack(f"<{n_frames * n_channels}B", raw_data)
                arr = (np.array(samples, dtype=np.float32) - 128.0) / 128.0
            else:
                arr = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

            rms = float(np.sqrt(np.mean(arr ** 2))) if len(arr) > 0 else 0.0
            return rms, duration_ms, framerate

    except Exception:
        return 0.0, 0.0, 16000


def create_synthetic_wav(
    duration_ms: float = 500.0,
    frequency_hz: float = 440.0,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a clean synthetic WAV clip in-memory for testing."""
    n_samples = int((duration_ms / 1000.0) * sample_rate)
    t = np.linspace(0, duration_ms / 1000.0, n_samples, False)
    waveform = amplitude * np.sin(2 * np.pi * frequency_hz * t)
    pcm16 = (waveform * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Visual Difference Hashing (dHash) & Scene Change Detection
# ---------------------------------------------------------------------------

def compute_dhash(
    image_bytes: Optional[bytes] = None,
    image_path: Optional[str] = None,
    hash_size: int = 8,
) -> int:
    """
    Compute Difference Hash (dHash) of an image.
    Efficient, scale-invariant, perceptual visual signature.

    Returns:
        64-bit integer hash.
    """
    try:
        if image_bytes is not None:
            image = Image.open(io.BytesIO(image_bytes))
        elif image_path is not None:
            image = Image.open(image_path)
        else:
            return 0

        # Resize to (hash_size + 1, hash_size) in grayscale
        image = image.convert("L").resize(
            (hash_size + 1, hash_size),
            Image.Resampling.LANCZOS,
        )
        if hasattr(image, "get_flattened_data"):
            pixels = list(image.get_flattened_data())
        else:
            pixels = list(image.getdata())

        diff = []
        for row in range(hash_size):
            for col in range(hash_size):
                pixel_left = pixels[row * (hash_size + 1) + col]
                pixel_right = pixels[row * (hash_size + 1) + col + 1]
                diff.append(pixel_left > pixel_right)

        # Convert boolean list to 64-bit integer
        decimal_val = 0
        for index, value in enumerate(diff):
            if value:
                decimal_val += 1 << index
        return decimal_val

    except Exception:
        return 0


def hamming_distance(hash1: int, hash2: int) -> int:
    """Compute Hamming distance between two 64-bit hashes."""
    x = hash1 ^ hash2
    distance = 0
    while x > 0:
        distance += 1
        x &= x - 1
    return distance


def create_synthetic_png(
    color: Tuple[int, int, int] = (255, 0, 0),
    size: Tuple[int, int] = (64, 64),
    label: str = "",
) -> bytes:
    """Generate a clean synthetic PNG image in-memory for testing."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
