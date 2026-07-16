"""
Landbridge operator backend — prototype.

Two-tier API reflecting the "Kalsa Dermaga stays the operator" model, plus a
browser dashboard for human operators (separate session login, not the API key).
"""

import os
import sys
import datetime
from pathlib import Path
from collections import defaultdict
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for,
    session, flash, get_flashed_messages, Response,
)

sys.path.append(str(Path(__file__).parent.parent))
from edifact_parser import parse_interchange  # noqa: E402
from allocation import allocate, ROUTE  # noqa: E402
from db import (  # noqa: E402
    init_db, save_containers, get_containers, clear_containers,
    save_plan, get_last_plan, save_job, get_jobs, get_job,
)
from edi_generator import generate_wagon_status_edi  # noqa: E402
from rates import (  # noqa: E402
    build_job, PARTNER_COST_RATES, HAZMAT_COST_SURCHARGE,
    CLIENT_SELL_RATES, CLIENT_HAZMAT_SURCHARGE, CURRENCY,
)

app = Flask(__name__)
init_db()

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")
API_KEY = os.environ.get("API_KEY")

PORT_COLOR_PALETTE = ["#46b9ae", "#f2a93b", "#8f82d9", "#5c90ee", "#e36c86", "#7fd48f"]


def _port_colors(ports):
    return {p: PORT_COLOR_PALETTE[i % len(PORT_COLOR_PALETTE)] for i, p in enumerate(ports)}


# ---------------------------------------------------------------------------
# AUTH — two separate mechanisms: API key (programmatic) vs session login (browser)
# ---------------------------------------------------------------------------

def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not API_KEY:
            return jsonify({"error": "server misconfigured: API_KEY not set"}), 500
        if request.headers.get("X-API-Key") != API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


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


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Kalsa Dermaga Landbridge API",
        "status": "running",
        "endpoints": ["/internal/parse", "/internal/allocate", "/internal/queue", "/partner/ecrl/wagon-plan", "/dashboard"],
    })


# ---------------------------------------------------------------------------
# INTERNAL API — Kalsa Dermaga operator platform. Full data, API-key protected.
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
# PARTNER (ECRL) — narrow, read-only, operational data only. API-key protected.
# ---------------------------------------------------------------------------

def _to_partner_view(plan: dict) -> dict:
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
    plan = get_last_plan()
    if not plan:
        return jsonify({"error": "no allocation run yet"}), 404
    return jsonify(_to_partner_view(plan))


# ---------------------------------------------------------------------------
# DASHBOARD — browser UI for human operators. Session-login protected.
# ---------------------------------------------------------------------------

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


@app.route("/dashboard/upload", methods=["POST"])
@login_required
def dashboard_upload():
    file = request.files.get("edi_file")
    if not file or file.filename == "":
        flash("No file selected.")
        return redirect(url_for("dashboard"))
    raw = file.read().decode("utf-8", errors="replace")
    result = parse_interchange(raw)
    containers = [c.as_dict() for c in result.containers]
    if containers:
        save_containers(containers)
    msg = f"Parsed {len(containers)} containers from {file.filename}."
    if result.warnings:
        msg += " Warnings: " + "; ".join(result.warnings)
    flash(msg)
    return redirect(url_for("dashboard"))


@app.route("/dashboard/generate-edi")
@login_required
def dashboard_generate_edi():
    plan = get_last_plan()
    if not plan:
        flash("No allocation plan to generate EDI from yet — run allocation first.")
        return redirect(url_for("dashboard"))
    edi_text = generate_wagon_status_edi(plan)
    return Response(
        edi_text,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=wagon_status.edi"},
    )


# ---------------------------------------------------------------------------
# VESSEL BAY PLAN — view containers by their ship position (from BAPLIE),
# filter by discharge port, and assign an ECRL station to queue them for
# wagon allocation.
# ---------------------------------------------------------------------------

@app.route("/dashboard/vessel")
@login_required
def vessel_bayplan():
    containers = get_containers()

    discharge_ports = sorted({c.get("discharge_port") for c in containers if c.get("discharge_port")})
    port_colors = _port_colors(discharge_ports)
    selected_port = request.args.get("discharge_port", discharge_ports[0] if discharge_ports else "")
    filtered = [c for c in containers if c.get("discharge_port") == selected_port]

    bays = defaultdict(list)
    for c in containers:
        if c.get("bay") is not None:
            bays[c["bay"]].append(c)
    for bay_num in bays:
        bays[bay_num].sort(key=lambda c: c.get("tier") or 0, reverse=True)
    bays = dict(sorted(bays.items()))

    stations = [s for s in ROUTE if not s.get("origin")]

    return render_template(
        "vessel.html",
        bays=bays,
        port_colors=port_colors,
        discharge_ports=discharge_ports,
        selected_port=selected_port,
        filtered=filtered,
        stations=stations,
    )


@app.route("/dashboard/vessel/assign", methods=["POST"])
@login_required
def vessel_assign():
    containers = get_containers()
    by_id = {c["container_id"]: c for c in containers}
    updated = []
    for key, value in request.form.items():
        if key.startswith("station__") and value:
            container_id = key[len("station__"):]
            if container_id in by_id:
                c = by_id[container_id]
                c["destination_station"] = value
                updated.append(c)
    if updated:
        save_containers(updated)
        flash(f"Assigned {len(updated)} containers to ECRL stations — ready for wagon allocation.")
    else:
        flash("No stations were selected.")
    selected_port = request.form.get("discharge_port", "")
    return redirect(url_for("vessel_bayplan", discharge_port=selected_port))


# ---------------------------------------------------------------------------
# BILLING — rate card, job creation, invoice generation. All rates in
# rates.py are placeholders; see that file's header before using for real.
# ---------------------------------------------------------------------------

@app.route("/dashboard/billing")
@login_required
def billing():
    return render_template(
        "billing.html",
        containers=get_containers(),
        jobs=get_jobs(),
        partner_rates=PARTNER_COST_RATES,
        hazmat_cost=HAZMAT_COST_SURCHARGE,
        client_rates=CLIENT_SELL_RATES,
        hazmat_sell=CLIENT_HAZMAT_SURCHARGE,
        currency=CURRENCY,
    )


@app.route("/dashboard/billing/create", methods=["POST"])
@login_required
def billing_create():
    client_name = request.form.get("client_name", "").strip()
    selected_ids = request.form.getlist("container_ids")
    if not client_name or not selected_ids:
        flash("Enter a client name and select at least one container.")
        return redirect(url_for("billing"))
    containers = [c for c in get_containers() if c["container_id"] in selected_ids]
    job_ref = "JOB-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    job = build_job(containers, client_name, job_ref)
    save_job(job)
    # Deliberately no margin/cost figures here -- this message is shown on the
    # very next page, which is the client-facing invoice. Margin stays visible
    # only on the internal Billing page's job list.
    flash(f"Created {job_ref} for {client_name} — {len(containers)} containers.")
    return redirect(url_for("invoice_view", job_ref=job_ref))


@app.route("/dashboard/billing/invoice/<job_ref>")
@login_required
def invoice_view(job_ref):
    job = get_job(job_ref)
    if not job:
        flash("Job not found.")
        return redirect(url_for("billing"))
    return render_template("invoice.html", job=job)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
