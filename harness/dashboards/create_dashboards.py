#!/usr/bin/env python3
"""Create the lab's two Bronto dashboards in the shared demo org.

  "Atlas — storefront (M10)"        Atlas's own Metrics-tab charts, from the OTel Metrics Sink
  "Storefront × Atlas — checkout"   the demo flow: slow checkout → the orders query → Atlas's side

    BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --validate  # dry run: every query, read-only
    BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py             # create
    BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --check     # each widget's latest values
    BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --relayout  # put the widgets back in place
    BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --delete    # remove what it created

--validate only reads, so the public read-only key is enough. The others need dashboard write access.

Atlas sends serverStatus counters (opcounters, documents scanned and returned, network bytes) as
ever-growing gauges, and Bronto has no derivative function. So a counter is two queries, MAX and MIN
of the same series per time bucket, and a formula takes the difference: the increase within the
bucket. It slightly under-counts (the step between buckets is lost), which cancels out in a ratio
like query targeting. Counters are read on the primary only. Atlas sends a point a minute,
so view them with a rollup of 2 minutes or more: a 1-minute bucket holds one sample and reads 0.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("BRONTO_API_URL") or f"https://api.{os.environ.get('BRONTO_REGION', 'eu').strip().lower() or 'eu'}.bronto.io"
STATE = Path(os.environ.get("DASHBOARD_STATE", Path(__file__).with_name("state.json")))

PRIMARY = "\"mongodb.replica_set.state\" = 'primary'"
HOST = ["mongodb.process.host"]
LOGS = "\"collection\" = 'mongodb-dublin' AND \"dataset\" = 'atlas-mongod'"
SLOW = "\"$msg\" = 'Slow query'"
SERVER = "\"$span.kind\" = 'SPAN_KIND_SERVER'"
CHECKOUT_REQ = SERVER + " AND \"$span.name\" = 'POST /checkout'"
MONGO = "\"$db.system\" = 'mongodb'"
ERROR = "\"$span.status_code\" = 'STATUS_CODE_ERROR'"

NS_TO_MS = {"type": "time", "input": "nanoseconds", "output": "milliseconds"}
US = {"type": "time", "input": "microseconds", "output": "auto"}
MS = {"type": "time", "input": "milliseconds", "output": "auto"}
BYTES = {"type": "binary_data_size", "input": "bytes", "output": "auto"}


def traces(service: str) -> str:
    return f"\"collection\" = '.traces' AND \"dataset\" = '{service}'"


def q(name, select, source, where="", groups=None, agg="count", reduce_to="sum", unit=None) -> dict:
    query = {"name": name, "select": [select], "from_expr": source, "where": where,
             "groups": groups or [], "aggregation": [{"time": agg, "reduce_to": reduce_to}]}
    if unit:
        query["unit_config"] = unit
    return query


def metric(name, metric_name, agg="avg", where="", groups=None, unit=None) -> dict:
    fn = {"avg": "AVERAGE", "max": "MAX", "min": "MIN", "sum": "SUM"}[agg]
    return q(name, f"{fn}(value)", f"metric_name = '{metric_name}'", where, groups, agg, "avg", unit)


def counter(qid, metric_name, where=PRIMARY) -> tuple[list[dict], str]:
    """The increase of a cumulative gauge within each bucket: (queries, formula expression).
    Query ids stay short: a formula expression is capped at 100 characters."""
    return ([metric(f"{qid}x", metric_name, "max", where), metric(f"{qid}n", metric_name, "min", where)],
            f"({qid}x - {qid}n)")


def counters(*pairs, where=PRIMARY) -> tuple[list[dict], list[dict]]:
    """Up to three counters on one chart (a definition takes at most six queries), one formula series each."""
    queries, formulas = [], []
    for i, (label, metric_name) in enumerate(pairs):
        qs, expr = counter(f"c{i}", metric_name, where)
        queries += qs
        formulas.append({"name": label, "expression": expr})
    return queries, formulas


SS = "mongodb.server_status."
_scanned, _scanned_e = counter("s", SS + "metrics.query_executor.scanned_objects")
_keys, _keys_e = counter("k", SS + "metrics.query_executor.scanned")
_returned, _returned_e = counter("r", SS + "metrics.document.returned")
# Atlas's Query Targeting: documents (and index keys) scanned per document returned.
QT = (_scanned + _returned, [{"name": "docs_scanned_per_returned", "expression": f"{_scanned_e} / {_returned_e}"}])
QT_BOTH = (_scanned + _keys + _returned,
           QT[1] + [{"name": "keys_scanned_per_returned", "expression": f"{_keys_e} / {_returned_e}"}])
LAT = "mongodb.derived.server_status.op_latencies."
CPU = "mongodb.hardware.system.cpu.normalized_"  # hardware metrics carry no host or replica-set state


def W(title, kind, desc, queries, formulas=(), w=1 / 3, h=7.0) -> dict:
    return {"title": title, "kind": kind, "desc": desc, "queries": queries if isinstance(queries, list) else [queries],
            "formulas": list(formulas), "w": w, "h": h}


def T(title, desc, w=1 / 4):  # a score tile
    def tile(queries, formulas=()):
        return W(title, "score", desc, queries, formulas, w, 3.5)
    return tile


DASHBOARDS = {
    "atlas": {
        "name": "Atlas — storefront (M10)",
        "rows": [
            [T("Connections", "Current client connections, all three hosts.")(
                metric("conns", SS + "connections.current", "max")),
             T("Query targeting", "Documents scanned per document returned, primary. Healthy: tens. Bad: thousands.")(*QT),
             T("Read latency P95", "Atlas's own read-latency percentile.")(
                metric("reads_p95", LAT + "reads.micros.p95", "max", PRIMARY, unit=US)),
             T("System CPU %", "CPU (user), normalized to the instance's cores. Highest of the three hosts.")(
                metric("cpu", CPU + "user_percent", "max"))],

            [W("Opcounters: reads", "line", "Operations per bucket on the primary (Atlas: Opcounters). "
               "Aggregations, counts included, are commands.",
               *counters(("query", SS + "opcounters.query"), ("command", SS + "opcounters.command"),
                         ("getmore", SS + "opcounters.getmore"))),
             W("Opcounters: writes", "line", "Operations per bucket on the primary (Atlas: Opcounters).",
               *counters(("insert", SS + "opcounters.insert"), ("update", SS + "opcounters.update"),
                         ("delete", SS + "opcounters.delete"))),
             W("Query targeting", "line",
               "Atlas: Query Targeting. Documents and index keys scanned per document returned. "
               "A jump means a query stopped using an index.",
               *QT_BOTH)],

            [W("Operation execution time", "line", "P95 latency of reads, writes and commands (Atlas: Op Execution Time).",
               [metric("reads", LAT + "reads.micros.p95", "max", PRIMARY, unit=US),
                metric("writes", LAT + "writes.micros.p95", "max", PRIMARY, unit=US),
                metric("commands", LAT + "commands.micros.p95", "max", PRIMARY, unit=US)]),
             W("Connections by host", "line", "Atlas: Connections.",
               metric("conns", SS + "connections.current", "max", groups=HOST)),
             W("Normalized system CPU", "line", "Atlas: Normalized System CPU, user and kernel. Highest of the three hosts.",
               [metric("user", CPU + "user_percent", "max"),
                metric("kernel", CPU + "kernel_percent", "max")])],

            [W("Memory", "line", "Resident memory (MB) and the WiredTiger cache, primary.",
               [metric("resident_mb", SS + "mem.resident", "max", PRIMARY),
                metric("cache", SS + "wired_tiger.cache.bytes_currently_in_the_cache", "max", PRIMARY, unit=BYTES),
                metric("cache_max", SS + "wired_tiger.cache.maximum_bytes_configured", "max", PRIMARY, unit=BYTES)]),
             W("Disk IOPS", "line", "Atlas: Disk IOPS (max over each sample).",
               metric("iops", "mongodb.hardware.disk.max_total_iops", "max")),
             W("Disk space used %", "line", "Atlas: Disk Space Percent Used.",
               metric("disk_used", "mongodb.hardware.disk.max_disk_percent_used", "max"))],

            [W("Network", "line", "Bytes in and out of mongod per bucket, primary (Atlas: Network).",
               *counters(("bytes_in", SS + "network.bytes_in"), ("bytes_out", SS + "network.bytes_out"))),
             W("Replication lag", "line", "Secondaries behind the primary, ms (Atlas: Replication Lag).",
               metric("lag", "mongodb.derived.replstatus.lag_milliseconds", "max", groups=HOST, unit=MS)),
             W("Queues", "line", "Operations waiting for a lock (Atlas: Queues).",
               [metric("readers", SS + "global_lock.current_queue.readers", "max", PRIMARY),
                metric("writers", SS + "global_lock.current_queue.writers", "max", PRIMARY)])],

            [W("Documents", "line", "Documents returned, inserted and updated per bucket, primary (Atlas: Document Metrics).",
               *counters(("returned", SS + "metrics.document.returned"), ("inserted", SS + "metrics.document.inserted"),
                         ("updated", SS + "metrics.document.updated")), w=1 / 2),
             W("Scan and order", "line", "Queries that sorted in memory because no index gave the order (Atlas: Scan and Order).",
               *counters(("scan_and_order", SS + "metrics.operation.scan_and_order")), w=1 / 2)],
        ],
    },
    "checkout": {
        "name": "Storefront × Atlas — checkout",
        "rows": [
            [W("Checkout requests", "line", "POST /checkout on shop-checkout, per bucket.",
               q("requests", "*", traces("shop-checkout"), CHECKOUT_REQ)),
             W("Checkout latency", "line", "POST /checkout duration, P50 and P95.",
               [q("p50", "$span.duration_nano", traces("shop-checkout"), CHECKOUT_REQ, agg="p50", reduce_to="max", unit=NS_TO_MS),
                q("p95", "$span.duration_nano", traces("shop-checkout"), CHECKOUT_REQ, agg="p95", reduce_to="max", unit=NS_TO_MS)]),
             W("Failed requests at the web tier", "bar", "shop-web server spans with an error: checkouts that hit the client timeout.",
               q("errors", "*", traces("shop-web"), SERVER + " AND " + ERROR, ["$span.name"]))],

            [W("Release running", "bar", "shop-checkout requests by service.version: the deploy, as a step.",
               q("by_version", "*", traces("shop-checkout"), SERVER, ["$service.version"])),
             W("MongoDB calls from checkout, P95", "line",
               "Database client spans under shop-checkout, by operation. The slow one is the request's time.",
               q("db_p95", "$span.duration_nano", traces("shop-checkout"), MONGO, ["$span.name"],
                 agg="p95", reduce_to="max", unit=NS_TO_MS)),
             W("MongoDB calls by collection", "top-list", "Time spent in the database from checkout, per collection.",
               q("db_time", "$span.duration_nano", traces("shop-checkout"), MONGO, ["\"$db.mongodb.collection\""],
                 agg="sum", unit=NS_TO_MS))],

            [W("Atlas: query targeting", "line",
               "Documents scanned per document returned, primary. The same minutes as the checkout latency above.", *QT),
             W("Atlas: read latency P95", "line", "From the OTel Metrics Sink.",
               metric("reads_p95", LAT + "reads.micros.p95", "max", PRIMARY, unit=US)),
             W("Atlas: system CPU %", "line", "CPU (user), normalized. Highest of the three hosts.",
               metric("cpu", CPU + "user_percent", "max"))],

            [W("Slow queries", "bar", "Atlas mongod log lines with msg = Slow query, by namespace.",
               q("slow", "*", LOGS, SLOW, ["\"$attr.ns\""])),
             W("Slow queries by plan", "pie", "COLLSCAN means no index was used.",
               q("plans", "*", LOGS, SLOW, ["\"$attr.planSummary\""])),
             W("Documents examined (max)", "top-list", "The largest docsExamined per namespace in a slow query.",
               q("examined", "\"$attr.docsExamined\"", LOGS, SLOW, ["\"$attr.ns\""], agg="max", reduce_to="max"))],
        ],
    },
}


class API:
    def __init__(self, key: str):
        self.key = key

    def __call__(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        req = urllib.request.Request(
            BASE_URL + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-BRONTO-API-KEY": self.key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode()
                return r.status, json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, raw


def need(status, expected, what, resp):
    if status not in (expected if isinstance(expected, tuple) else (expected,)):
        raise SystemExit(f"{what}: HTTP {status}: {resp}")
    return resp


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def layout_for(d: dict, widget_ids: list[str]) -> list[dict]:
    """x and w are fractions of the width, y and h are rows. The UI snaps x and w to a 12-column grid by
    rounding down, so 0.3333 renders as a quarter: round up at 8 places (1/3 -> 0.33333334, as the UI saves it)."""
    ids, out, y = iter(widget_ids), [], 0.0
    for row in d["rows"]:
        x, row_h = 0.0, 0.0
        for w in row:
            out.append({"id": next(ids), "x": math.ceil(x * 1e8) / 1e8, "y": y, "w": math.ceil(w["w"] * 1e8) / 1e8, "h": w["h"]})
            x += w["w"]
            row_h = max(row_h, w["h"])
        y += row_h
    return out


def relayout(api: API) -> None:
    for key, entry in load().items():
        status, resp = api("PATCH", f"/dashboards/{entry['dashboard']}",
                           {"layout": {"widget_layouts": layout_for(DASHBOARDS[key], entry["widgets"])}})
        print(key, status if status in (200, 204) else f"HTTP {status}: {resp}")


def widgets():
    for key, d in DASHBOARDS.items():
        for row in d["rows"]:
            for w in row:
                yield key, w


def validate(api: API) -> None:
    """Run every widget's queries over the last 3 hours, read-only, and report what comes back."""
    bad = 0
    for key, w in widgets():
        body = {"time_range": {"natural": "Last 3 hours"}, "num_of_slices": 12,
                "queries": w["queries"], "formulas": w["formulas"]}
        status, resp = api("POST", "/timeseries/search", body)
        if status != 200:
            bad += 1
            print(f"BAD  {key:8} {w['title']:34} HTTP {status} {str(resp)[:200]}")
            continue
        parts = []
        for name in [f["name"] for f in w["formulas"]] or [x["name"] for x in w["queries"]]:
            r = resp.get(name, {})
            pts = [float(s["value"]) for s in r.get("series", []) if s.get("value") is not None]
            groups = r.get("groups_series") or []
            if groups:
                parts.append(f"{name}: {len(groups)} groups ({', '.join(str(g.get('name')) for g in groups[:4])})")
            elif pts:
                parts.append(f"{name}: {min(pts):.4g}..{max(pts):.4g}")
            else:
                parts.append(f"{name}: EMPTY")
        empty = all(p.endswith("EMPTY") for p in parts)
        bad += empty
        print(f"{'BAD ' if empty else 'ok  '} {key:8} {w['title']:34} {'; '.join(parts)[:180]}")
    print(f"\n{bad} widget(s) with errors or no data")


