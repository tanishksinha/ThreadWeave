"""
tests.test_coordinator
~~~~~~~~~~~~~~~~~~~~~~

Integration tests for ThreadWeaveCoordinator:
Testing the dual asynchronous queues, speculative execution,
interruption cancellation, and state snapshot consistency.
"""

import asyncio
import pytest
from threadweave.coordinator import ThreadWeaveCoordinator
from threadweave.models import (
    ActionType,
    FillerAction,
    FinalResponse,
    ToolCallAction,
    ToolCancelAction,
    ToolManifest,
    ToolResult,
    TranscriptChunk,
)


@pytest.mark.asyncio
async def test_coordinator_interruption_flow():
    """
    Simulate full interruption flow:
    1. Speculative query -> Flight search call
    2. Mid-stream interruption -> Cancel call, emit filler, dispatch Train search
    3. Tool result arrives -> Grounded response with correct snapshot
    """
    input_queue = asyncio.Queue()
    output_queue = asyncio.Queue()

    coordinator = ThreadWeaveCoordinator(session_id="test_integ_01")
    coordinator_task = asyncio.create_task(
        coordinator.start(input_queue, output_queue)
    )

    # 1. Manifest
    manifest = ToolManifest(tools=[
        {
            "name": "search_flights",
            "category": "read_only",
            "parameters": {"destination": {"type": "string"}},
        },
        {
            "name": "search_trains",
            "category": "read_only",
            "parameters": {"destination": {"type": "string"}},
        },
    ])
    await input_queue.put(manifest)

    # 2. User begins: "Book a flight to Mumbai"
    await input_queue.put(
        TranscriptChunk(text="Book a flight to Mumbai", is_end_of_turn=False)
    )
    await asyncio.sleep(0.05)

    # Output should have filler + speculative tool call
    action1 = await output_queue.get()
    assert isinstance(action1, FillerAction)

    action2 = await output_queue.get()
    assert isinstance(action2, ToolCallAction)
    assert action2.tool_name == "search_flights"
    assert action2.is_speculative is True
    first_call_id = action2.call_id

    # 3. Interruption: "wait, cancel that, find trains to Delhi instead"
    await input_queue.put(
        TranscriptChunk(
            text="wait, cancel that, find trains to Delhi instead",
            is_end_of_turn=True,
        )
    )
    await asyncio.sleep(0.05)

    # Output should have:
    # a) ToolCancelAction for flight call
    # b) FillerAction for train switch
    # c) ToolCallAction for train search
    cancel_act = await output_queue.get()
    assert isinstance(cancel_act, ToolCancelAction)
    assert cancel_act.call_id == first_call_id

    filler_act = await output_queue.get()
    assert isinstance(filler_act, FillerAction)
    assert "train" in filler_act.text.lower()

    train_call = await output_queue.get()
    assert isinstance(train_call, ToolCallAction)
    assert train_call.tool_name == "search_trains"
    assert train_call.arguments.get("destination") == "Delhi"

    # 4. Supply train result
    train_result = ToolResult(
        call_id=train_call.call_id,
        tool_name="search_trains",
        result={"options": [{"name": "Vande Bharat", "departure": "06:00 AM", "price": 1850}]},
    )
    await input_queue.put(train_result)
    await asyncio.sleep(0.05)

    # 5. Verify final response
    final_act = await output_queue.get()
    assert isinstance(final_act, FinalResponse)
    assert "Vande Bharat" in final_act.text
    snapshot = final_act.state_snapshot
    assert snapshot.intent == "search_trains"
    assert snapshot.slot_values["transport"] == "train"
    assert snapshot.slot_values["destination"] == "Delhi"

    # Stop coordinator
    await input_queue.put(None)
    await coordinator_task
