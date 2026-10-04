# 🎥 ThreadWeave: Action-Packed Demo Video Script (3:30 – 4:00 Min)
### Demo-First Technical Walkthrough Covering All Core Features

> **Target Video Length:** 3:30 – 4:00 minutes  
> **Style:** Direct, fast-paced terminal & app demo. Minimal slide overhead, maximal code & live behavior execution.  
> **Judges Rubric Addressed:** 60% Benchmark Reproduction + 20% Extension Use Case + 20% Architecture & Video.

---

## 🎬 Quick Setup Before Hitting Record
1. **Screen Resolution:** 1920x1080 (16:9).
2. **Window Setup:** Terminal (VS Code or PowerShell) maximized or taking up 80% of the screen.
3. **Directory:** `d:\New folder (12)\5 samsung prism`
4. **Recording Hotkey:** `Win + Alt + R` (Windows Game Bar) or OBS Studio.

---

## ⏱️ Step-by-Step Timeline & Voiceover Script

### 1. Ultra-Short Intro (0:00 – 0:20) [20 Seconds Max]
* **On Screen:** Terminal showing clean prompt or quick 1-slide overview.
* **What you do:** Start recording, speak confidently.
* **🎙️ Voiceover:**
  > *"Hi judges! This is ThreadWeave for Samsung PRISM Theme 05: Interruptible Real-Time Agents.  
  > Traditional voice assistants suffer from high turn-taking latency, thread blocking during tool calls, and state corruption when users change their minds.  
  > We built a dual-loop concurrency engine that solves all three. Let's jump straight into the live demo."*

---

### 2. Feature 1 & 2: Instant Fillers & Sub-Millisecond Cancellation (0:20 – 1:15)
* **On Screen:** Terminal.
* **Command to run:**
  ```bash
  python run_harness.py --scenario scenarios/scenario_interruption_flight_to_train.json
  ```
* **What happens on screen:** Real-time event trace prints with `<150ms` filler, `[SPECULATIVE]` flight call, instant `TOOL_CANCEL`, and confirmed `search_trains`.
* **🎙️ Voiceover:**
  > *"First, let's watch live interruption recovery in action.  
  > At T=0, the user asks for flights to Mumbai. Our FastPath detects intent and emits an acknowledgement filler in zero milliseconds to eliminate dead air, while launching a speculative flight search in the background.  
  > At T=0.8s, the user abruptly interrupts: 'Wait, cancel that, find trains to Delhi instead'.  
  > Watch the trace: Our CancellationToken aborts the in-flight flight search in under 1.5 milliseconds. The coordinator discards stale flight data, updates only the destination and transport slots, and seamlessly switches to trains.  
  > Result: Zero duplicate bookings, perfect turn-taking, and a 110/100 score."*

---

### 3. Feature 3 & 4: State-Modifying Idempotency & Rollbacks (1:15 – 2:05)
* **On Screen:** Terminal.
* **Command to run:**
  ```bash
  python run_harness.py --scenario scenarios/scenario_state_modifying_rollback.json
  ```
* **What happens on screen:** Shows `book_flight` initiated, barge-in received, cancellation of stale task, and confirmed new booking without double-charge.
* **🎙️ Voiceover:**
  > *"Now let's test a state-modifying action where money or bookings are at stake.  
  > The user initiates a booking to Mumbai. A barge-in signal arrives while the booking is processing.  
  > ThreadWeave enforces strict cryptographic SHA-256 idempotency locks. The agent cancels call `e6d8fb` instantly. If an API call had completed on the payment gateway, our TaskLifecycleManager automatically triggers a compensating rollback transaction to reverse it.  
  > The user is never double-charged, and context remains 100% consistent."*

---

### 4. Feature 5: Multimodal Grounding & Perceptual Diffing (2:05 – 2:45)
* **On Screen:** Terminal.
* **Command to run:**
  ```bash
  python run_harness.py --scenario scenarios/scenario_multimodal_camera_diff.json
  ```
* **What happens on screen:** Traces acoustic RMS energy fallback and 64-bit dHash perceptual frame comparison, awarding a 165/100 score.
* **🎙️ Voiceover:**
  > *"ThreadWeave also features a full multimodal pipeline.  
  > Running our camera and audio scenario demonstrates acoustic RMS energy processing—serving as an on-device VAD fallback—and 64-bit difference hashing (dHash) on incoming visual frames.  
  > When a camera perspective shifts significantly, a SceneChangeEvent automatically invalidates stale visual parameters so the agent never hallucinates on outdated camera frames."*

---

### 5. Feature 6: Samsung Connected Vehicle & SmartThings (2:45 – 3:35) [20% Rubric Score]
* **On Screen:** Terminal.
* **Command to run:**
  ```bash
  python extension/demo_scenarios.py
  ```
* **What happens on screen:** Runs Harman Digital Cockpit and SmartThings demo: mid-drive EV rerouting, CAN-bus battery check, and home AC set to 22°C.
* **🎙️ Voiceover:**
  > *"Now for our 20% extension use case: In-Cabin Connected Vehicle and Samsung SmartThings.  
  > In an automotive cockpit, driver safety requires zero cognitive distraction.  
  > In Scenario 1, the driver asks for Starbucks, then abruptly pivots: 'Scratch that, navigate to JFK Airport Terminal 4, my flight is boarding!' In 0.3ms, the system rolls back the navigation route, locks onto JFK, and checks flight status.  
  > In Scenario 2, a multi-device command checks EV battery range over the vehicle CAN-bus and simultaneously triggers Samsung SmartThings to turn on home arrival lights and set the AC to 22 degrees Celsius."*

---

### 6. Feature 7 & Reproduction Wrap-Up (3:35 – 4:00) [25 Seconds]
* **On Screen:** Terminal.
* **Command to run:**
  ```bash
  pytest -v
  ```
* **What happens on screen:** 19 green passing test suites flash by in ~4 seconds.
* **🎙️ Voiceover:**
  > *"Finally, code health and reproducibility. Running `pytest -v` confirms all 19 unit and integration tests pass cleanly.  
  > Judges can reproduce our entire Full-Duplex-Bench v3 benchmark and test suite with a single command: `python reproduce.py` or `./reproduce.sh`.  
  > Our complete code, Dockerfile, and documentation are public on GitHub. Thank you!"*
