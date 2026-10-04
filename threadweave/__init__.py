"""
ThreadWeave: Full-Duplex Interruptible Real-Time Agent Architecture.

Production-grade real-time voice intelligence platform.
Features:
  - Dual-loop concurrency (Fast Path < 150ms + Slow Path multi-step execution)
  - Cooperative cancellation token protocol with sub-millisecond grace periods
  - Speculative tool execution & safe state-modifying locks
  - Compensating transaction rollbacks with idempotency keys
  - Localized slot correction & session-scoped state snapshot engine
  - Multimodal frame-diffing & acoustic energy ingestion pipeline
"""

__version__ = "0.1.0"
