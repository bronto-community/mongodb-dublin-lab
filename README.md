# MongoDB Dublin: AI Observability & Monitoring

Bronto's talk and guided build at **MongoDB Dublin** (Building 2, 1 Ballsbridge, Shelbourne Road, Dublin 4) for
Dublin AI Week, hosted by Give(a)Go, on **Wednesday 7 October 2026**. Event page: <https://luma.com/observability>.

- **Deck:** <https://ai-observability-dublin.vercel.app> (source: [`slides/`](slides))
- **Lab guide:** <https://mongodb-dublin-lab.vercel.app> (source: [`site/app/page.mdx`](site/app/page.mdx))

## Run of show

| Time (Dublin, pm) | What | Deck |
|---|---|---|
| 6:00 | Doors, food, networking | title slide up |
| 6:30 | Welcome and build-session briefing (Give(a)Go) | |
| 6:40 | Harshit Mehta, MongoDB: "AI Observability in Action: MongoDB Atlas OTel Metrics Sink" (talk only) | |
| 6:55 | **Bronto talk**, 20 min, with a live Bronto + Claude demo | slides 1–13 |
| 7:15 | **Guided build**, 75 min: setup + six steps | slides 14–21 |
| 8:30 | Builds, lessons and questions | slide 22 |
| 8:45 | Food and networking; 9:00 close | slide 23 |

The build delivers what the event page promises:

- **Trace model, agent and tool activity:** step 2, where the agent sends its own traces to the attendee's Bronto.
- **Connect application signals with database metrics:** step 4, Atlas metrics through Bronto's metrics API, plus
  slow-query logs.
- **Investigate a production issue to its root cause:** steps 3, 5 and 6.

## What's here

| Path | What it is |
|---|---|
| [`slides/`](slides) | Slidev deck. `npm ci && npx slidev`; publish with `./deploy.sh` |
| [`site/`](site) | The lab guide (Next.js, static, one MDX page). `npm ci && npm run dev` |
| [`agent/`](agent) | The lab's own AI SRE (Strands), one image with `AGENT_STEP=1..6`, published as `ghcr.io/bronto-community/mongodb-lab-agent` |
| [`storefront/`](storefront) | Builds `bronto-community/storefront-mongo`: Severin's Storefront up to v3.1.0, moved to MongoDB Atlas (v4.0.0), and the v4.1.0 release with the incident |
| [`harness/`](harness) | One EC2 instance running Storefront, its load and an OpenTelemetry Collector that forwards Storefront's telemetry to the shared Bronto demo org. It also relays Atlas's mongod log export: Caddy on 443 (TLS and a relay token) in front of the Collector, which turns each mongod line into one Bronto event with its fields. Atlas sends its metrics to Bronto directly |

## The incident

Storefront's shop-checkout and shop-catalog store their data in an Atlas M10 cluster with about 1.3M orders. Release
v4.1.0 has three commits, and one of them adds a query on `orders` that no index covers. Every checkout then scans the
collection. Here is what each signal shows:

| Signal | What it shows |
|---|---|
| Traces | A slow `storefront.aggregate` span on `orders` under `POST /checkout` (about 0.55 s per checkout, against 5 ms for the insert) |
| Atlas metrics | Query targeting and operation latency jump |
| Atlas logs | `Slow query … COLLSCAN` |
| GitHub | The commit, with its misleading message |

Don't share the details with attendees before 8:30. The speaker notes on slides 21–22 have the answer.

### Organiser checklist

**One-off setup**

1. **Atlas:** an M10 cluster called `storefront` and a database user with readWrite on `storefront`.
   - Add the harness's Elastic IP in Network Access.
   - Project → Integrations → OpenTelemetry:
     - **metrics** to `https://ingestion.eu.bronto.io/v1/metrics`;
     - **log export** (`mongod`) to the harness relay, `https://<elastic-ip-with-dashes>.sslip.io/v1/logs`.

     Metrics use the header `x-bronto-api-key` set to the ingestion key. The log export uses `X-Relay-Token` set to the relay token, `RELAY_TOKEN` in the gitignored `harness/.env`.
2. **Storefront repo:**
   - Run `sh storefront/build-history.sh /tmp/storefront-mongo`.
   - Push it to `bronto-community/storefront-mongo` with `git push -u origin main --tags`.
