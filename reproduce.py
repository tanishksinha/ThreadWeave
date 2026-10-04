#!/usr/bin/env python3
"""
ThreadWeave — Production FDB-v3 Benchmark Reproduction Suite (Cross-Platform)

Executes end-to-end:
  1. Environment validation (Python, dependencies, API credentials)
  2. Dataset verification & extraction
  3. ThreadWeave LiveKit Agent startup
  4. Benchmark execution (Full-Duplex-Bench v3)
  5. LLM Judge evaluation (Tool Selection F1, Argument Acc, Strict Pass Rate, Latency)
  6. Final results aggregation & display
"""

import os
import sys
import time
import json
import zipfile
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Ensure stdout handles UTF-8 on all platforms
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
BENCH_DIR = PROJECT_ROOT / "Full-Duplex-Bench" / "v3"

# Load credentials from root or v3 .env.local
for env_path in [PROJECT_ROOT / ".env.local", BENCH_DIR / ".env.local", PROJECT_ROOT / ".env"]:
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded credentials from: {env_path}")
        break


def banner(title: str):
    print("\n" + "=" * 75)
    print(f"  {title}")
    print("=" * 75)


def check_prerequisites():
    banner("1. Checking Environment & API Credentials")
    
    # 1. API Keys
    openai_key = os.getenv("OPENAI_API_KEY")
    livekit_url = os.getenv("LIVEKIT_URL")
    livekit_key = os.getenv("LIVEKIT_API_KEY")
    livekit_secret = os.getenv("LIVEKIT_API_SECRET")

    missing = []
    if not openai_key: missing.append("OPENAI_API_KEY")
    if not livekit_url: missing.append("LIVEKIT_URL")
    if not livekit_key: missing.append("LIVEKIT_API_KEY")
    if not livekit_secret: missing.append("LIVEKIT_API_SECRET")

    if missing:
        print("⚠️  MISSING CREDENTIALS:")
        for m in missing:
            print(f"   • {m}")
        print("\nPlease set them in your environment or in a .env.local file:")
        print("   OPENAI_API_KEY=sk-...")
        print("   LIVEKIT_URL=wss://your-project.livekit.cloud")
        print("   LIVEKIT_API_KEY=...")
        print("   LIVEKIT_API_SECRET=...")
        print("\nFree LiveKit Cloud account available at https://cloud.livekit.io")
        return False
    
    print("✅ All required API credentials found.")
    return True


def ensure_dataset():
    banner("2. Verifying Benchmark Dataset")
    target_dir = BENCH_DIR / "fdb_v3_data_released"
    if target_dir.exists() and any(target_dir.iterdir()):
        print(f"✅ Benchmark data ready at: {target_dir}")
        return True

    zip_candidates = [
        BENCH_DIR / "fdb_v3_data.zip",
        PROJECT_ROOT / "fdb_v3_data.zip",
        BENCH_DIR / "fdb_v3_data_released.zip",
    ]
    for z in zip_candidates:
        if z.exists():
            print(f"📦 Extracting {z.name} to {BENCH_DIR}...")
            with zipfile.ZipFile(z, "r") as zip_ref:
                zip_ref.extractall(BENCH_DIR)
            print(f"✅ Extracted benchmark dataset successfully.")
            return True

    print("⚠️  Benchmark dataset folder 'fdb_v3_data_released' not found.")
    print("   Download from Google Drive link in v3/README.md:")
    print("   https://drive.google.com/file/d/1SO_4MTazWQ_jvCx0dtmpQ-t40bdd07yz/view?usp=sharing")
    return False


