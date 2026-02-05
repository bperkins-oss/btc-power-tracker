#!/usr/bin/env python3
"""Bitcoin Mining Power Tracker - Flask Backend"""

import time
import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# ---------------------------------------------------------------------------
# CONUS Fleet Model
# ---------------------------------------------------------------------------
FLEET_MODEL = [
    {"model": "Antminer S19j Pro",  "efficiency": 30.5, "weight": 0.15},
    {"model": "Antminer S19 XP",    "efficiency": 21.5, "weight": 0.20},
    {"model": "Antminer S19k Pro",   "efficiency": 23.0, "weight": 0.10},
    {"model": "Antminer S21",        "efficiency": 17.5, "weight": 0.15},
    {"model": "Antminer S21 Pro",    "efficiency": 15.0, "weight": 0.05},
    {"model": "Antminer T21",        "efficiency": 19.0, "weight": 0.08},
    {"model": "WhatsMiner M50S",     "efficiency": 26.0, "weight": 0.07},
    {"model": "WhatsMiner M60S",     "efficiency": 18.5, "weight": 0.08},
    {"model": "Legacy (S9/older)",   "efficiency": 75.0, "weight": 0.05},
    {"model": "Other/Canaan",        "efficiency": 22.0, "weight": 0.07},
]

CONUS_SHARE = 0.378  # 37.8% of global hash rate

FLEET_WEIGHTED_EFFICIENCY = sum(
    m["efficiency"] * m["weight"] for m in FLEET_MODEL
)

# ---------------------------------------------------------------------------
# State-Level Mining Distribution (% of CONUS hash rate)
# Based on CBECI, EIA, Foundry USA pool data, and industry reports
# ---------------------------------------------------------------------------
STATE_DISTRIBUTION = {
    "Texas":          0.285,
    "Georgia":        0.105,
    "New York":       0.095,
    "Kentucky":       0.050,
    "Pennsylvania":   0.045,
    "Wyoming":        0.040,
    "Ohio":           0.035,
    "North Carolina": 0.030,
    "Nebraska":       0.025,
    "Tennessee":      0.025,
    "Mississippi":    0.020,
    "Missouri":       0.020,
    "Washington":     0.020,
    "South Carolina": 0.020,
    "Oklahoma":       0.020,
    "North Dakota":   0.015,
    "Montana":        0.015,
    "Indiana":        0.015,
    "Virginia":       0.015,
    "Arkansas":       0.015,
    "Florida":        0.012,
    "Illinois":       0.010,
    "Michigan":       0.008,
    "Colorado":       0.008,
    "Oregon":         0.007,
    "Alabama":        0.007,
    "Louisiana":      0.006,
    "Iowa":           0.005,
    "Kansas":         0.005,
    "Utah":           0.005,
    "Minnesota":      0.004,
    "Nevada":         0.004,
    "Arizona":        0.004,
    "New Mexico":     0.003,
    "Wisconsin":      0.003,
    "West Virginia":  0.003,
    "South Dakota":   0.002,
    "Maine":          0.002,
    "Idaho":          0.002,
    "New Hampshire":  0.002,
    "Maryland":       0.002,
    "Connecticut":    0.001,
    "New Jersey":     0.001,
    "Massachusetts":  0.001,
    "Delaware":       0.001,
    "Vermont":        0.001,
    "Rhode Island":   0.0005,
    "California":     0.0005,
}

# ---------------------------------------------------------------------------
# Simple TTL Cache
# ---------------------------------------------------------------------------
_cache = {}
CACHE_TTL = 60  # seconds


def cached_get(key, fetch_fn):
    """Return cached value if fresh, otherwise call fetch_fn and cache it."""
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["value"]
    value = fetch_fn()
    _cache[key] = {"value": value, "ts": time.time()}
    return value


# ---------------------------------------------------------------------------
# API Fetchers
# ---------------------------------------------------------------------------
MEMPOOL_HASHRATE_URL = "https://mempool.space/api/v1/mining/hashrate/2w"
BLOCKCHAIN_INFO_URL = (
    "https://api.blockchain.info/charts/hash-rate?timespan=14days&format=json"
)