3. **Harness:** run `set -a; . harness/.env; set +a`, then `harness/deploy.sh` with `MONGODB_URI` set. A redeploy
   rebuilds the instance's `.env` from Secrets Manager: run `./night.sh load 0.3` again afterwards, unless the secret
   has `CHECKOUT_RPS=0.3`.
4. **Shared demo org:** the EU org. Its public "ReadOnly" key has the Lab read (logs + metrics) role, so it covers both MCP and the metrics API.
5. **Agent image:**
   ```bash
   docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/bronto-community/mongodb-lab-agent --push agent
   ```
   Make the package public on GHCR.
6. **Deck and guide:** run `slides/deploy.sh`, and deploy `site/` to its own Vercel project, `mongodb-dublin-lab`.

**Pre-event email**

Approved guests get setup guidance before the event. Ask them to arrive with:

- Docker installed
- a Gemini API key
- a Bronto account and its ingestion key
- the `ai-sre-issues` repo and its token
- `docker pull ghcr.io/bronto-community/mongodb-lab-agent` already done, and pulled **again** on the night: the image
  was updated on 7 October (shared-org copy, step 4 metrics fix)

**On the night**

The event's times are Dublin time, Irish Standard Time (UTC+1). The harness runs on **UTC**, so its hourly timers
fire at 19:00 and 19:15 Dublin time (18:00 and 18:15 UTC). Left alone, they would roll the incident back at 20:00
Dublin time, in the middle of step 5. Instead, switch the incident by hand from a laptop with
[`harness/night.sh`](harness/night.sh), which runs the commands on the instance over SSM:

| Dublin (IST) | UTC | Run | Effect |
|---|---|---|---|
| before 19:00 | before 18:00 | `./night.sh load 0.3` | 0.3 checkouts a second. The M10 is burstable: once its CPU credits run out, Atlas throttles it to about 20% (CPU steal ~80%), and at 0.5 or more the bad release tips into minutes-long queues within the hour |
| 19:00 | 18:00 | `./night.sh baseline` | Hourly timers off, good release `v4.0.0` live. 19:00–19:30 is the quiet baseline |
| 19:30 | 18:30 | `./night.sh release` | `v4.1.0` ships and checkout gets slow. Leave it running through the build |
| after 20:45 | after 19:45 | `./night.sh restore` | Good release back, hourly timers on again |

Run each from `harness/` with `AWS_PROFILE=bronto`, after `aws sso login --profile bronto`.
`./night.sh status` shows which release is live, the timers and the load.

**Before the talk (6:55)**, for the live demo on slides 9 and 10:

- Open both dashboards, logged in to the shared org, at "Last 1 hour" and a rollup of 2 minutes or more (at 1 minute
  the Atlas counter charts read 0). The hourly incident is live from 18:15 to 19:00 Dublin time.
- Claude Desktop with the Bronto connector on the shared org, a fresh chat, the three questions from slide 10 ready.
- The deck's backup screenshots are in `slides/public/img/demo/`; the Claude ones are `claude-1..3.png`.

## Dashboards

[`harness/dashboards/create_dashboards.py`](harness/dashboards/create_dashboards.py) builds two dashboards in the shared demo org, for the talk's live demo:

- **Storefront × Atlas — checkout**: checkout latency and requests, the release running, the MongoDB calls under checkout, Atlas query targeting and CPU, and the mongod slow-query log. One time axis, top to bottom.
- **Atlas — storefront (M10)**: Atlas's own Metrics-tab charts (opcounters, query targeting, op execution time, connections, CPU, memory, disk, network, replication lag, queues), from the OTel Metrics Sink.

Atlas sends serverStatus counters as ever-growing gauges, and Bronto has no derivative function. So each counter is two queries per bucket, MAX and MIN, plus a formula for the difference. The script's docstring explains the details. One definition takes at most six queries, and a formula expression at most 100 characters.

```bash
BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --validate   # read-only dry run
BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py              # create
BRONTO_API_KEY=... python3 harness/dashboards/create_dashboards.py --delete     # remove, from state.json
```

Creating needs a key with dashboard write access; the public read-only key is enough for `--validate`. The IDs of what it created are in `harness/dashboards/state.json`.

