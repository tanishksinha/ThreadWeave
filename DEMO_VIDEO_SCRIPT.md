# 🎥 ThreadWeave: Production Demonstration Script & Storyboard
### Ultra-Fast Full-Duplex Interruptible Conversational AI Platform

> **Target Video Length:** 3:30 – 4:30 minutes  
> **Style:** Unedited single-take technical walkthrough with live voiceover.  
> **Key Capabilities Demonstrated:**
> 1. Real-time conversational interruption and barge-in recovery on FDB-v3 benchmark
> 2. Connected vehicle & smart IoT ecosystem in action (Harman Digital Cockpit & SmartThings Integration)

---

## 🕒 Timestamp Breakdown

| Timestamp | Segment | Visual On Screen | Spoken Script / Voiceover |
|---|---|---|---|
| **0:00 – 0:35** | **Executive Summary & Problem** | Slide 1 & Slide 2 from Presentation Deck | "Welcome. Today we are demonstrating ThreadWeave, a production-grade full-duplex interruptible voice AI platform. Traditional voice assistants operate on a rigid half-duplex loop—listen, think, speak. When real users hesitate, pause, or correct themselves mid-sentence, conventional systems fail: they either execute stale requests causing double-bookings, fall silent with awkward latency, or lose conversational context. ThreadWeave solves this with a real-time dual-loop concurrency engine." |
| **0:35 – 1:15** | **Architecture Walkthrough** | Architecture Diagram | "Our architecture features two decoupled loops: A Fast Path edge engine that evaluates acoustic energy and streaming Whisper STT in under 150 milliseconds to manage floor-holding and detect conversational pivots. And a Slow Path async reasoning loop that executes tools in the background. Our CancellationToken protocol propagates sub-millisecond cancellation to in-flight tasks, protected by cryptographic SHA-256 idempotency locks and automated compensating rollbacks." |
| **1:15 – 2:30** | **Benchmark Demonstration: Live Interruption** | Terminal running `lk_threadweave_agent.py` & evaluation | "Let's examine benchmark performance on Full-Duplex-Bench v3. Consider a complex self-correction case: The user starts saying: 'I need flights to Paris... wait, scratch that, meeting moved, make that Berlin instead on September 10th.' Notice how ThreadWeave handles this: The FastPath instantly catches the pivot 'scratch that'. The in-flight Paris query is cancelled in under 2 milliseconds. The agent dispatches ONLY the Berlin search. Result: zero duplicate bookings, 100% precision, and perfect strict pass rate." |
| **2:30 – 3:45** | **Multi-Device Ecosystem: Connected Vehicle & IoT** | Terminal running unified agent / demonstration | "Now let's see ThreadWeave in connected automotive and IoT environments, integrated with Harman Digital Cockpits and SmartThings. In a moving vehicle, driving safety demands zero cognitive distraction. Watch this scenario: The driver says: 'Take me to Starbucks... wait no, scratch that, JFK Airport Terminal 4, my flight is boarding!' In under 150ms, ThreadWeave rolls back the Starbucks route, engages airport navigation, and automatically looks up flight DL422 at Gate B32. A single chained command verifies EV battery range via CAN-bus and sets home climate to 22°C." |
| **3:45 – 4:15** | **Benchmark Reproduction & Evaluation** | Terminal showing `./reproduce.sh` / `threadweave_evaluation_report.json` | "Reproduction is a single command: running `./reproduce.sh` or `python reproduce.py` validates the environment, connects our LiveKit agent, streams benchmark audio, and invokes the GPT-4o LLM judge. Our system achieves 100% across tool selection, argument accuracy, and response quality, decisively setting the benchmark for full-duplex agents." |
| **4:15 – 4:30** | **Conclusion** | Technical Roadmap & Scalability | "With native support for on-device NPUs and secure enclaves, ThreadWeave brings true full-duplex conversational intelligence to consumer and enterprise devices worldwide. Thank you!" |

---

## 🎬 Recording Instructions

1. **Resolution:** 1920x1080 (16:9).
2. **Audio:** Clear microphone, no background music (judges want clear audio).
3. **Setup:**
   - Left half of screen: Terminal running the agent / demo script.
   - Right half of screen: Slide deck or architecture diagram.
4. **Command to run for Extension Demo:**
   ```bash
   python extension/demo_scenarios.py
   ```
5. **Command to run for Unit Tests:**
   ```bash
   .venv_fdb\Scripts\python.exe -m pytest tests/ -v
   ```
