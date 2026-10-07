"""The database, as a sense: Atlas metrics from Bronto's metrics API.

Atlas pushes its cluster metrics to Bronto through the OTel Metrics Sink.
Bronto's MCP server reads logs and traces but not metrics, so these two
tools call the REST API directly (docs.bronto.io/api-reference/timeseries),
with the same read-only key the MCP server uses.

Answers are kept small on purpose: a few dozen points and a summary, not the
raw series, so a 2-hour window doesn't flood the model's context.
"""

import os
from datetime import datetime, timezone

import httpx2
from strands import tool

API = os.environ.get("BRONTO_API_URL", "https://api.eu.bronto.io")
PREFIX = os.environ.get("ATLAS_METRIC_PREFIX", "mongodb")


def _headers() -> dict:
    return {"X-BRONTO-API-KEY": os.environ["BRONTO_API_KEY"]}


@tool
def list_atlas_metrics(contains: str = "") -> list[dict]:
    """List the MongoDB Atlas metrics available in Bronto: name, type, unit, description.

    Call this first to find the exact metric names to query.

    Args:
        contains: optional text the metric name must contain, e.g. "query", "opcounter", "latency", "cpu".
    """
    r = httpx2.get(f"{API}/metrics", headers=_headers(), timeout=30)
    r.raise_for_status()
    return [
        {k: m.get(k) for k in ("metric_name", "type", "unit", "description") if m.get(k)}
        for m in r.json().get("metrics", [])
        if m["metric_name"].startswith(PREFIX) and contains.lower() in m["metric_name"].lower()
    ]


@tool
def query_atlas_metrics(
    metric: str,
    time_range: str = "Last 60 minutes",
    aggregation: str = "avg",
    group_by: str = "",
    where: str = "",
    points: int = 30,
) -> dict:
    """Get one Atlas metric over time, to compare a quiet baseline with the incident window.

    Counters that only ever grow (opcounters, documents scanned and returned, network bytes)
    come back as their increase per time bucket, which is what you want to compare.

    Args:
        metric: exact metric name from list_atlas_metrics.
        time_range: natural language, e.g. "Last 60 minutes", "Last 3 hours".
        aggregation: avg, max, min, sum, p95 or p99 (ignored for counters).
        group_by: optional attribute to split by, e.g. "mongodb.process.host".
        where: optional filter on metric attributes, e.g. "\"mongodb.replica_set.state\" = 'primary'".
        points: how many time buckets to return (max 120; counters at most 12).
    """
    counter = metric.startswith(COUNTERS)
    if counter:  # MAX - MIN within each bucket: the counter's increase. Needs 2+ samples a bucket.
        queries = [_q("hi", metric, "max", where, group_by), _q("lo", metric, "min", where, group_by)]
        formulas = [{"name": "m", "expression": "hi - lo"}]
        points = min(points, 12)
    else:
        queries, formulas = [_q("m", metric, aggregation, where, group_by)], []
    result = _search(queries, formulas, time_range, points)
    if "error" in result:
        return result
    out = {"metric": metric, "time_range": time_range,
           "aggregation": "increase per bucket (cumulative counter)" if counter else aggregation}
    m = result.get("m", {})
    if m.get("series"):
        out["series"] = _compact(m["series"])
    if m.get("groups_series"):
        out["groups"] = [  # "name" is the value of the attribute grouped by
            {group_by: g.get("name") or "(not set)", "series": _compact(g.get("timeseries", []))}
            for g in m["groups_series"][:10]
        ]
    return out


@tool
def atlas_query_targeting(time_range: str = "Last 2 hours", points: int = 12) -> dict:
    """Atlas's query targeting on the primary: documents scanned per document returned, over time.

    Near 1 means queries use indexes well. Hundreds or thousands mean queries scan far more
    documents than they return: usually a query no index covers (a COLLSCAN).

    Args:
        time_range: natural language, e.g. "Last 2 hours".
        points: how many time buckets to return (at most 12).
    """
    queries = [_q(n, f"{SS}metrics.{m}", fn, PRIMARY) for n, m, fn in (
        ("sx", "query_executor.scanned_objects", "max"), ("sn", "query_executor.scanned_objects", "min"),
        ("rx", "document.returned", "max"), ("rn", "document.returned", "min"))]
    result = _search(queries, [{"name": "m", "expression": "(sx - sn) / (rx - rn)"}], time_range, min(points, 12))
    if "error" in result:
        return result
    return {"metric": "documents scanned per document returned (primary)", "time_range": time_range,
            "series": _compact(result.get("m", {}).get("series", []))}


SS = "mongodb.server_status."
PRIMARY = "\"mongodb.replica_set.state\" = 'primary'"
COUNTERS = tuple(SS + p for p in ("opcounters", "metrics.document", "metrics.query_executor",
                                  "metrics.operation", "network.", "asserts"))
FN = {"avg": "AVERAGE", "max": "MAX", "min": "MIN", "sum": "SUM", "p95": "P95", "p99": "P99"}


def _q(name: str, metric: str, aggregation: str, where: str = "", group_by: str = "") -> dict:
    fn = FN.get(aggregation, "AVERAGE")
    return {"name": name, "select": [f"{fn}(value)"], "from_expr": f"metric_name = '{metric}'", "where": where,
            "groups": [group_by] if group_by else [], "aggregation": [{"time": fn.lower() if fn != "AVERAGE" else "average"}]}


def _search(queries: list[dict], formulas: list[dict], time_range: str, points: int) -> dict:
    body = {"time_range": {"natural": time_range}, "num_of_slices": max(1, min(points, 120)),
            "queries": queries, "formulas": formulas}
    r = httpx2.post(f"{API}/timeseries/search", headers=_headers(), json=body, timeout=60)
    if r.status_code >= 400:
        return {"error": r.status_code, "details": r.text[:500]}
    return r.json()


def _compact(series: list[dict]) -> dict:
    pts = [  # Bronto sends numbers as strings
        (datetime.fromtimestamp(int(s["@timestamp"]) / 1000, timezone.utc).strftime("%d %b %H:%M"), float(s["value"]))
        for s in series if s.get("value") is not None
    ]
    values = [v for _, v in pts]
    if not values:
        return {"points": [], "note": "no data in this window"}
    return {
        "points": [f"{t} {v:.4g}" for t, v in pts],
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "first": round(values[0], 4),
        "last": round(values[-1], 4),
    }
