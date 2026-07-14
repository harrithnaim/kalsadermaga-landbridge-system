"""
Landbridge operator backend — prototype.

Two-tier API reflecting the "Kalsa Dermaga stays the operator" model:

  /internal/*      Full access. EDI intake, parsed containers, allocation runs,
                    everything. This is Kalsa Dermaga's own operator platform.

  /partner/ecrl/*   Deliberately narrow. ECRL only ever sees wagon plans
                    (container id, weight, hazmat flag, station, wagon
                    assignment) — never rates, shipper identity, or booking
                    commercial terms. This boundary is enforced here, not
                    just documented.

Run:
    pip install -r requirements.txt
    python app.py
Then:
    curl -X POST http://localhost:5000/internal/parse -H "Content-Type: text/plain" --data-binary @../edifact_parser/samples/sample_coprar.edi
"""

import sys
from pathlib import Path
from flask import Flask, request, jsonify

# edifact_parser/ lives alongside this backend/ folder — see repo layout note in README.
sys.path.append(str(Path(__file__).parent.parent))
from edifact_parser import parse_interchange  # noqa: E402
from allocation import allocate  # noqa: E402

app = Flask(__name__)
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Kalsa Dermaga Landbridge API",
        "status": "running",
        "endpoints": ["/internal/parse", "/internal/allocate", "/internal/queue", "/partner/ecrl/wagon-plan"],
    })
# In-memory store for the prototype. Swap for real persistence (Postgres/SQLite)
# before this handles anything beyond a demo session.
_STATE = {"containers": [], "last_plan": None}


# ---------------------------------------------------------------------------
# INTERNAL — Kalsa Dermaga operator platform. Full data, no scoping.
# ---------------------------------------------------------------------------

@app.route("/internal/parse", methods=["POST"])
def internal_parse():
    """Accepts raw EDIFACT text (COPRAR or CODECO), returns parsed canonical data."""
    raw = request.get_data(as_text=True)
    if not raw:
        return jsonify({"error": "empty request body"}), 400

    result = parse_interchange(raw)
    containers = [c.as_dict() for c in result.containers]
    events = [e.as_dict() for e in result.events]

    if containers:
        _STATE["containers"].extend(containers)

    return jsonify({
        "containers": containers,
        "events": events,
        "warnings": result.warnings,
        "containers_in_queue": len(_STATE["containers"]),
    })


@app.route("/internal/allocate", methods=["POST"])
def internal_allocate():
    """Runs the wagon allocation engine against the current container queue
    (or an explicit list passed in the request body)."""
    body = request.get_json(silent=True) or {}
    containers = body.get("containers") or _STATE["containers"]
    if not containers:
        return jsonify({"error": "no containers to allocate — call /internal/parse first, or pass 'containers'"}), 400

    plan = allocate(containers)
    _STATE["last_plan"] = plan
    return jsonify(plan)


@app.route("/internal/queue", methods=["GET"])
def internal_queue():
    return jsonify({"containers": _STATE["containers"]})


@app.route("/internal/queue", methods=["DELETE"])
def internal_clear_queue():
    _STATE["containers"] = []
    return jsonify({"status": "cleared"})


# ---------------------------------------------------------------------------
# PARTNER (ECRL) — narrow, read-only, operational data only.
# ---------------------------------------------------------------------------

def _to_partner_view(plan: dict) -> dict:
    """Strip a full allocation plan down to what ECRL is allowed to see.
    No booking refs, no B/L numbers, no commercial data of any kind."""
    return {
        "wagons": [
            {
                "wagon_id": w["id"],
                "station": w["station"],
                "station_name": w["station_name"],
                "container_count": len(w["containers"]),
                "weight_kg": w["weight_kg"],
                "is_buffer": w["is_buffer"],
            }
            for w in plan["wagons"]
        ],
        "violations": plan["violations"],
        "stats": plan["stats"],
    }


@app.route("/partner/ecrl/wagon-plan", methods=["GET"])
def partner_wagon_plan():
    """The only thing ECRL's system ever sees: the latest wagon plan, stripped
    of container identity and all commercial data. Swap this for real auth
    (API key / OAuth client) before this leaves prototype stage."""
    if not _STATE["last_plan"]:
        return jsonify({"error": "no allocation run yet"}), 404
    return jsonify(_to_partner_view(_STATE["last_plan"]))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
