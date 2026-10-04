"""
tests.test_multimodal
~~~~~~~~~~~~~~~~~~~~~

Unit tests for Multimodal Ingestion Pipeline:
WAV audio processing and PNG frame perceptual difference hashing (dHash).
"""

from threadweave.models import AudioClip, VideoFrame
from threadweave.multimodal import MultimodalPipeline
from threadweave.utils import (
    calculate_wav_energy,
    compute_dhash,
    create_synthetic_png,
    create_synthetic_wav,
    hamming_distance,
)


def test_wav_energy_calculation():
    """Verify acoustic energy calculation on synthetic audio."""
    wav_bytes = create_synthetic_wav(duration_ms=500.0, frequency_hz=440.0, amplitude=0.5)
    rms, duration, rate = calculate_wav_energy(audio_bytes=wav_bytes)

    assert rms > 0.2
    assert 480.0 <= duration <= 520.0
    assert rate == 16000


def test_dhash_and_scene_change_detection():
    """Verify perceptual hashing detects visual scene transitions."""
    pipeline = MultimodalPipeline(scene_change_threshold=10)

    from PIL import Image
    import io

    # Frame 1: Vertical stripe pattern A
    im1 = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            im1.putpixel((x, y), 255 if (x % 4 < 2) else 0)
    b1 = io.BytesIO()
    im1.save(b1, format="PNG")
    frame1 = VideoFrame(frame_id="frame_01", image_bytes=b1.getvalue())
    change1 = pipeline.process_frame(frame1)
    assert change1 is None  # Initial frame has no predecessor

    # Frame 2: Identical pattern A (no scene change)
    frame2 = VideoFrame(frame_id="frame_02", image_bytes=b1.getvalue())
    change2 = pipeline.process_frame(frame2)
    assert change2 is None

    # Frame 3: Inverted vertical stripe pattern B (drastic scene change!)
    im3 = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            im3.putpixel((x, y), 0 if (x % 4 < 2) else 255)
    b3 = io.BytesIO()
    im3.save(b3, format="PNG")
    frame3 = VideoFrame(frame_id="frame_03", image_bytes=b3.getvalue())

    change3 = pipeline.process_frame(frame3)
    assert change3 is not None
    assert change3.distance >= 10
    assert change3.frame_id == "frame_03"
