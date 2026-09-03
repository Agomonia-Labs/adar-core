"""
domains/scheduling/tools/__init__.py
Maps tool name strings from agents_config.scheduling.json to callable functions.
"""

from domains.scheduling.tools.availability_tools import (
    find_practice,
    list_appointment_types,
    list_providers,
    check_availability,
    get_weekly_availability,
    hold_slot,
    confirm_booking,
    cancel_appointment,
    reschedule_appointment,
    list_my_appointments,
)

TOOL_REGISTRY: dict = {
    "find_practice": find_practice,
    "list_appointment_types": list_appointment_types,
    "list_providers": list_providers,
    "check_availability": check_availability,
    "get_weekly_availability": get_weekly_availability,
    "hold_slot": hold_slot,
    "confirm_booking": confirm_booking,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment,
    "list_my_appointments": list_my_appointments,
}
