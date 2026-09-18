from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator, metrics

from app.config import settings


def setup_telemetry(app):
    if settings.otel_enabled:
        resource = Resource.create({"service.name": settings.app_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)

    # Phase 4 (RAG hardening spec): the library's default bundle already
    # includes a latency histogram, but WITHOUT a `handler` label -- p50/p95
    # off that mixes /chat's real (multi-second, LLM-bound) latency with
    # near-instant /healthz probes, which isn't a meaningful signal for
    # judging /chat specifically. Adding this explicitly, per-handler.
    # Instrumentator() only auto-adds its default metric bundle when
    # .add() is never called -- calling .add() ourselves means we must
    # re-add metrics.default() explicitly, or lose the existing
    # http_requests_total/etc. metrics this project already relies on.
    #
    # Real finding: metrics.default() already registers a per-handler
    # "http_request_duration_seconds" histogram, but with only 3 fixed
    # buckets (0.1/0.5/1.0) -- fine for typical HTTP handlers, useless for
    # /chat's multi-second-to-multi-minute LLM-bound latency (every real
    # request landed in the same "+Inf" bucket, no usable p50/p95 shape).
    # A second metrics.latency() call under the SAME default name doesn't
    # error, but silently keeps the first Histogram's buckets -- gave this
    # one an explicit distinct name instead of assuming the buckets
    # argument would take effect.
    (
        Instrumentator()
        .add(metrics.default())
        .add(metrics.latency(
            should_include_handler=True,
            buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 40, 60, 120),
            metric_name="http_request_duration_wide_seconds",
            metric_doc="Request latency by handler, wide buckets suited to /chat's LLM-bound tail latency",
        ))
        .instrument(app)
        .expose(app, endpoint="/metrics")
    )
