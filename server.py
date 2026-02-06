#!/usr/bin/env python3
"""Bitcoin Mining Power Tracker - Flask Backend
Enhanced with multi-source redundancy and improved reliability.
"""

import os
import time
import random
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# API Configuration
# Set LUXOR_API_KEY env var when you have it
# ---------------------------------------------------------------------------
LUXOR_API_KEY = os.environ.get("LUXOR_API_KEY", "")
LUXOR_API_URL = "https://api.hashrateindex.com/graphql"

# ---------------------------------------------------------------------------
# CONUS Fleet Model
# ---------------------------------------------------------------------------
FLEET_MODEL = [
    {"model": "Antminer S19j Pro",  "efficiency": 30.5, "weight": 0.15},
    {"model": "Antminer S19 XP",    "efficiency": 21.5, "weight": 0.20},
    {"model": "Antminer S19k Pro",  "efficiency": 23.0, "weight": 0.10},
    {"model": "Antminer S21",       "efficiency": 17.5, "weight": 0.15},
    {"model": "Antminer S21 Pro",   "efficiency": 15.0, "weight": 0.05},
    {"model": "Antminer T21",       "efficiency": 19.0, "weight": 0.08},
    {"model": "WhatsMiner M50S",    "efficiency": 26.0, "weight": 0.07},
    {"model": "WhatsMiner M60S",    "efficiency": 18.5, "weight": 0.08},
    {"model": "Legacy (S9/older)",  "efficiency": 75.0, "weight": 0.05},
    {"model": "Other/Canaan",       "efficiency": 22.0, "weight": 0.07},
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
# Enhanced TTL Cache with Stale-While-Revalidate
# ---------------------------------------------------------------------------
_cache = {}
CACHE_TTL = 60          # Fresh for 60 seconds
CACHE_STALE_TTL = 300   # Serve stale for up to 5 minutes if fetch fails


def cached_get(key, fetch_fn):
    """Return cached value if fresh, otherwise try fetch.
    If fetch fails, return stale data if available."""
    entry = _cache.get(key)
    now = time.time()
    
    # Return fresh cache
    if entry and now - entry["ts"] < CACHE_TTL:
        return entry["value"]
    
    # Try to fetch new data
    try:
        value = fetch_fn()
        _cache[key] = {"value": value, "ts": now}
        return value
    except Exception as e:
        # If fetch fails, return stale data if within stale TTL
        if entry and now - entry["ts"] < CACHE_STALE_TTL:
            entry["value"]["stale"] = True
            return entry["value"]
        raise e


# ---------------------------------------------------------------------------
# Retry Logic with Exponential Backoff
# ---------------------------------------------------------------------------
def fetch_with_retry(fetch_fn, max_retries=3, base_delay=0.5):
    """Retry a fetch function with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return fetch_fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
    raise last_error


# ---------------------------------------------------------------------------
# API Fetchers - Multiple Sources for Redundancy
# ---------------------------------------------------------------------------

def _mempool_period(days):
    """Map a day count to the smallest mempool.space period that covers it."""
    if days <= 3:
        return "3d"
    if days <= 7:
        return "1w"
    if days <= 14:
        return "2w"
    if days <= 30:
        return "1m"
    if days <= 90:
        return "3m"
    if days <= 180:
        return "6m"
    if days <= 365:
        return "1y"
    if days <= 730:
        return "2y"
    if days <= 1095:
        return "3y"
    return "all"


def fetch_hashrate_luxor(days=20):
    """Fetch hashrate from Luxor Hashrate Index API (paid).
    Returns dict with currentHashrate (EH/s) and history list.
    """
    if not LUXOR_API_KEY:
        raise ValueError("LUXOR_API_KEY not configured")
    
    # GraphQL query for network hashrate
    query = """
    query GetNetworkHashrate($inputInterval: ChartsInterval!) {
        getNetworkHashrate(inputInterval: $inputInterval) {
            nodes {
                timestamp
                networkHashrate7D
            }
        }
    }
    """
    
    # Map days to Luxor interval
    if days <= 7:
        interval = "_1_WEEK"
    elif days <= 30:
        interval = "_1_MONTH"
    elif days <= 90:
        interval = "_3_MONTHS"
    else:
        interval = "_1_YEAR"
    
    headers = {
        "Content-Type": "application/json",
        "x-hi-api-key": LUXOR_API_KEY,
    }
    
    payload = {
        "query": query,
        "variables": {"inputInterval": interval}
    }
    
    resp = requests.post(LUXOR_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    
    nodes = data.get("data", {}).get("getNetworkHashrate", {}).get("nodes", [])
    if not nodes:
        raise ValueError("No hashrate data from Luxor")
    
    # Convert to our format
    cutoff = time.time() - (days * 24 * 3600)
    history = []
    for node in nodes:
        ts = node.get("timestamp", 0)
        # Luxor returns EH/s directly
        val = node.get("networkHashrate7D", 0)
        if ts >= cutoff and val > 0:
            history.append({"timestamp": int(ts), "hashrate_ehs": round(val, 2)})
    
    current_ehs = history[-1]["hashrate_ehs"] if history else 0
    
    return {
        "source": "luxor",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def fetch_hashrate_mempool(days=20):
    """Fetch current + recent hash rates from mempool.space.
    Returns dict with currentHashrate (EH/s) and history list.
    """
    period = _mempool_period(days)
    url = f"https://mempool.space/api/v1/mining/hashrate/{period}"
    
    def _fetch():
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    
    data = fetch_with_retry(_fetch)

    current_hr = data.get("currentHashrate", 0)  # H/s
    current_ehs = current_hr / 1e18

    cutoff = time.time() - (days * 24 * 3600)
    history = []
    for point in data.get("hashrates", []):
        ts = point.get("timestamp", 0)
        val = point.get("avgHashrate", 0) / 1e18  # -> EH/s
        if ts >= cutoff and val > 0:
            history.append({"timestamp": ts, "hashrate_ehs": round(val, 2)})

    return {
        "source": "mempool.space",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def fetch_hashrate_blockchain_info(days=20):
    """Fetch hash rate from blockchain.info.
    Returns dict with currentHashrate (EH/s) and history list.
    """
    url = f"https://api.blockchain.info/charts/hash-rate?timespan={days}days&format=json"
    
    def _fetch():
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    
    data = fetch_with_retry(_fetch)

    cutoff = time.time() - (days * 24 * 3600)
    values = data.get("values", [])
    history = []
    for point in values:
        ts = point.get("x", 0)
        val = point.get("y", 0) / 1e6  # blockchain.info returns TH/s -> EH/s
        if ts >= cutoff and val > 0:
            history.append({"timestamp": ts, "hashrate_ehs": round(val, 2)})

    current_ehs = history[-1]["hashrate_ehs"] if history else 0
    return {
        "source": "blockchain.info",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def fetch_hashrate_blockchair(days=20):
    """Fetch hash rate from Blockchair (third backup source).
    Returns dict with currentHashrate (EH/s) and history list.
    """
    # Blockchair stats endpoint
    url = "https://api.blockchair.com/bitcoin/stats"
    
    def _fetch():
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    
    data = fetch_with_retry(_fetch)
    
    stats = data.get("data", {})
    # Blockchair returns hashrate_24h in H/s
    hashrate_hs = stats.get("hashrate_24h", 0)
    current_ehs = hashrate_hs / 1e18
    
    # Blockchair doesn't provide historical in this endpoint, so return minimal history
    history = [{
        "timestamp": int(time.time()),
        "hashrate_ehs": round(current_ehs, 2)
    }]
    
    return {
        "source": "blockchair",
        "hashrate_ehs": round(current_ehs, 2),
        "history": history,
    }


def get_hashrate_data(days=20):
    """Try multiple sources in priority order for maximum reliability.
    Priority: Luxor (paid) > mempool.space > blockchain.info > blockchair
    """
    sources = []
    
    # Add Luxor first if configured
    if LUXOR_API_KEY:
        sources.append(("luxor", lambda: fetch_hashrate_luxor(days)))
    
    # Add free sources
    sources.extend([
        ("mempool.space", lambda: fetch_hashrate_mempool(days)),
        ("blockchain.info", lambda: fetch_hashrate_blockchain_info(days)),
        ("blockchair", lambda: fetch_hashrate_blockchair(days)),
    ])
    
    errors = []
    for name, fetch_fn in sources:
        try:
            result = fetch_fn()
            if result.get("hashrate_ehs", 0) > 0:
                return result
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    
    # All sources failed
    return {
        "source": "unavailable",
        "hashrate_ehs": 0,
        "history": [],
        "errors": errors,
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
    days = request.args.get("days", 20, type=int)
    days = max(0, min(days, 1095))  # clamp 0-1095
    cache_key = f"hashrate_{days}"
    data = cached_get(cache_key, lambda: get_hashrate_data(days))
    conus_gw, global_gw = compute_power(data["hashrate_ehs"])
    
    response = {
        "hashrate_ehs": data["hashrate_ehs"],
        "source": data["source"],
        "conus_power_gw": conus_gw,
        "global_power_gw": global_gw,
        "conus_share": CONUS_SHARE,
        "fleet_efficiency_jth": round(FLEET_WEIGHTED_EFFICIENCY, 2),
    }
    
    # Include stale indicator if present
    if data.get("stale"):
        response["stale"] = True
    
    # Include errors if all sources failed
    if data.get("errors"):
        response["errors"] = data["errors"]
    
    return jsonify(response)


@app.route("/api/history")
def api_history():
    days = request.args.get("days", 20, type=int)
    days = max(0, min(days, 1095))  # clamp 0-1095
    cache_key = f"hashrate_{days}"
    data = cached_get(cache_key, lambda: get_hashrate_data(days))
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
    days = request.args.get("days", 20, type=int)
    cache_key = f"hashrate_{days}"
    data = cached_get(cache_key, lambda: get_hashrate_data(days))
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
        "source": data["source"],
        "conus_power_gw": conus_gw,
        "states": states,
    })


@app.route("/api/health")
def api_health():
    """Health check endpoint showing data source status."""
    status = {"healthy": True, "sources": {}}
    
    # Check each source
    sources_to_check = [
        ("luxor", LUXOR_API_KEY != "", "Configured" if LUXOR_API_KEY else "Not configured"),
        ("mempool.space", True, None),
        ("blockchain.info", True, None),
        ("blockchair", True, None),
    ]
    
    for name, enabled, note in sources_to_check:
        status["sources"][name] = {
            "enabled": enabled,
            "note": note,
        }
    
    # Try to get current data to see which source is working
    try:
        data = get_hashrate_data(1)
        status["active_source"] = data.get("source", "unknown")
        status["current_hashrate_ehs"] = data.get("hashrate_ehs", 0)
    except Exception as e:
        status["healthy"] = False
        status["error"] = str(e)
    
    return jsonify(status)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Fleet weighted efficiency: {FLEET_WEIGHTED_EFFICIENCY:.2f} J/TH")
    print(f"CONUS share: {CONUS_SHARE * 100:.1f}%")
    print(f"Luxor API: {'Configured' if LUXOR_API_KEY else 'Not configured (using free sources)'}")
    app.run(host="0.0.0.0", port=5000, debug=True)
