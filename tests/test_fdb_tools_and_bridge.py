"""
Unit tests for ThreadWeave FDB-v3 Tool Registry and LiveKit Bridge
"""

import pytest
import json
import asyncio
from threadweave.tool_registry import (
    AssistantFnc,
    LatencyTracker,
    DynamicResultStore,
    normalize_city,
    normalize_doc_type,
    normalize_doc_number,
    MockAPIs,
)
from threadweave.lk_bridge import FastPathTranscriptFilter, ThreadWeaveSessionBridge


def test_normalization():
    assert normalize_city("vegas") == "Las Vegas"
    assert normalize_city("NYC") == "New York"
    assert normalize_city("Berlin") == "Berlin"

    assert normalize_doc_type("driver license") == "driver_license"
    assert normalize_doc_type("driver's license") == "driver_license"
    assert normalize_doc_type("passport") == "passport"
    assert normalize_doc_type("visa") == "visa"

    # Verify ASR phonetic digit normalization for travel identifiers
    assert normalize_doc_number("P-8-8-9-9-0-0-1-1") == "P9-9-9-90011"
    assert normalize_doc_number("P889-90011") == "P9-9-9-90011"
    assert normalize_doc_number("P9-9-9-90011") == "P9-9-9-90011"
    assert normalize_doc_number("DL555") == "DL555"


def test_dynamic_reference_resolution():
    store = DynamicResultStore()
    store.record("search_flights", {
        "status": "success",
        "flights": [{"flight_id": "FL123", "price": 450.0}]
    })
    store.record("search_products", {
        "status": "success",
        "products": [{"product_id": "PROD99", "name": "Headphones"}]
    })

    assert store.resolve("$RESULT_0.flights[0].flight_id") == "FL123"
    assert store.resolve("$RESULT_1.products[0].product_id") == "PROD99"
    assert store.resolve("EXPLICIT_ID") == "EXPLICIT_ID"


@pytest.mark.asyncio
async def test_all_12_fdb_tools():
    tracker = LatencyTracker()
    fnc = AssistantFnc(tracker, "test_room_101")

    # 1. Travel & Identity
    r = json.loads(await fnc.search_flights("vegas", "2026-08-20"))
    assert r["status"] == "success"
    assert r["flights"][0]["destination"] == "Las Vegas"

    r = json.loads(await fnc.book_flight("Casey Lee", "$RESULT_0.flights[0].flight_id"))
    assert r["status"] == "success"
    assert r["passenger"] == "Casey Lee"
    assert r["flight_id"] == "FL123"

    r = json.loads(await fnc.update_identity_doc("driver license", "DL12345678"))
    assert r["status"] == "success"
    assert r["updated_doc"] == "driver_license"
    assert r["masked_number"] == "5678"

    # 2. Finance & Billing
    r = json.loads(await fnc.get_card_benefits("platinum"))
    assert r["status"] == "success"
    assert "2% Cashback" in r["benefits"]

    r = json.loads(await fnc.get_exchange_rate(100.0, "EUR", "USD"))
    assert r["status"] == "success"
    assert r["converted_amount"] == 110.0

    r = json.loads(await fnc.modify_autopay("credit card", "checking"))
    assert r["status"] == "success"
    assert r["autopay_enabled"] is True

    # 3. Housing & Location
    r = json.loads(await fnc.search_apartments("vegas", 2, 2500.0))
    assert r["status"] == "success"
    assert r["city"] == "Las Vegas"

    r = json.loads(await fnc.calculate_commute("Home", "Office", "driving"))
    assert r["status"] == "success"
    assert r["duration_mins"] == 25

    r = json.loads(await fnc.update_search_filter("pet_friendly", True))
    assert r["status"] == "success"
    assert r["new_value"] is True

    # 4. E-Commerce
    r = json.loads(await fnc.track_order("BOB12"))
    assert r["status"] == "success"
    assert r["order_id"] == "BOB12"

    r = json.loads(await fnc.search_products("headphones", 150.0))
    assert r["status"] == "success"
    assert len(r["products"]) == 1

    r = json.loads(await fnc.add_to_cart("PROD1", 2))
    assert r["status"] == "success"
    assert r["quantity"] == 2


@pytest.mark.asyncio
async def test_idempotency_protection():
    tracker = LatencyTracker()
    fnc = AssistantFnc(tracker, "test_room_idempotency")

    # First execution executes normally
    r1 = json.loads(await fnc.book_flight("Morgan Smith", "FL123"))
    assert r1.get("cached") is not True

    # Second execution with identical parameters is caught by idempotency layer
    r2 = json.loads(await fnc.book_flight("Morgan Smith", "FL123"))
    assert r2.get("cached") is True


def test_fastpath_self_correction_interception():
    trans_filter = FastPathTranscriptFilter()
    token = trans_filter.new_turn()
    assert not token.is_cancelled

    # User starts saying "Book flight to Paris..."
    has_corr, _, pivot = trans_filter.inspect_transcript("I need to book a flight to Paris")
    assert not has_corr
    assert not token.is_cancelled

    # User self-corrects mid-utterance: "actually scratch that, make that Berlin"
    has_corr, _, pivot = trans_filter.inspect_transcript("actually scratch that, make that Berlin instead")
    assert has_corr
    assert pivot is not None
    # Stale token was cancelled!
    assert token.is_cancelled
    assert token.cancel_reason.startswith("self_correction")


@pytest.mark.asyncio
async def test_connected_vehicle_and_iot_tools():
    tracker = LatencyTracker()
    fnc = AssistantFnc(tracker, "test_room_cockpit")

    # 1. POI search
    r = json.loads(await fnc.search_nearby_poi("coffee"))
    assert r["status"] == "success"
    assert "Starbucks" in r["results"][0]["name"]

    # 2. Navigation
    r = json.loads(await fnc.set_car_destination("JFK International Airport - Terminal 4"))
    assert r["status"] == "success"
    assert r["action"] == "route_active"
    assert r["eta_minutes"] == 25

    # 3. Cancellation rollback
    r = json.loads(await fnc.cancel_navigation(reason="destination_changed"))
    assert r["status"] == "success"
    assert r["action"] == "route_cancelled"

    # 4. CAN-bus telemetry
    r = json.loads(await fnc.check_vehicle_telemetry("range"))
    assert r["status"] == "success"
    assert r["battery_level_pct"] == 74
    assert r["range_sufficient_for_trip"] is True

    # 5. SmartThings IoT
    r = json.loads(await fnc.smartthings_set_mode("home", 22.0))
    assert r["status"] == "success"
    assert r["mode_set"] == "home"

    # 6. Flight status
    r = json.loads(await fnc.check_flight_status("DL422"))
    assert r["status"] == "success"
    assert r["flight_number"] == "DL422"
    assert r["gate"] == "B32"

