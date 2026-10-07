"""A second copy of the agent's spans, for the shared workshop org.

Your own Bronto gets every span in full. The shared org, where everyone's agent
lands as the ai-sre dataset, gets the same spans without their content: no
prompts, answers, or tool inputs and results. It keeps what a room-wide view
needs (span names, timings, models, tokens, tools and their status, attendee),
and it means one agent can't read another's conclusions while it investigates
Storefront in the same org.
"""

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

SHARED_ENDPOINT = "https://ingestion.eu.bronto.io/v1/traces"
CONTENT = ("gen_ai.input.", "gen_ai.output.", "gen_ai.system_instructions", "gen_ai.tool.call.arguments",
           "gen_ai.tool.call.result", "gen_ai.tool.definitions", "gen_ai.prompt", "gen_ai.completion")


def _without_content(span: ReadableSpan) -> ReadableSpan:
    return ReadableSpan(
        name=span.name, context=span.context, parent=span.parent, resource=span.resource,
        attributes={k: v for k, v in (span.attributes or {}).items() if not k.startswith(CONTENT)},
        events=(), links=span.links, kind=span.kind, status=span.status,
        start_time=span.start_time, end_time=span.end_time, instrumentation_scope=span.instrumentation_scope,
    )


class _ContentFree(SpanExporter):
    def __init__(self, inner: SpanExporter):
        self.inner = inner

    def export(self, spans) -> SpanExportResult:
        return self.inner.export([_without_content(s) for s in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def shared_exporter(key: str) -> BatchSpanProcessor:
    return BatchSpanProcessor(_ContentFree(OTLPSpanExporter(endpoint=SHARED_ENDPOINT, headers={"x-bronto-api-key": key})))
