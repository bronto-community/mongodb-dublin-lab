#!/usr/bin/env python3
"""Create the "AI SRE agent" dashboard in a Bronto account, from the agent's own GenAI spans.

Everything comes from the ai-sre traces your agent sends from step 2: no custom
logging. Run it from the lab image, with a Bronto API key that can write
dashboards (Settings → API keys; an ingestion key gets a 403):

    docker run --rm -e BRONTO_API_KEY=YOUR-API-KEY -e BRONTO_REGION=eu ghcr.io/bronto-community/mongodb-lab-agent python dashboard.py
    ... python dashboard.py --delete    # remove it again (needs the same container's state: pass -v "$PWD:/state")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("BRONTO_API_URL") or f"https://api.{os.environ.get('BRONTO_REGION', 'eu').strip().lower() or 'eu'}.bronto.io"
NAME = os.environ.get("DASHBOARD_NAME", "AI SRE agent — MongoDB Dublin lab")
STATE = Path(os.environ.get("DASHBOARD_STATE", "/state/dashboard.json" if Path("/state").is_dir() else "dashboard.json"))

TRACES = "\"collection\" = '.traces' AND \"dataset\" = 'ai-sre'"
AGENT = "\"$gen_ai.operation.name\" = 'invoke_agent'"
CHAT = "\"$gen_ai.operation.name\" = 'chat'"
TOOL = "\"$gen_ai.operation.name\" = 'execute_tool'"
NS_TO_MS = {"type": "time", "input": "nanoseconds", "output": "milliseconds"}


def q(name, select, where, groups=(), agg="count", reduce_to="sum", unit=None):
    query = {"name": name, "select": [select], "from_expr": TRACES, "where": where, "groups": list(groups),
             "aggregation": [{"time": agg, "reduce_to": reduce_to}]}
    if unit:
        query["unit_config"] = unit
    return query


# (title, type, description, query), three to a row
WIDGETS = [
    ("Questions answered", "line", "One invoke_agent span per question you asked.",
     q("questions", "*", AGENT)),
    ("Answer time P95", "line", "invoke_agent duration: what you waited for, tools and all.",
     q("answer_p95", "$span.duration_nano", AGENT, agg="p95", reduce_to="max", unit=NS_TO_MS)),
    ("Model calls P95 by model", "line", "One chat span per model call.",
     q("chat_p95", "$span.duration_nano", CHAT, ["$gen_ai.request.model"], agg="p95", reduce_to="max", unit=NS_TO_MS)),

    ("Input tokens by model", "line", "Prompt tokens per model call: history and tool results grow it every loop.",
     q("input_tokens", "$gen_ai.usage.input_tokens", CHAT, ["$gen_ai.request.model"], agg="sum")),
    ("Output tokens by model", "line", "Generated tokens per model call.",
     q("output_tokens", "$gen_ai.usage.output_tokens", CHAT, ["$gen_ai.request.model"], agg="sum")),
    ("Tokens by step", "bar", "Total tokens per AGENT_STEP: every sense you add costs context.",
     q("step_tokens", "$gen_ai.usage.total_tokens", AGENT, ["$agent.step"], agg="sum")),

    ("Tool calls by tool", "top-list", "execute_tool spans: Bronto MCP, the Atlas metrics tools, GitHub MCP.",
     q("tool_calls", "*", TOOL, ["$gen_ai.tool.name"])),
    ("Tool errors", "bar", "execute_tool spans that failed.",
     q("tool_errors", "*", TOOL + " AND \"$gen_ai.tool.status\" = 'error'", ["$gen_ai.tool.name"])),
    ("Model calls per question", "bar", "Agent-loop cycles: more tools, more loops, more tokens.",
     q("cycles", "*", "\"$span.name\" = 'execute_event_loop_cycle'", ["$agent.step"])),

    ("Tokens by attendee", "top-list", "In the shared workshop org: who spent the most. In your own account: you.",
     q("attendee_tokens", "$gen_ai.usage.total_tokens", AGENT, ["$attendee"], agg="sum")),
]


def api(method: str, path: str, body=None):
    req = urllib.request.Request(BASE_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-BRONTO-API-KEY": os.environ["BRONTO_API_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def need(status, ok, what, resp):
    if status not in ok:
        raise SystemExit(f"{what}: HTTP {status}: {resp}"
                         + ("\nThis key can't create dashboards: use an API key, not an ingestion key." if status == 403 else ""))
    return resp


def create() -> None:
    if STATE.exists():
        raise SystemExit(f"{STATE} exists: the dashboard is already there (run with --delete first)")
    state = {"metrics": [], "widgets": [], "dashboard": None}
    try:
        for title, kind, desc, query in WIDGETS:
            status, m = api("POST", "/metrics/definitions", {"name": f"AI SRE — {title}", "description": desc, "queries": [query]})
            need(status, (201,), f"metric {title}", m)
            state["metrics"].append(m["id"])
            status, w = api("POST", "/widgets", {"name": title, "description": desc, "type": kind, "metric_ids": [m["id"]]})
            need(status, (201,), f"widget {title}", w)
            state["widgets"].append(w["id"])
            print(f"  + {title}")
        status, d = api("POST", "/dashboards", {"name": NAME})
        need(status, (201,), "dashboard", d)
        state["dashboard"] = d["id"]
        status, r = api("POST", f"/dashboards/{d['id']}/widgets", {"widget_ids": state["widgets"]})
        need(status, (200, 201, 204), "attach widgets", r)
        # x and w are fractions of the width, snapped by the UI to 12 columns: 0.33333334, not 0.3333
        third = 0.33333334
        layout = [{"id": w, "x": [0.0, third, 0.6666667][i % 3], "y": (i // 3) * 7.0, "w": third, "h": 7.0}
                  for i, w in enumerate(state["widgets"])]
        status, r = api("PATCH", f"/dashboards/{d['id']}", {"layout": {"widget_layouts": layout}})
        need(status, (200, 204), "layout", r)
    except SystemExit:
        print("partly created; run with --delete to clean up", file=sys.stderr)
        raise
    finally:
        STATE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"\n{NAME}\n{BASE_URL.replace('api.', 'app.')}/dashboards/{state['dashboard']}")


def delete() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else {"metrics": [], "widgets": [], "dashboard": None}
    if state["dashboard"]:
        print("dashboard", api("DELETE", f"/dashboards/{state['dashboard']}")[0])
    for w in state["widgets"]:
        print("widget   ", api("DELETE", f"/widgets/{w}")[0])
    for m in state["metrics"]:
        print("metric   ", api("DELETE", f"/metrics/definitions/{m}")[0])
    STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--delete", action="store_true")
    if not os.environ.get("BRONTO_API_KEY"):
        raise SystemExit("set BRONTO_API_KEY: a Bronto API key that can write dashboards")
    delete() if p.parse_args().delete else create()