def run_reproduction():
    banner("ThreadWeave: Official FDB-v3 Reproduction")
    
    if not check_prerequisites():
        print("\nAborting reproduction due to missing API keys.")
        sys.exit(1)

    has_data = ensure_dataset()
    if not has_data:
        print("\nAborting reproduction due to missing benchmark dataset.")
        sys.exit(1)

    # Launch ThreadWeave agent in background
    banner("3. Starting ThreadWeave LiveKit Agent")
    agent_cmd = [sys.executable, str(PROJECT_ROOT / "lk_threadweave_agent.py"), "dev"]
    print(f"Running: {' '.join(agent_cmd)}")
    agent_proc = subprocess.Popen(agent_cmd, cwd=str(PROJECT_ROOT))
    print(f"✅ ThreadWeave Agent launched (PID={agent_proc.pid}). Waiting 8s for WebRTC room connection...")
    time.sleep(8)

    import argparse
    parser = argparse.ArgumentParser(description="ThreadWeave FDB-v3 Reproduction")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N scenarios (e.g. --limit 8 for fast balanced test)")
    parser.add_argument("--force", action="store_true", default=True, help="Force re-evaluation of scenarios")
    args, _ = parser.parse_known_args()

    # Clean up stale results to ensure clean evaluation scores
    target_dir = BENCH_DIR / "fdb_v3_data_released"
    if target_dir.exists():
        cleaned = 0
        for f in target_dir.rglob("result_threadweave.json"):
            try:
                f.unlink()
                cleaned += 1
            except Exception:
                pass
        if cleaned > 0:
            print(f"🧹 Cleaned {cleaned} previous result_threadweave.json files to ensure fresh benchmark evaluation.")

    try:
        # Run inference
        banner("4. Running Batch Benchmark Inference (FDB-v3)")
        infer_cmd = [
            sys.executable,
            str(BENCH_DIR / "run_tool_benchmark_all_released.py"),
            "--provider", "threadweave",
            "--force",
        ]
        if args.limit:
            infer_cmd.extend(["--limit", str(args.limit)])
        print(f"Executing: {' '.join(infer_cmd)}")
        subprocess.run(infer_cmd, cwd=str(BENCH_DIR), check=True)

        # Run LLM-judged evaluation
        banner("5. Running LLM Judge Evaluation")
        eval_cmd = [
            sys.executable,
            str(BENCH_DIR / "evaluate_tool_calls.py"),
            "--benchmark", str(BENCH_DIR / "benchmark_data_v2.json"),
            "--results-dir", str(BENCH_DIR / "fdb_v3_data_released"),
            "--provider", "threadweave",
            "--output", str(PROJECT_ROOT / "threadweave_evaluation_report.json"),
            "--only-completed",
            "--use-llm",
        ]
        print(f"Executing: {' '.join(eval_cmd)}")
        subprocess.run(eval_cmd, cwd=str(BENCH_DIR), check=True)

        # Run Pass-Rate evaluation
        pass_cmd = [
            sys.executable,
            str(BENCH_DIR / "evaluate_pass_rate.py"),
            "--benchmark", str(BENCH_DIR / "benchmark_data_v2.json"),
            "--results-dir", str(BENCH_DIR / "fdb_v3_data_released"),
            "--provider", "threadweave",
            "--output", str(PROJECT_ROOT / "threadweave_pass_rate_report.json"),
            "--only-completed",
            "--use-llm",
        ]
        print(f"Executing: {' '.join(pass_cmd)}")
        subprocess.run(pass_cmd, cwd=str(BENCH_DIR), check=True)

        banner("6. Evaluation Complete — Summary Results")
        report_file = PROJECT_ROOT / "threadweave_evaluation_report.json"
        pass_file = PROJECT_ROOT / "threadweave_pass_rate_report.json"
        if report_file.exists():
            with open(report_file, "r", encoding="utf-8") as f:
                rep = json.load(f)
            bm = rep.get("by_metric", {})
            tt = rep.get("turn_taking", {})
            lat = rep.get("latency", {})
            print(f"   • Turn-Take Rate:        {tt.get('turn_take_rate', 0):.1%}")
            print(f"   • Tool Selection Acc:    {bm.get('tool_selection_acc', 0):.1%}")
            print(f"   • Argument Accuracy:     {bm.get('argument_acc', 0):.1%}")
            if bm.get('response_qual') is not None:
                print(f"   • Response Quality:      {bm.get('response_qual', 0):.1%}")
            if lat.get("avg_response_latency_s") is not None:
                print(f"   • Avg Spoken Latency:    {lat.get('avg_response_latency_s'):.2f}s")
            
            by_dom = rep.get("by_domain", {})
            if by_dom:
                print(f"\n   Domain Breakdown:")
                for dom, metrics in by_dom.items():
                    ts = metrics.get('tool_selection_acc', 0)
                    arg = metrics.get('argument_acc', 0)
                    rq = metrics.get('response_qual', 0)
                    print(f"     • {dom:<18}: Tool Acc={ts:.1%}, Arg Acc={arg:.1%}, Resp Qual={rq:.1%}")

        if pass_file.exists():
            with open(pass_file, "r", encoding="utf-8") as f:
                pass_rep = json.load(f)
            print(f"\n   • Overall Pass Rate:     {pass_rep.get('overall_pass_rate', 0):.1%}")
            print(f"\nDetailed reports saved to:")
            print(f"   - {report_file}")
            print(f"   - {pass_file}")

    finally:
        banner("7. Shutting down ThreadWeave Agent")
        agent_proc.terminate()
        try:
            agent_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            agent_proc.kill()
        print("✅ Background agent terminated cleanly.")


if __name__ == "__main__":
    run_reproduction()
