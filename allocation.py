"""
Wagon allocation engine — Python port of the logic in the React prototype
(ecrl-stowage-prototype.jsx), now operating on real Container objects parsed
from EDI instead of mock data. This is the single source of truth going
forward; the frontend should call the backend rather than reimplementing
this logic in JS.
"""

from dataclasses import dataclass, field
from typing import List, Optional

MAX_WAGON_WEIGHT_KG = 60000
MAX_SLOTS = 2

# Illustrative route — replace with the real ECRL station list/sequence.
ROUTE = [
    {"id": "MYKUA", "name": "Kuantan Port", "seq": 0, "origin": True},
    {"id": "MYKTMK", "name": "Mentakab", "seq": 1},
    {"id": "MYBTG", "name": "Bentong", "seq": 2},
    {"id": "MYPKL", "name": "Port Klang", "seq": 3, "final": True},
]
STATION_BY_ID = {s["id"]: s for s in ROUTE}


@dataclass
class Wagon:
    id: str
    station: Optional[str]
    containers: List[dict] = field(default_factory=list)
    weight_kg: float = 0
    is_buffer: bool = False

    def as_dict(self):
        return {
            "id": self.id,
            "station": self.station,
            "station_name": STATION_BY_ID.get(self.station, {}).get("name"),
            "containers": [c["container_id"] for c in self.containers],
            "weight_kg": self.weight_kg,
            "is_buffer": self.is_buffer,
        }


def _slots_for(size_type: str) -> int:
    """Map an ISO 6346 size/type code to TEU slot footprint. Falls back to 1
    with the assumption logged by the caller if the code is unrecognized."""
    if not size_type:
        return 1
    first = size_type[0]
    if first == "2":
        return 1
    if first == "4":
        return 2
    return 1


def allocate(containers: List[dict]):
    """containers: list of dicts matching the Container canonical model
    (container_id, size_type, gross_weight_kg, hazmat_flag, destination_station).

    Returns dict with wagons (front-to-rear order), violations, and stats.
    """
    warnings = []
    groups = {}
    for c in containers:
        dest = c.get("destination_station")
        if dest not in STATION_BY_ID:
            warnings.append(f"{c.get('container_id')}: unknown destination_station '{dest}' — skipped")
            continue
        groups.setdefault(dest, []).append(c)

    # Front of train = last station visited (highest seq) ... rear = first station visited.
    ordered_stations = sorted(
        [s for s in ROUTE if not s.get("origin")],
        key=lambda s: -s["seq"],
    )

    wagons: List[Wagon] = []
    counter = 1

    for station in ordered_stations:
        group = sorted(groups.get(station["id"], []), key=lambda c: -(c.get("gross_weight_kg") or 0))
        current: Optional[Wagon] = None
        last_was_hazmat = False

        for container in group:
            weight = container.get("gross_weight_kg") or 0
            slots_needed = _slots_for(container.get("size_type"))
            is_hazmat = bool(container.get("hazmat_flag"))

            fitted = False
            if current and not is_hazmat and all(not c.get("hazmat_flag") for c in current.containers):
                used_slots = sum(_slots_for(c.get("size_type")) for c in current.containers)
                projected_weight = current.weight_kg + weight
                if used_slots + slots_needed <= MAX_SLOTS and projected_weight <= MAX_WAGON_WEIGHT_KG:
                    current.containers.append(container)
                    current.weight_kg = projected_weight
                    fitted = True

            if not fitted:
                if is_hazmat and last_was_hazmat:
                    wagons.append(Wagon(id=f"W{counter}", station=station["id"], is_buffer=True))
                    counter += 1
                current = Wagon(id=f"W{counter}", station=station["id"], containers=[container], weight_kg=weight)
                counter += 1
                wagons.append(current)
                last_was_hazmat = is_hazmat

    violations = [
        f"{w.id} exceeds {MAX_WAGON_WEIGHT_KG/1000:.0f}t limit ({w.weight_kg/1000:.1f}t)"
        for w in wagons if w.weight_kg > MAX_WAGON_WEIGHT_KG
    ]

    loaded = [w for w in wagons if not w.is_buffer]
    total_weight = sum(w.weight_kg for w in loaded)
    total_slots_used = sum(_slots_for(c.get("size_type")) for w in loaded for c in w.containers)
    utilization = round((total_slots_used / (len(loaded) * MAX_SLOTS)) * 100) if loaded else 0

    return {
        "wagons": [w.as_dict() for w in wagons],
        "violations": violations,
        "warnings": warnings,
        "stats": {
            "wagon_count": len(wagons),
            "loaded_count": len(loaded),
            "total_weight_kg": total_weight,
            "utilization_pct": utilization,
        },
    }
