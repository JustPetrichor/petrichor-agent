from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.config import Settings

_telemetry_initialized = False


def configure_telemetry(settings: Settings) -> None:
    global _telemetry_initialized

    if _telemetry_initialized or not settings.app_enable_telemetry:
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "deployment.environment": settings.app_env,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=True,
            )
        )
    )
    trace.set_tracer_provider(tracer_provider)
    LoggingInstrumentor().instrument(set_logging_format=True)
    _telemetry_initialized = True


def instrument_fastapi(app, settings: Settings) -> None:
    if not settings.app_enable_telemetry:
        return

    configure_telemetry(settings)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())


def get_tracer(name: str = "petrichor-agent"):
    return trace.get_tracer(name)


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "unknown"
    return format(span_context.trace_id, "032x")
