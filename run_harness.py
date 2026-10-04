"""
run_harness.py
~~~~~~~~~~~~~~

Command-line entry point to execute ThreadWeave against the Virtual Clock
streaming test kit.
Generates comprehensive trace logs and prints quantitative evaluation scorecards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from threadweave.coordinator import ThreadWeaveCoordinator
from harness_adapter import VirtualClockHarness


def print_banner() -> None:
    print("=" * 80)
    print("   THREADWEAVE: FULL-DUPLEX INTERRUPTIBLE REAL-TIME AGENT HARNESS")
    print("   Enterprise Full-Duplex Conversational AI Evaluation Engine")
    print("=" * 80)


def print_scorecard(eval_res: Dict[str, Any]) -> None:
    """Print beautifully formatted evaluation rubric breakdown."""
    raw = eval_res["raw_scores"]
    mult = eval_res["multipliers"]
    trace = eval_res["trace_summary"]

    print("\n" + "-" * 80)
    print(f"SCENARIO: {eval_res['scenario']}")
    print("-" * 80)

    print("\n[QUANTITATIVE EVALUATION RUBRIC]")
    print(f"  1. Task Completion (40% max):            {raw['task_completion']:>6.1f} / 40.0 pts")
    print(f"  2. Interruption Recovery (35% max):       {raw['interruption_recovery']:>6.1f} / 35.0 pts")
    print(f"  3. Response Latency (<150-200ms) (15%):   {raw['response_latency']:>6.1f} / 15.0 pts")
    print(f"  4. Safety & Protocol Adherence (10% max): {raw['safety_protocol']:>6.1f} / 10.0 pts")
    print(f"  -------------------------------------------------------------")
    print(f"  Raw Subtotal:                            {raw['raw_total']:>6.1f} / 100.0 pts")
    print(f"  Quality Multiplier:                      x{mult['quality']:.2f}")
    print(f"  Multimodal Multiplier:                   x{mult['multimodal']:.2f}")
    print(f"  =============================================================")
    print(f"  FINAL WEIGHTED SCORE:                    {eval_res['final_score']:>6.2f} / 100.00")
    print(f"  =============================================================\n")

    print("[OBSERVED OUTPUT ACTIONS TRACE SUMMARY]")
    print(f"  - Spoken Conversational Fillers: {trace['fillers']}")
    print(f"  - Non-Blocking Tool Calls:       {trace['tool_calls']}")
    print(f"  - In-Flight Tool Cancellations:  {trace['cancellations']}")
    print(f"  - Compensating Rollbacks:        {trace['rollbacks']}")
    print(f"  - Grounded Final Responses:      {trace['final_responses']}")
    print(f"  - Total Output Events:           {trace['total_actions']}")

    print("\n[DETAILED ACTION TRACE]")
    for idx, act in enumerate(eval_res.get("output_trace", []), 1):
        atype = act["action_type"]
        payload = act["payload"]
        if atype == "filler":
            print(f"  [{idx:02d}] FILLER         -> \"{payload.get('text')}\" (latency: {payload.get('latency_ms', 0):.1f}ms)")
        elif atype == "tool_call":
            spec = "[SPECULATIVE]" if payload.get("is_speculative") else "[CONFIRMED]"
            print(f"  [{idx:02d}] TOOL_CALL      -> {payload.get('tool_name')} ({payload.get('call_id')}) {spec} args={payload.get('arguments')}")
        elif atype == "tool_cancel":
            print(f"  [{idx:02d}] TOOL_CANCEL    -> {payload.get('call_id')} (reason: {payload.get('reason')})")
        elif atype == "rollback":
            print(f"  [{idx:02d}] ROLLBACK       -> {payload.get('rollback_tool_name')} for orig_id={payload.get('original_call_id')}")
        elif atype == "final_response":
            snap = payload.get("state_snapshot", {})
            print(f"  [{idx:02d}] FINAL_RESPONSE -> \"{payload.get('text')}\"")
            print(f"       State Snapshot: intent='{snap.get('intent')}', slots={snap.get('slot_values')}, v{snap.get('version')}")
    print("-" * 80 + "\n")


async def run_scenario_file(filepath: Path) -> Dict[str, Any]:
    """Load and execute single scenario JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    harness = VirtualClockHarness(scenario_data)
    result = await harness.run(ThreadWeaveCoordinator)
    return result


async def main_async() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="ThreadWeave Harness Runner")
    parser.add_argument(
        "--scenario",
        type=str,
        default="scenarios/scenario_interruption_flight_to_train.json",
        help="Path to specific scenario JSON file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all available scenarios in scenarios/ directory",
    )
    args = parser.parse_args()

    print_banner()

    scenarios_dir = Path(__file__).parent / "scenarios"
    if args.all:
        scenario_files = sorted(list(scenarios_dir.glob("*.json")))
    else:
        scenario_path = Path(args.scenario)
        if not scenario_path.is_absolute():
            scenario_path = Path(__file__).parent / scenario_path
        scenario_files = [scenario_path]

    if not scenario_files:
        print("No scenario files found to execute!")
        return 1

    total_scenarios = len(scenario_files)
    scores = []

    for s_file in scenario_files:
        print(f"\nExecuting: {s_file.name} ...")
        res = await run_scenario_file(s_file)
        print_scorecard(res)
        scores.append(res["final_score"])

    avg_score = sum(scores) / len(scores) if scores else 0.0
    print("=" * 80)
    print(f"ALL SCENARIOS COMPLETED ({total_scenarios}/{total_scenarios})")
    print(f"AVERAGE COMPOSITE SCORE: {avg_score:.2f} / 100.00")
    print("=" * 80)

    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
