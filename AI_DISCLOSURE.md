# AI Usage Disclosure Form

### 1. Team Details
- **Team Name:** Chromastone
- **Project / Product Name:** ThreadWeave
- **Organization / Institution (if any):** MSRIT (Ramaiah Institute of Technology)
- **Submission Date:** 4th October 2026

---

### 2. AI Usage Declaration
- **Did your team use any Artificial Intelligence (AI) in developing this project?** Yes

---

### 3. Purpose of AI Usage (Brief Details)
- **Idea generation / brainstorming:** Yes
- **Code generation or assistance:** Yes
- **UI / UX design:** Yes
- **Content creation:** Yes
- **Data analysis:** No
- **Testing / debugging:** Yes
- **Other:** Runtime conversational reasoning & evaluation benchmark (GPT-4o, Silero VAD, Whisper STT)

---

### 4. Feature Origin Classification

#### Feature 1: Dual-Loop Concurrency Engine (Fast Path & Slow Path)
- **Classification:** Both (Self-Generated & AI-Assisted)
- **Description:**
  - *AI tools/platforms Used:* Antigravity AI Assistant / LLM Pair Programmer
  - *Prompt Used:* "Help design an async event-loop coordinator in Python using asyncio.Queue that decouples spoken conversational fillers (<150ms) from heavy background tool execution."
  - *Output Summary:* Provided a foundational skeleton with dual queues and an event loop router.
  - *Modification:* We heavily adapted and customized the logic in `threadweave/coordinator.py`, implementing strict state versioning, task cancellation grace periods, and prioritized stream routing.

#### Feature 2: Cooperative CancellationToken Protocol & Compensating Rollbacks
- **Classification:** Both (Self-Generated & AI-Assisted)
- **Description:**
  - *AI tools/platforms Used:* Antigravity AI Assistant
  - *Prompt Used:* "Implement a cooperative CancellationToken and TaskLifecycleManager to handle sub-millisecond barge-in aborts and trigger compensating rollback transactions for state-modifying actions."
  - *Output Summary:* Basic cancellation token pattern and transaction rollback dictionary structure.
  - *Modification:* Architected and verified sub-1.5ms abort latency in `threadweave/cancellation.py`, integrated SHA-256 cryptographic idempotency hashing to block duplicate transactions, and tied it into our test harness.

#### Feature 3: LiveKit Voice Agent Bridge & Unified 18-Tool Registry
- **Classification:** Both (Self-Generated & AI-Assisted)
- **Description:**
  - *AI tools/platforms Used:* LiveKit Documentation Assistant / LLM Assistant
  - *Prompt Used:* "Create an async LiveKit Agent wrapper bridging Silero VAD, Whisper STT, and GPT-4o with custom tool function schemas."
  - *Output Summary:* Boilerplate LiveKit Agent class with basic tool decorators.
  - *Modification:* Wrote custom transcript interception hooks (`lk_bridge.py`), normalized alphanumeric and passport inputs to address benchmark quirks, and unified 18 tools spanning E-commerce, Banking, Travel, and IoT.

#### Feature 4: Connected Vehicle & Samsung SmartThings Multi-Device Extension
- **Classification:** Self-Generated
- **Description:**
  - *AI tools/platforms Used:* None (Designed manually)
  - *Prompt Used:* N/A
  - *Output Summary:* Conceived and authored `extension/in_car_agent.py` and `mock_car_apis.py`.
  - *Modification:* Fully conceptualized and implemented the 3 automotive scenarios: dynamic in-cabin destination rerouting, CAN-bus vehicle telemetry checks, and automated SmartThings home arrival climate control.

#### Feature 5: Multimodal Acoustic & Perceptual Diffing Pipeline
- **Classification:** Both (Self-Generated & AI-Assisted)
- **Description:**
  - *AI tools/platforms Used:* LLM Coding Assistant
  - *Prompt Used:* "Provide efficient algorithms in Python for calculating audio RMS energy and 64-bit difference hashing (dHash) for images."
  - *Output Summary:* Python functions for calculating NumPy RMS audio energy and PIL-based dHash.
  - *Modification:* Tailored the pipeline to act as an on-device VAD fallback and tied visual Hamming distance thresholds (≥12) to automatic conversational scene-reset events.

---

### 5. Ethical & Compliance Confirmation
- AI usage complies with guidelines and policies: **Yes**
- No proprietary or copyrighted data misused: **I Agree**

---

### 6. Declaration & Sign-Off
- **Name of Team Representative:** Tanishk Sinha
- **Role:** Team Lead
- **Signature:** Tanishk Sinha
- **Date:** 4th October 2026
