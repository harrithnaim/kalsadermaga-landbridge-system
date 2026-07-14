# Landbridge Operator Backend — Prototype

Ports the allocation logic out of the React demo and wires it to the real
EDIFACT parser, structured around the "Kalsa Dermaga stays the operator"
model: two API tiers, one internal (full data), one partner-facing (scoped).

## Run it

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Runs on `http://localhost:5000`.

## Try it

```bash
# 1. Feed it a COPRAR message (parses + queues containers)
curl -X POST http://localhost:5000/internal/parse \
  -H "Content-Type: text/plain" \
  --data-binary @../edifact_parser/samples/sample_coprar.edi

# 2. Run allocation against the queue
curl -X POST http://localhost:5000/internal/allocate

# 3. See what ECRL's system would be allowed to see
curl http://localhost:5000/partner/ecrl/wagon-plan
```

Step 3's response is deliberately stripped — no container IDs, no booking
refs, no B/L numbers. Compare it against step 2's full response to see the
boundary in effect.

## Why two tiers

`/internal/*` is Kalsa Dermaga's own operator platform — full container
identity, booking references, everything from EDI. `/partner/ecrl/*` is what
a rail partner integration would actually be allowed to call: wagon-level
operational data only (weight, station, hazmat flag, container count), never
who owns the cargo or what it's worth. This is enforced in `_to_partner_view()`
in `app.py`, not just documented — worth keeping that function as the single
choke point as more partner-facing fields get added later, rather than letting
individual routes decide what to expose.

## What's still prototype-grade, not production

- **No auth.** Both tiers are wide open. Before ECRL (or anyone) integrates,
  `/partner/ecrl/*` needs real API-key or OAuth client scoping, and
  `/internal/*` needs to sit behind your own operator login.
- **In-memory state only.** Restarting the process wipes the container queue.
  Swap `_STATE` for Postgres/SQLite once this handles more than a demo.
- **Single ECRL partner assumed.** If Port Klang's operator or another rail
  line eventually integrates too, generalize `/partner/ecrl/*` into
  `/partner/<partner_id>/*` with per-partner scoping rules.
- **No outbound EDI yet.** Status updates back to the shipping line (IFTSTA)
  aren't built — this only handles inbound COPRAR/CODECO and the allocation
  step.

## Layout

```
edifact_parser/    (sibling folder — the EDI parser built in Phase 1)
backend/
  app.py           Flask app, internal + partner routes
  allocation.py    wagon allocation engine (Python port of the JS prototype)
  requirements.txt
```