**The room's agents.** With `WORKSHOP_INGEST_KEY` in their `.env` (step 2), every attendee's agent sends its spans to
their own Bronto in full, and a copy to the shared org without prompts, answers or tool results
([`agent/workshop.py`](agent/workshop.py)). The copy lands in `.traces / ai-sre`, which the agent's prompt tells it to
ignore, and without content, so one agent can't read another's conclusions. "AI SRE agents — the whole room" in the
shared org is built from it by [`agent/dashboard.py`](agent/dashboard.py) (its IDs are in
`harness/dashboards/agents/dashboard.json`). Attendees can run the same script against their own account:

```bash
docker run --rm -e BRONTO_API_KEY=THEIR-API-KEY -e BRONTO_REGION=eu ghcr.io/bronto-community/mongodb-lab-agent python dashboard.py
```

`WORKSHOP_INGEST_KEY` is the harness's ingestion key, published in the guide for the evening: rotate it afterwards
(it also carries Storefront's telemetry, so update `harness/.env` and the Secrets Manager secret when you do).

## Provisioned (5 October)

- **Atlas:** org "Stephen's Org", project `mongodb-dublin` (`6ac39bb035b2838e26badbdf`).
  - Cluster `storefront`: M10, AWS eu-west-1, MongoDB 8.0.
  - Database user `storefront`, with readWrite on the `storefront` database.
  - The password is in the gitignored `harness/.env`.
- **Atlas → Bronto metrics:** a custom OTEL metric integration that sends MongoDB and hardware metrics to `https://ingestion.eu.bronto.io/v1/metrics`. The test metric arrived in the shared EU org.
- **Bronto:** ingestion key "mongodb-dublin ingestion (Storefront + Atlas)", which expires 4 November 2026. It's in the gitignored `harness/.env`.
- **GitHub:** `bronto-community/storefront-mongo`, with the built history and tags.
- **Bronto public read-only key** ("ReadOnly", shared with other Bronto labs in the same org): moved from the built-in SearchApi role to a custom API role, **Lab read (logs + metrics)**.
  - Permissions: `logs_read`, `logs_read_pii` and `dashboards_read`.
  - `dashboards_read` is what Bronto checks for `GET /metrics` and `POST /timeseries/search`; Bronto has no metrics permission of its own.
  - MCP still works with it.

## Notes and open questions

- **Atlas log export goes through the harness relay** (Caddy → Collector → Bronto `/v1/logs`).
  - What Atlas sends (Caddy's log, 7 Oct, 3 hours): OTLP/HTTP **JSON**, `POST /v1/logs`, `Content-Type: application/json`, no compression, user agent `Java-http-client/11.0.18`, about 3 posts a minute of 7.6–575 KB (median 66 KB), from AWS us-east-1 addresses although the cluster is in eu-west-1. All 200; the Collector logged no errors.
  - Each record's body is one mongod JSON log line. The Collector parses it into fields and keeps slow queries, warnings and errors, so each becomes one event in `mongodb-dublin / atlas-mongod` with `msg`, `attr.ns`, `attr.planSummary` and `attr.docsExamined`. Without the relay Bronto would get about 1 GB per node per day of unparsed lines.
  - When the relay was built (5–6 Oct), Atlas's scheduled exports never arrived at Bronto's endpoint directly, only its tests did, and Bronto's `/v1/logs` accepts only an exact `application/json` or `application/x-protobuf` Content-Type. Atlas now sends exactly `application/json`, so a direct export may work: untested, and it would lose the parsing and filtering.
  - Configure it through the Admin API (`PUT /groups/{id}/logIntegrations/{id}`, type `OTEL_LOG_EXPORT`). The UI's edit form re-sends the masked header value when it tests.
- The values on the GenAI vocabulary slide (model, tokens, tool name) are illustrative. The checkout trace slide uses two real harness traces.
- End-to-end test, 7 Oct, gemini-3.8-flash, against the live incident: steps 1–6 all answer; step 6 names commit `46c63a30`. With the "at most 10 tool calls" rule in `my.md`, a step 4 question took 12 model calls, ~200k input tokens and 87 s; without it, 77 calls and millions of tokens. Every MongoDB span carries `db.statement`, so a good agent can name the `customer_email` filter as early as step 3.
- Load (`CHECKOUT_RPS`) and seed size (`SEED_ORDERS`): 0.3 checkouts a second and 1.3M orders make the bad release cost about 0.6 s per checkout without draining the M10's CPU credits (7 Oct). `night.sh trim` brings orders back down as checkouts add to them.
