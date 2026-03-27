from typing import Set

ALLOWED_RELATIONS: Set[str] = {
    "following",
    "conflict_with",
    "yielding_to",
    "crossing",
}

VEHICLE_TYPES: Set[str] = {
    "CAR",
    "VAN",
    "BUS",
    "TRUCK",
    "MOTORCYCLIST",
    "CYCLIST",
}