def fetch_hashrate_mempool():
    """Fetch current + recent hash rates from mempool.space.
    Returns dict with currentHashrate (EH/s) and history list.
    """
    resp = requests.get(MEMPOOL_HASHRATE_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    current_hr = data.get("currentHashrate", 0)  # H/s
    current_ehs = current_hr / 1e18

    history = []
    for point in data.get("hashrates", []):
        ts = point.get("timestamp", 0)
        val = point.get("avgHashrate", 0) / 1e18  # -> EH/s
        history.append({"timestamp": ts, "hashrate_ehs": round(val, 2)})

    return {
        "source": "mempool.space",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def fetch_hashrate_blockchain_info():
    """Fallback: fetch hash rate from blockchain.info.
    Returns dict with currentHashrate (EH/s) and history list.
    """
    resp = requests.get(BLOCKCHAIN_INFO_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    values = data.get("values", [])
    history = []
    for point in values:
        ts = point.get("x", 0)
        val = point.get("y", 0) / 1e6  # blockchain.info returns TH/s -> EH/s
        history.append({"timestamp": ts, "hashrate_ehs": round(val, 2)})

    current_ehs = history[-1]["hashrate_ehs"] if history else 0
    return {
        "source": "blockchain.info",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def get_hashrate_data():
    """Try mempool.space first, fall back to blockchain.info."""
    try:
        return fetch_hashrate_mempool()
    except Exception:
        pass
    try:
        return fetch_hashrate_blockchain_info()
    except Exception:
        return {
            "source": "unavailable",
            "hashrate_ehs": 0,
            "history": [],
        }


def compute_power(hashrate_ehs):
    """Compute CONUS and global estimated power in GW."""
    hashrate_ths = hashrate_ehs * 1e6  # EH/s -> TH/s
    conus_watts = hashrate_ths * CONUS_SHARE * FLEET_WEIGHTED_EFFICIENCY
    conus_gw = conus_watts / 1e9

    global_watts = hashrate_ths * FLEET_WEIGHTED_EFFICIENCY
    global_gw = global_watts / 1e9
    return round(conus_gw, 2), round(global_gw, 2)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/hashrate")
def api_hashrate():
    data = cached_get("hashrate", get_hashrate_data)
    conus_gw, global_gw = compute_power(data["hashrate_ehs"])
    return jsonify({
        "hashrate_ehs": data["hashrate_ehs"],
        "source": data["source"],
        "conus_power_gw": conus_gw,
        "global_power_gw": global_gw,
        "conus_share": CONUS_SHARE,
        "fleet_efficiency_jth": round(FLEET_WEIGHTED_EFFICIENCY, 2),
    })


@app.route("/api/history")
def api_history():
    data = cached_get("hashrate", get_hashrate_data)
    history = []
    for point in data["history"]:
        conus_gw, _ = compute_power(point["hashrate_ehs"])
        history.append({**point, "conus_power_gw": conus_gw})
    return jsonify({
        "source": data["source"],
        "history": history,
    })


@app.route("/api/fleet")
def api_fleet():
    return jsonify({
        "fleet": FLEET_MODEL,
        "weighted_efficiency_jth": round(FLEET_WEIGHTED_EFFICIENCY, 2),
        "conus_share": CONUS_SHARE,
    })


@app.route("/api/states")
def api_states():
    data = cached_get("hashrate", get_hashrate_data)
    conus_gw, _ = compute_power(data["hashrate_ehs"])
    states = []
    for name, share in STATE_DISTRIBUTION.items():
        states.append({
            "state": name,
            "share": share,
            "power_mw": round(conus_gw * 1000 * share, 1),
        })
    states.sort(key=lambda s: s["share"], reverse=True)
    return jsonify({
        "conus_power_gw": conus_gw,
        "states": states,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Fleet weighted efficiency: {FLEET_WEIGHTED_EFFICIENCY:.2f} J/TH")
    print(f"CONUS share: {CONUS_SHARE * 100:.1f}%")
    app.run(host="0.0.0.0", port=5000, debug=True)
