"""
Maps parsed COPRAR and CODECO segments onto the canonical model (models.py).

This is a pragmatic subset of the UN/EDIFACT D.95B COPRAR and CODECO
message structures -- covering the segments that matter for container
discharge planning and gate/status tracking. It is NOT a full implementation
of every code list in the D.95B directory.

Before pointing this at a real shipping line feed:
  1. Get their actual message implementation guideline (MIG) -- carriers and
     EDI providers (INTTRA, GT Nexus, CargoSmart, etc.) often use slightly
     different qualifier subsets or proprietary extensions.
  2. Validate LOC/RFF/DGS qualifier codes against that MIG -- the qualifier
     dictionaries below (LOC_QUALIFIERS, RFF_QUALIFIERS, CODECO_STATUS) are
     the common subset, not the full UNECE code list.
  3. Consider a proper EDIFACT validation library for production rather than
     relying solely on this hand-rolled parser.

Segment cheat sheet used here:
  EQD  Equipment details      -> starts a new container "loop"
  MEA  Measurements           -> weight
  DGS  Dangerous goods        -> hazmat class
  LOC  Location                -> port of discharge / destination station
  RFF  Reference                -> booking ref / B/L ref
  TDT  Transport details        -> vessel / voyage (COPRAR header)
  DTM  Date/time                -> event timestamp (CODECO loop)
  STS  Status                   -> gate event type (CODECO loop)
"""

from typing import List, Tuple
from .tokenizer import Segment
from .models import Container, MilestoneEvent, ParseResult

LOC_QUALIFIERS = {
    "9": "loading_port",
    "11": "discharge_port",
    "147": "destination_station",
    "165": "current_location",
}

RFF_QUALIFIERS = {
    "BN": "booking_ref",
    "BM": "carrier_bl_ref",
}

FULL_EMPTY = {
    "4": "full",
    "5": "empty",
}

# CODECO status codes (STS segment) -- common subset.
CODECO_STATUS = {
    "1": "gate_in",
    "2": "gate_out",
    "3": "discharged",
    "4": "loaded_vessel",
    "5": "gated_out",
}


def _split_equipment_loops(segments: List[Segment]) -> Tuple[List[Segment], List[List[Segment]]]:
    """Split a message's segments into a header block (before first EQD)
    and a list of per-container loops (each starting with an EQD segment)."""
    header, loops = [], []
    current = None
    for seg in segments:
        if seg.tag == "EQD":
            if current is not None:
                loops.append(current)
            current = [seg]
        elif current is not None:
            current.append(seg)
        else:
            header.append(seg)
    if current is not None:
        loops.append(current)
    return header, loops


def _header_context_coprar(header: List[Segment]) -> dict:
    ctx = {"vessel_name": None, "voyage_ref": None, "discharge_port": None}
    for seg in header:
        if seg.tag == "TDT":
            ctx["voyage_ref"] = seg.value(1, 0)
            # vessel name position varies by MIG (often element 3 or 7); check both
            ctx["vessel_name"] = seg.value(3, 0) or seg.value(7, 0)
        elif seg.tag == "LOC":
            qualifier = seg.value(0, 0)
            if LOC_QUALIFIERS.get(qualifier) == "discharge_port":
                ctx["discharge_port"] = seg.value(1, 0)
    return ctx


def parse_coprar(segments: List[Segment], warnings: List[str]) -> List[Container]:
    header, loops = _split_equipment_loops(segments)
    ctx = _header_context_coprar(header)
    containers = []

    for loop in loops:
        eqd = loop[0]
        container = Container(
            container_id=eqd.value(1, 0, default=""),
            size_type=eqd.value(2, 0, default=""),
            full_empty=FULL_EMPTY.get(eqd.value(4, 0), None),
            vessel_name=ctx["vessel_name"],
            voyage_ref=ctx["voyage_ref"],
            discharge_port=ctx["discharge_port"],
            source_message_type="COPRAR",
        )
        if not container.container_id:
            warnings.append("EQD segment missing container id; skipped")
            continue

        for seg in loop[1:]:
            if seg.tag == "MEA":
                unit_and_value = seg.element(2, default=[])
                if len(unit_and_value) >= 2:
                    try:
                        container.gross_weight_kg = float(unit_and_value[1])
                    except ValueError:
                        warnings.append(f"{container.container_id}: unparseable weight value")
            elif seg.tag == "DGS":
                container.hazmat_flag = True
                container.hazmat_class = seg.value(1, 0)
            elif seg.tag == "LOC":
                qualifier = LOC_QUALIFIERS.get(seg.value(0, 0))
                if qualifier == "destination_station":
                    container.destination_station = seg.value(1, 0)
                elif qualifier == "discharge_port":
                    container.discharge_port = seg.value(1, 0)
            elif seg.tag == "RFF":
                ref = RFF_QUALIFIERS.get(seg.value(0, 0))
                ref_value = seg.value(0, 1)
                if ref == "booking_ref":
                    container.booking_ref = ref_value
                elif ref == "carrier_bl_ref":
                    container.carrier_bl_ref = ref_value

        containers.append(container)

    return containers


