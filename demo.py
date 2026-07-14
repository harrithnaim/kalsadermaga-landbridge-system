"""
Demo: parse sample COPRAR + CODECO files into the canonical model.

Run (from the directory containing edifact_parser/):
    python -m edifact_parser.demo
"""

import json
from pathlib import Path
from edifact_parser.mapper import parse_interchange

SAMPLES = Path(__file__).parent / "samples"


def main():
    print("=" * 70)
    print("PARSING COPRAR (pre-arrival container/stowage data)")
    print("=" * 70)
    coprar_raw = (SAMPLES / "sample_coprar.edi").read_text()
    coprar_result = parse_interchange(coprar_raw)

    for c in coprar_result.containers:
        print(json.dumps(c.as_dict(), indent=2))
    if coprar_result.warnings:
        print("Warnings:", coprar_result.warnings)

    print()
    print("=" * 70)
    print("PARSING CODECO (gate / discharge status events)")
    print("=" * 70)
    codeco_raw = (SAMPLES / "sample_codeco.edi").read_text()
    codeco_result = parse_interchange(codeco_raw)

    for e in codeco_result.events:
        print(json.dumps(e.as_dict(), indent=2))
    if codeco_result.warnings:
        print("Warnings:", codeco_result.warnings)

    print()
    print(f"Parsed {len(coprar_result.containers)} containers, "
          f"{len(codeco_result.events)} milestone events.")
    print("These Container objects are what feeds the wagon allocation engine's")
    print("`destination_station` + `gross_weight_kg` + `hazmat_flag` fields directly.")


if __name__ == "__main__":
    main()
