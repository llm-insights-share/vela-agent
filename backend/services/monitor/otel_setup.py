"""OpenTelemetry TracerProvider setup for OpenInference dual-write."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_INITIALIZED = False
TRACER_NAME = "vela.agent"


def _load_observability_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "otel_enabled": True,
        "otlp_endpoint": "",
        "success_sample_rate": 1.0,
    }
    try:
        import yaml
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "vela.yaml"
        if path.is_file():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            obs = raw.get("observability") or {}
            if isinstance(obs, dict):
                cfg["otel_enabled"] = bool(obs.get("otel_enabled", True))
                cfg["otlp_endpoint"] = str(obs.get("otlp_endpoint") or "")
                if obs.get("success_sample_rate") is not None:
                    cfg["success_sample_rate"] = float(obs["success_sample_rate"])
    except Exception as e:
        logger.debug("observability config load skipped: %s", e)

    env_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if env_endpoint:
        cfg["otlp_endpoint"] = env_endpoint
    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("1", "true", "yes"):
        cfg["otel_enabled"] = False
    return cfg


def is_otel_enabled() -> bool:
    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("1", "true", "yes"):
        return False
    return bool(_load_observability_config().get("otel_enabled", True))


def get_tracer():
    from opentelemetry import trace

    return trace.get_tracer(TRACER_NAME)


def setup_tracer_provider(*, force: bool = False) -> None:
    """Initialize global TracerProvider once (idempotent)."""
    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    cfg = _load_observability_config()
    if not cfg.get("otel_enabled", True):
        logger.info("OpenTelemetry disabled via config/env")
        if force:
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider

                # Replace provider without OTLP exporter so prior Phoenix endpoint stops receiving
                provider = TracerProvider(
                    resource=Resource.create({"service.name": "vela-agent", "service.namespace": "vela"})
                )
                trace.set_tracer_provider(provider)
            except Exception as e:
                logger.debug("disabled tracer replace skipped: %s", e)
        _INITIALIZED = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from services.monitor.span_buffer import BufferSpanProcessor
    except ImportError as e:
        logger.warning("OpenTelemetry packages missing: %s", e)
        _INITIALIZED = True
        return

    resource = Resource.create(
        {
            "service.name": "vela-agent",
            "service.namespace": "vela",
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BufferSpanProcessor())

    endpoint = (cfg.get("otlp_endpoint") or "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            otlp_url = endpoint.rstrip("/")
            if not otlp_url.endswith("/v1/traces"):
                otlp_url = otlp_url + "/v1/traces"
            exporter = OTLPSpanExporter(endpoint=otlp_url)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP exporter configured: %s", otlp_url)
        except Exception as e:
            logger.warning("OTLP exporter setup failed: %s", e)
    else:
        logger.info("OTLP endpoint empty; OpenInference spans buffer locally only")

    # Always replace when force, or when still on proxy/noop
    existing = trace.get_tracer_provider()
    existing_name = existing.__class__.__name__
    if force or existing_name in ("ProxyTracerProvider", "NoOpTracerProvider"):
        # Shut down previous provider to flush/stop old exporters
        if force and existing_name == "TracerProvider":
            try:
                existing.shutdown()  # type: ignore[attr-defined]
            except Exception:
                pass
        trace.set_tracer_provider(provider)
    elif isinstance(existing, TracerProvider):
        logger.debug("TracerProvider already set; skipping re-init")
    else:
        trace.set_tracer_provider(provider)

    _INITIALIZED = True


def shutdown_tracer_provider() -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.shutdown()
    except Exception:
        pass