def create(api: API) -> None:
    status, who = api("GET", "/customer")
    need(status, 200, "identify account", who)
    print(f"org: {who.get('customer_name')}")
    state = load()
    host = BASE_URL.replace("api.", "app.")
    for key, d in DASHBOARDS.items():
        if key in state:
            print(f"{d['name']}: already created ({state[key]['dashboard']}); --delete first to rebuild")
            continue
        entry = state[key] = {"metrics": [], "widgets": [], "dashboard": None}
        try:
            for row in d["rows"]:
                for w in row:
                    status, m = api("POST", "/metrics/definitions", {
                        "name": f"{d['name']} — {w['title']}", "description": w["desc"],
                        "queries": w["queries"], "formulas": w["formulas"]})
                    need(status, 201, f"metric {w['title']}", m)
                    entry["metrics"].append(m["id"])
                    status, wid = api("POST", "/widgets", {"name": w["title"], "description": w["desc"],
                                                           "type": w["kind"], "metric_ids": [m["id"]]})
                    need(status, 201, f"widget {w['title']}", wid)
                    entry["widgets"].append(wid["id"])
                    save(state)
                    print(f"  + {w['title']}")

            status, dash = api("POST", "/dashboards", {"name": d["name"]})
            need(status, 201, "dashboard", dash)
            entry["dashboard"] = dash["id"]
            save(state)
            status, resp = api("POST", f"/dashboards/{dash['id']}/widgets", {"widget_ids": entry["widgets"]})
            need(status, (200, 201, 204), "attach widgets", resp)
            status, resp = api("PATCH", f"/dashboards/{dash['id']}", {"layout": {"widget_layouts": layout_for(d, entry["widgets"])}})
            need(status, (200, 204), "layout", resp)
        except SystemExit:
            save(state)
            print(f"partial state saved to {STATE}; run --delete to clean up", file=sys.stderr)
            raise
        print(f"{d['name']}\n{host}/dashboards/{entry['dashboard']}\n")


