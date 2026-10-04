"""
Mock APIs for Samsung Harman In-Car Digital Cockpit & SmartThings Auto

Features:
- Deterministic POI Search, Real-Time Turn-by-Turn Navigation, and Route Cancellation
- Vehicle Telemetry Monitoring (Battery/Fuel Range, Tire Pressure)
- Samsung SmartThings IoT Integration (Home Mode, Climate Control)
- Flight Tracker API for airport emergency rerouting
"""

import time
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("CarAPIs")


def search_nearby_poi(category: str, location: Optional[str] = "current_gps") -> dict:
    """Find points of interest near the vehicle's current location."""
    cat_lower = category.lower().strip()
    if "coffee" in cat_lower or "starbucks" in cat_lower or "cafe" in cat_lower:
        return {
            "status": "success",
            "category": "coffee",
            "results": [
                {"name": "Starbucks - 5th Ave", "distance_miles": 0.4, "eta_mins": 3, "address": "120 5th Ave"},
                {"name": "Blue Bottle Coffee", "distance_miles": 1.2, "eta_mins": 7, "address": "450 Broadway"},
            ]
        }
    elif "airport" in cat_lower:
        return {
            "status": "success",
            "category": "airport",
            "results": [
                {"name": "JFK International Airport - Terminal 4", "distance_miles": 14.2, "eta_mins": 26, "address": "Queens, NY 11430"},
                {"name": "LaGuardia Airport (LGA)", "distance_miles": 9.8, "eta_mins": 21, "address": "East Elmhurst, NY 11371"},
            ]
        }
    elif "gas" in cat_lower or "charge" in cat_lower or "charging" in cat_lower:
        return {
            "status": "success",
            "category": "ev_charging",
            "results": [
                {"name": "Samsung FastCharge EV Hub", "distance_miles": 0.8, "eta_mins": 4, "available_plugs": 6},
            ]
        }
    return {
        "status": "success",
        "category": category,
        "results": [
            {"name": f"{category.title()} Location A", "distance_miles": 1.5, "eta_mins": 8, "address": "Downtown"},
        ]
    }


def set_car_destination(destination: str, route_type: str = "fastest") -> dict:
    """Sets vehicle navigation route to the requested destination."""
    dest_lower = destination.lower()
    if "airport" in dest_lower or "jfk" in dest_lower:
        eta = 25
        miles = 14.5
    elif "starbucks" in dest_lower or "coffee" in dest_lower:
        eta = 4
        miles = 0.5
    elif "home" in dest_lower:
        eta = 18
        miles = 8.2
    else:
        eta = 15
        miles = 6.0

    return {
        "status": "success",
        "action": "route_active",
        "destination": destination,
        "eta_minutes": eta,
        "distance_miles": miles,
        "route_type": route_type,
        "navigation_id": f"NAV-{int(time.time()) % 10000}",
    }


def cancel_navigation(navigation_id: Optional[str] = None, reason: str = "user_interruption") -> dict:
    """Compensating rollback tool: instantly clears active navigation."""
    return {
        "status": "success",
        "action": "route_cancelled",
        "navigation_id": navigation_id or "CURRENT",
        "reason": reason,
        "timestamp": time.time(),
    }


def check_vehicle_telemetry(metric: str = "range") -> dict:
    """Inspects vehicle sensors via Harman digital cockpit CAN bus."""
    return {
        "status": "success",
        "battery_level_pct": 74,
        "estimated_range_miles": 218,
        "tire_pressure_psi": {"fl": 34, "fr": 34, "rl": 35, "rr": 35},
        "range_sufficient_for_trip": True,
    }


def smartthings_set_mode(mode: str = "away", thermostat_temp_c: Optional[float] = 22.0) -> dict:
    """Triggers Samsung SmartThings home automation scene from car."""
    return {
        "status": "success",
        "system": "Samsung SmartThings",
        "mode_set": mode,
        "thermostat_target_c": thermostat_temp_c,
        "security_system": "armed" if mode == "away" else "disarmed",
        "lights_automated": True,
    }


def check_flight_status(flight_number: str) -> dict:
    """Fetches real-time flight status for travel urgency handling."""
    return {
        "status": "success",
        "flight_number": flight_number.upper(),
        "airline": "Delta Air Lines",
        "departure_airport": "JFK",
        "gate": "B32",
        "status": "On Time - Boarding in 35 mins",
        "terminal": "Terminal 4",
    }


class CarAPIRegistry:
    FUNCTIONS = {
        "search_nearby_poi": search_nearby_poi,
        "set_car_destination": set_car_destination,
        "cancel_navigation": cancel_navigation,
        "check_vehicle_telemetry": check_vehicle_telemetry,
        "smartthings_set_mode": smartthings_set_mode,
        "check_flight_status": check_flight_status,
    }

    @classmethod
    def call(cls, func_name: str, **kwargs) -> dict:
        func = cls.FUNCTIONS.get(func_name)
        if not func:
            return {"status": "error", "message": f"Unknown function {func_name}"}
        return func(**kwargs)
