import os
import logging
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Suppress debug logs from opentelemetry itself to avoid infinite loops/noise
logging.getLogger("opentelemetry").setLevel(logging.ERROR)

def setup_observability():
    """
    Initializes OpenTelemetry standard instrumentation.
    This routes traces and metrics to the OTLP endpoint (Grafana Cloud).
    LangSmith spans will be automatically correlated and routed here if LANGSMITH_OTEL_ENABLED=true.
    """
    
    # We only initialize if the exporter endpoint is actually provided
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    
    if not otlp_endpoint:
        logging.getLogger(__name__).info("OTEL_EXPORTER_OTLP_ENDPOINT not set. Running without OpenTelemetry.")
        return

    # Basic resource definitions (your app name)
    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "orbit-agent"),
    })

    # ==========================
    # 1. TRACES
    # ==========================
    tracer_provider = TracerProvider(resource=resource)
    
    # Read headers if they exist from standard env var
    headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    headers_dict = {}
    if headers:
        for pair in headers.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers_dict[k.strip()] = v.strip()

    otlp_trace_exporter = OTLPSpanExporter(
        endpoint=f"{otlp_endpoint}/v1/traces",
        headers=headers_dict
    )
    span_processor = BatchSpanProcessor(otlp_trace_exporter)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    # ==========================
    # 2. METRICS
    # ==========================
    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=f"{otlp_endpoint}/v1/metrics",
        headers=headers_dict
    )
    metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=15000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # ==========================
    # 3. LOGGING CORRELATION
    # ==========================
    # This automatically injects trace_id and span_id into standard python logging.
    # Allowing Loki to connect logs to Tempo traces.
    LoggingInstrumentor().instrument(set_logging_format=True)

    logging.getLogger(__name__).info("OpenTelemetry OTLP tracing and metrics successfully initialized.")

def get_meter():
    """Returns the globally configured OpenTelemetry Meter."""
    return metrics.get_meter(os.getenv("OTEL_SERVICE_NAME", "orbit-agent"))