def delete(api: API) -> None:
    for key, entry in load().items():
        if entry.get("dashboard"):
            print("dashboard", api("DELETE", f"/dashboards/{entry['dashboard']}")[0])
        for w in entry["widgets"]:
            print("widget   ", api("DELETE", f"/widgets/{w}")[0])
        for m in entry["metrics"]:
            print("metric   ", api("DELETE", f"/metrics/definitions/{m}")[0])
    STATE.unlink(missing_ok=True)


def check(api: API) -> None:
    state = load()
    params = urllib.parse.urlencode({"time_range": "Last 3 hours", "num_of_slices": 6})
    for key, d in DASHBOARDS.items():
        ids = state.get(key, {}).get("metrics", [])
        titles = [w["title"] for row in d["rows"] for w in row]
        for title, metric_id in zip(titles, ids):
            status, resp = api("GET", f"/timeseries/{metric_id}?{params}")
            print(f"{status}  {key:8} {title:34} {json.dumps(resp)[:150]}")


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--validate", action="store_true")
    g.add_argument("--delete", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--relayout", action="store_true")
    args = p.parse_args()
    key = os.environ.get("BRONTO_API_KEY", "").strip()
    if not key:
        raise SystemExit("set BRONTO_API_KEY (dashboard write access; --validate only needs read)")
    api = API(key)
    if args.validate:
        validate(api)
    elif args.delete:
        delete(api)
    elif args.check:
        check(api)
    elif args.relayout:
        relayout(api)
    else:
        create(api)


if __name__ == "__main__":
    main()
