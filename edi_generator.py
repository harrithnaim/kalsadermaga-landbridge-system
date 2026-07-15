"""
Outbound EDI generator.

Takes a confirmed wagon allocation plan (the same dict shape allocation.py
produces) and writes it back out as an EDIFACT-formatted status message,
modeled loosely on IFTSTA (forwarding and transport status) conventions --
one EQD/STS/DTM/LOC/RFF loop per container, reporting it as loaded onto its
assigned wagon and bound for its set-out station.

Same caveat as the inbound parsers: this is a pragmatic subset, not a
validated implementation guideline. Before sending this to a real shipping
line or ECRL, confirm the actual message type and qualifiers they expect --
this gives you a working, inspectable starting point, not a finished spec.
"""

from datetime import datetime, timezone

STATUS_LOADED_WAGON = "6"  # local convention: rail-specific extension, not a standard EDIFACT code


def generate_wagon_status_edi(plan: dict, sender: str = "KALSADERMAGA", recipient: str = "SHIPLINEXYZ") -> str:
    now = datetime.now(timezone.utc)
    interchange_date = now.strftime("%y%m%d")
    interchange_time = now.strftime("%H%M")
    dtm_value = now.strftime("%Y%m%d%H%M")

    lines = [
        "UNA:+.? '",
        f"UNB+UNOC:3+{sender}:ZZ+{recipient}:ZZ+{interchange_date}:{interchange_time}+1'",
        "UNH+1+IFTSTA:D:95B:UN'",
        f"BGM+23+WAGONPLAN{now.strftime('%Y%m%d%H%M%S')}+9'",
    ]

    for wagon in plan.get("wagons", []):
        if wagon.get("is_buffer"):
            continue
        for container_id in wagon.get("containers", []):
            lines.append(f"EQD+CN+{container_id}+'")
            lines.append(f"STS+{STATUS_LOADED_WAGON}'")
            lines.append(f"DTM+178:{dtm_value}:203'")
            lines.append(f"LOC+147+{wagon.get('station', '')}'")
            lines.append(f"RFF+WGN:{wagon.get('id', '')}'")

    segment_count = len(lines) - 1  # UNH itself not counted, per typical convention
    lines.append(f"UNT+{segment_count}+1'")
    lines.append("UNZ+1+1'")

    return "\n".join(lines)
