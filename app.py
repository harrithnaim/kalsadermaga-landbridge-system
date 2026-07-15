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
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from db import init_db, save_containers, get_containers, clear_containers, save_plan, get_last_plan

# edifact_parser/ lives alongside this backend/ folder — see repo layout note in README.
sys.path.append(str(Path(__file__).parent.parent))
from edifact_parser import parse_interchange  # noqa: E402
from allocation import allocate  # noqa: E402

app = Flask(__name__)
init_db()
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == DASHBOARD_USERNAME and request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", containers=get_containers(), plan=get_last_plan())

@app.route("/dashboard/allocate", methods=["POST"])
@login_required
def dashboard_allocate():
    containers = get_containers()
    if containers:
        save_plan(allocate(containers))
    return redirect(url_for("dashboard"))

@app.route("/dashboard/clear", methods=["POST"])
@login_required
def dashboard_clear():
    clear_containers()
    return redirect(url_for("dashboard"))
import os
from functools import wraps

API_KEY = os.environ.get("API_KEY")

def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not API_KEY:
            return jsonify({"error": "server misconfigured: API_KEY not set"}), 500
        if request.headers.get("X-API-Key") != API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper
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
@require_api_key
def internal_parse():
    raw = request.get_data(as_text=True)
    if not raw:
        return jsonify({"error": "empty request body"}), 400
    result = parse_interchange(raw)
    containers = [c.as_dict() for c in result.containers]
    events = [e.as_dict() for e in result.events]
    if containers:
        save_containers(containers)
    return jsonify({
        "containers": containers,
        "events": events,
        "warnings": result.warnings,
        "containers_in_queue": len(get_containers()),
    })



@app.route("/internal/allocate", methods=["POST"])
@require_api_key
def internal_allocate():
    body = request.get_json(silent=True) or {}
    containers = body.get("containers") or get_containers()
    if not containers:
        return jsonify({"error": "no containers to allocate — call /internal/parse first, or pass 'containers'"}), 400
    plan = allocate(containers)
    save_plan(plan)
    return jsonify(plan)


@app.route("/internal/queue", methods=["GET"])
@require_api_key
def internal_queue():
    return jsonify({"containers": get_containers()})


@app.route("/internal/queue", methods=["DELETE"])
@require_api_key
def internal_clear_queue():
    clear_containers()
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
@require_api_key
def partner_wagon_plan():
    """The only thing ECRL's system ever sees: the latest wagon plan, stripped
    of container identity and all commercial data. Swap this for real auth
    (API key / OAuth client) before this leaves prototype stage."""
    plan = get_last_plan()
    if not plan:
        return jsonify({"error": "no allocation run yet"}), 404
    return jsonify(_to_partner_view(plan))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
