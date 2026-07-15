"""
Canonical data model that EDIFACT messages get mapped into.
Mirrors the entities defined in ecrl-stowage-data-model.md (Container, MilestoneEvent).
Downstream services (allocation engine, tracking, single B/L) only ever touch
these objects -- never raw EDIFACT.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Container:
    container_id: str                  # ISO 6346, e.g. MSCU1234567
    size_type: str                      # e.g. "45G1" (raw code) or normalized "40HC"
    gross_weight_kg: Optional[float] = None
    hazmat_flag: bool = False
    hazmat_class: Optional[str] = None
    destination_station: Optional[str] = None   # location code, mapped to Station later
    discharge_port: Optional[str] = None
    loading_port: Optional[str] = None
    booking_ref: Optional[str] = None
    carrier_bl_ref: Optional[str] = None
    vessel_name: Optional[str] = None
    voyage_ref: Optional[str] = None
    full_empty: Optional[str] = None    # "full" / "empty"
    source_message_type: Optional[str] = None   # e.g. "COPRAR", "BAPLIE"
    bay: Optional[int] = None           # vessel stowage position, from BAPLIE
    row: Optional[int] = None
    tier: Optional[int] = None

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class MilestoneEvent:
    container_id: str
    event_type: str          # gate_in, discharged, allocated, loaded_wagon, departed, arrived_station, set_out, gated_out, loaded_vessel
    timestamp: Optional[str] = None
    location: Optional[str] = None
    source_system: Optional[str] = None
    source_message_type: Optional[str] = None

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class ParseResult:
    containers: List[Container] = field(default_factory=list)
    events: List[MilestoneEvent] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
