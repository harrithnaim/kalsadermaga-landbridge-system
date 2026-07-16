"""
Rate engine — placeholder pricing structure for the landbridge service.

*** ALL NUMBERS BELOW ARE MADE UP PLACEHOLDERS. ***
None of these are real negotiated rates with Kuantan Port, ECRL/MRL, or Port
Klang. They exist so the billing system has something to compute with while
you gather actual tariff sheets from each partner. Replace them before this
touches a real invoice.

Structure follows the common industry pattern discussed: size-based base
rate per leg, plus a flat hazmat surcharge. Currency: MYR.
"""

CURRENCY = "MYR"

# What Kalsa Dermaga pays each partner, per container, by size bucket.
PARTNER_COST_RATES = {
    "kuantan_handling":   {"20": 350.00, "40": 550.00},
    "ecrl_haulage":       {"20": 900.00, "40": 1400.00},
    "portklang_handling": {"20": 380.00, "40": 600.00},
}
HAZMAT_COST_SURCHARGE = {
    "kuantan_handling": 150.00,
    "ecrl_haulage": 300.00,
    "portklang_handling": 150.00,
}

# What Kalsa Dermaga charges the client (shipping line / 3PL) — one bundled
# single-bill price per container. The client never sees the per-leg cost split.
CLIENT_SELL_RATES = {"20": 2200.00, "40": 3400.00}
CLIENT_HAZMAT_SURCHARGE = 700.00


def _size_bucket(size_type: str) -> str:
    """Map an ISO 6346 size/type code (e.g. '22G1', '45G1') to '20' or '40'."""
    if not size_type:
        return "20"
    return "40" if size_type[0] == "4" else "20"


def cost_breakdown(container: dict) -> dict:
    """What this container costs Kalsa Dermaga, broken down by leg."""
    size = _size_bucket(container.get("size_type"))
    hazmat = bool(container.get("hazmat_flag"))
    legs = {}
    for leg, rates in PARTNER_COST_RATES.items():
        amount = rates[size]
        if hazmat:
            amount += HAZMAT_COST_SURCHARGE[leg]
        legs[leg] = round(amount, 2)
    legs["total"] = round(sum(legs.values()), 2)
    return legs


def sell_price(container: dict) -> float:
    """What Kalsa Dermaga charges the client for this container."""
    size = _size_bucket(container.get("size_type"))
    price = CLIENT_SELL_RATES[size]
    if container.get("hazmat_flag"):
        price += CLIENT_HAZMAT_SURCHARGE
    return round(price, 2)


def build_job(containers: list, client_name: str, job_ref: str) -> dict:
    """Bundle a batch of containers into a billable job: line items, total
    cost (internal), total revenue (client-facing), and margin (internal)."""
    line_items = []
    total_cost = 0.0
    total_revenue = 0.0
    for c in containers:
        cost = cost_breakdown(c)
        revenue = sell_price(c)
        total_cost += cost["total"]
        total_revenue += revenue
        line_items.append({
            "container_id": c["container_id"],
            "size_type": c.get("size_type"),
            "hazmat_flag": bool(c.get("hazmat_flag")),
            "cost_breakdown": cost,
            "sell_price": revenue,
        })
    margin = total_revenue - total_cost
    return {
        "job_ref": job_ref,
        "client_name": client_name,
        "currency": CURRENCY,
        "line_items": line_items,
        "total_cost": round(total_cost, 2),
        "total_revenue": round(total_revenue, 2),
        "margin": round(margin, 2),
        "margin_pct": round((margin / total_revenue) * 100, 1) if total_revenue else 0,
    }
