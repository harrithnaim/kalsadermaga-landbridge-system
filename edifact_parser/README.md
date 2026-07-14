# EDIFACT Parser — Phase 1

Parses UN/EDIFACT **COPRAR** (stowage/discharge plan) and **CODECO** (gate/status)
messages into the canonical `Container` / `MilestoneEvent` model used by the
rest of the landbridge system (feeds directly into the wagon allocation engine).

## Structure

```
edifact_parser/
  tokenizer.py     low-level: raw text -> Segments (handles UNA, escaping)
  models.py        canonical dataclasses: Container, MilestoneEvent
  mapper.py         message-specific: Segments -> canonical model
  samples/          example COPRAR and CODECO messages
  demo.py           runnable example
```

## Run the demo

```bash
cd edifact_parser/..     # the directory containing edifact_parser/
python -m edifact_parser.demo
```

## Use in your own code

```python
from edifact_parser import parse_interchange

with open("incoming_coprar.edi") as f:
    result = parse_interchange(f.read())

for container in result.containers:
    print(container.container_id, container.destination_station, container.gross_weight_kg)

if result.warnings:
    print("Check these:", result.warnings)
```

`result.containers` is a list of `Container` objects — pass these straight into
the wagon allocation engine (`destination`, `weight`, `hazmat` fields already
match what that engine expects).

## Before pointing this at a real shipping-line feed

This covers the common segment subset (EQD, MEA, DGS, LOC, RFF, TDT, DTM, STS) —
**not** the full D.95B code list directory. Before production use:

1. **Get the real message implementation guideline (MIG)** from whichever
   shipping line / EDI provider (INTTRA, GT Nexus, CargoSmart, etc.) will be
   sending you data. Qualifier codes in `mapper.py` (`LOC_QUALIFIERS`,
   `RFF_QUALIFIERS`, `CODECO_STATUS`) are the common subset, not exhaustive —
   real feeds sometimes use carrier-specific extensions.
2. **Validate against real sample files** from your actual counterpart before
   trusting this on live cargo.
3. **Decide on error handling policy** — right now unparseable/missing fields
   get added to `result.warnings` rather than raising, so a bad segment
   doesn't take down the whole batch. Confirm that's the behavior you want
   operationally (vs. hard-failing on any malformed message).
4. Consider a maintained EDIFACT library or commercial EDI translator for
   full schema validation once volume justifies it — this parser is built for
   clarity and the specific COPRAR/CODECO subset you need, not full D.95B
   compliance.

## Next pieces (not yet built)

- IFTMIN (forwarding instruction) mapper, if bookings arrive that way instead
  of / in addition to COPRAR
- Outbound IFTSTA generator (status updates back to the shipping line)
- Persistence layer (canonical store) — right now `parse_interchange` returns
  in-memory objects only