def parse_codeco(segments: List[Segment], warnings: List[str]) -> List[MilestoneEvent]:
    header, loops = _split_equipment_loops(segments)
    events = []

    for loop in loops:
        eqd = loop[0]
        container_id = eqd.value(1, 0, default="")
        if not container_id:
            warnings.append("EQD segment missing container id in CODECO loop; skipped")
            continue

        event_type = None
        timestamp = None
        location = None

        for seg in loop[1:]:
            if seg.tag == "STS":
                event_type = CODECO_STATUS.get(seg.value(0, 0), f"unknown_status_{seg.value(0, 0)}")
            elif seg.tag == "DTM":
                timestamp = seg.value(0, 1)
            elif seg.tag == "LOC":
                location = seg.value(1, 0)

        events.append(MilestoneEvent(
            container_id=container_id,
            event_type=event_type or "unknown",
            timestamp=timestamp,
            location=location,
            source_message_type="CODECO",
        ))

    return events


def _split_stowage_loops(segments: List[Segment]) -> Tuple[List[Segment], List[List[Segment]]]:
    """BAPLIE loops start with a stowage-location LOC (qualifier '147'), which
    comes BEFORE the EQD for that container -- opposite order from COPRAR/CODECO,
    so this needs its own splitter rather than reusing _split_equipment_loops."""
    header, loops = [], []
    current = None
    for seg in segments:
        if seg.tag == "LOC" and seg.value(0, 0) == "147":
            if current is not None:
                loops.append(current)
            current = [seg]
        elif current is not None:
            current.append(seg)
        else:
            header.append(seg)
    if current is not None:
        loops.append(current)
    return header, loops


def _parse_bay_row_tier(code):
    """Fixed-width BBRRTT stowage code -> (bay, row, tier), e.g. '020486' -> (2, 4, 86).
    Returns (None, None, None) if the code is missing or malformed."""
    if not code or len(code) < 6:
        return None, None, None
    try:
        return int(code[0:2]), int(code[2:4]), int(code[4:6])
    except ValueError:
        return None, None, None


def parse_baplie(segments: List[Segment], warnings: List[str]) -> List[Container]:
    header, loops = _split_stowage_loops(segments)
    ctx = _header_context_coprar(header)  # same header shape (TDT vessel/voyage) as COPRAR
    containers = []

    for loop in loops:
        loc_seg = loop[0]
        bay, row, tier = _parse_bay_row_tier(loc_seg.value(1, 0))

        eqd = next((s for s in loop if s.tag == "EQD"), None)
        if eqd is None:
            warnings.append("BAPLIE loop missing EQD segment; skipped")
            continue

        container = Container(
            container_id=eqd.value(1, 0, default=""),
            size_type=eqd.value(2, 0, default=""),
            full_empty=FULL_EMPTY.get(eqd.value(4, 0), None),
            vessel_name=ctx["vessel_name"],
            voyage_ref=ctx["voyage_ref"],
            source_message_type="BAPLIE",
            bay=bay, row=row, tier=tier,
        )
        if not container.container_id:
            warnings.append("EQD segment missing container id in BAPLIE loop; skipped")
            continue

        for seg in loop:
            if seg.tag == "MEA":
                unit_and_value = seg.element(2, default=[])
                if len(unit_and_value) >= 2:
                    try:
                        container.gross_weight_kg = float(unit_and_value[1])
                    except ValueError:
                        warnings.append(f"{container.container_id}: unparseable weight value")
            elif seg.tag == "DGS":
                container.hazmat_flag = True
                container.hazmat_class = seg.value(1, 0)
            elif seg.tag == "LOC":
                qualifier = seg.value(0, 0)
                if qualifier == "9":
                    container.loading_port = seg.value(1, 0)
                elif qualifier == "11":
                    container.discharge_port = seg.value(1, 0)
            elif seg.tag == "RFF":
                ref = RFF_QUALIFIERS.get(seg.value(0, 0))
                ref_value = seg.value(0, 1)
                if ref == "booking_ref":
                    container.booking_ref = ref_value
                elif ref == "carrier_bl_ref":
                    container.carrier_bl_ref = ref_value

        containers.append(container)

    return containers


def parse_interchange(raw: str) -> ParseResult:
    """Top-level entry point: parse a raw EDIFACT interchange (possibly
    containing multiple COPRAR/CODECO messages) into the canonical model."""
    from .tokenizer import tokenize, split_messages

    result = ParseResult()
    segments = tokenize(raw)
    messages = split_messages(segments)

    if not messages:
        result.warnings.append("No UNH/UNT message pairs found in interchange")
        return result

    for msg_type, version, msg_segments in messages:
        if msg_type == "COPRAR":
            result.containers.extend(parse_coprar(msg_segments, result.warnings))
        elif msg_type == "CODECO":
            result.events.extend(parse_codeco(msg_segments, result.warnings))
        elif msg_type == "BAPLIE":
            result.containers.extend(parse_baplie(msg_segments, result.warnings))
        else:
            result.warnings.append(f"Unsupported message type '{msg_type}' -- skipped")

    return result
