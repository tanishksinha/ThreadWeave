"""
tests.test_fast_path
~~~~~~~~~~~~~~~~~~~~

Unit tests for Fast Path Engine: intent shift detection,
sub-150ms verbal filler latency, and audio energy evaluation.
"""

import time
from threadweave.fast_path import FastPathProcessor
from threadweave.models import AudioClip
from threadweave.utils import create_synthetic_wav


def test_intent_shift_detection():
    """Verify rapid classification of negations, pivots, and aborts."""
    processor = FastPathProcessor()

    # Negation + Pivot
    res1 = processor.detect_intent_shift("wait, cancel that, find trains to Delhi instead")
    assert res1.is_shift
    assert res1.shift_type in ("abort", "pivot")
    assert res1.pivot_target == "train"

    # Abort
    res2 = processor.detect_intent_shift("stop hold on never mind")
    assert res2.is_shift
    assert res2.shift_type == "abort"

    # Normal input (no shift)
    res3 = processor.detect_intent_shift("I want to book a ticket to Mumbai please")
    assert not res3.is_shift


def test_filler_generation_latency():
    """Verify filler generation strictly executes within < 150ms budget."""
    processor = FastPathProcessor()

    shift_res = processor.detect_intent_shift("wait make it trains instead")

    t0 = time.perf_counter()
    filler = processor.generate_filler(
        text="wait make it trains instead",
        shift_result=shift_res,
        destination_hint="Delhi",
    )
    t_elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert filler is not None
    assert "train" in filler.text.lower()
    assert t_elapsed_ms < 150.0  # Non-negotiable latency constraint!


def test_audio_energy_evaluation():
    """Verify acoustic energy thresholding for VAD."""
    processor = FastPathProcessor(energy_threshold=0.05)

    # Active synthetic audio
    speech_wav = create_synthetic_wav(duration_ms=400, amplitude=0.4)
    clip_active = AudioClip(raw_bytes=speech_wav)
    assert processor.check_audio_energy(clip_active) is True
    assert processor.user_has_floor is True

    # Silent synthetic audio
    silent_wav = create_synthetic_wav(duration_ms=400, amplitude=0.0)
    clip_silent = AudioClip(raw_bytes=silent_wav)
    processor.user_has_floor = False
    assert processor.check_audio_energy(clip_silent) is False
