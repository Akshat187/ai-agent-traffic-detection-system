"""
Observability, Structured JSON Logging, and Prometheus Metrics for SentinelTrace.
"""

import contextvars
import json
import logging
import threading
import time
from collections import defaultdict
from typing import Dict

# Correlation IDs for structured JSON logging
correlation_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="-")
correlation_site_id: contextvars.ContextVar[str] = contextvars.ContextVar("site_id", default="-")


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON with session_id and site_id correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": getattr(record, "session_id", correlation_session_id.get()),
            "site_id": getattr(record, "site_id", correlation_site_id.get()),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configures root logger with StructuredJsonFormatter if not already configured."""
    root = logging.getLogger("sentineltrace")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        root.addHandler(handler)
        root.setLevel(level)
        root.propagate = False


class MetricsRegistry:
    """Thread-safe in-memory Prometheus metrics registry."""

    def __init__(self):
        self._lock = threading.Lock()
        self.http_requests: Dict[tuple, int] = defaultdict(int)
        self.http_errors: Dict[tuple, int] = defaultdict(int)
        self.classifications: Dict[str, int] = defaultdict(int)
        self.layer_latency_sum_ms: Dict[str, float] = defaultdict(float)
        self.layer_latency_count: Dict[str, int] = defaultdict(int)

    def record_http(self, method: str, status_code: int) -> None:
        with self._lock:
            self.http_requests[(method, str(status_code))] += 1
            if status_code >= 400:
                self.http_errors[(method, str(status_code))] += 1

    def record_classification(self, label: str) -> None:
        with self._lock:
            self.classifications[label] += 1

    def record_layer_latency(self, layer: str, duration_ms: float) -> None:
        with self._lock:
            self.layer_latency_sum_ms[layer] += duration_ms
            self.layer_latency_count[layer] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP sentineltrace_http_requests_total Total HTTP requests processed",
            "# TYPE sentineltrace_http_requests_total counter",
        ]
        with self._lock:
            for (method, status), count in sorted(self.http_requests.items()):
                lines.append(f'sentineltrace_http_requests_total{{method="{method}",status="{status}"}} {count}')

            lines.extend([
                "# HELP sentineltrace_http_errors_total Total HTTP 4xx/5xx error responses",
                "# TYPE sentineltrace_http_errors_total counter",
            ])
            for (method, status), count in sorted(self.http_errors.items()):
                lines.append(f'sentineltrace_http_errors_total{{method="{method}",status="{status}"}} {count}')

            lines.extend([
                "# HELP sentineltrace_classifications_total Total actor classifications by verdict",
                "# TYPE sentineltrace_classifications_total counter",
            ])
            for label, count in sorted(self.classifications.items()):
                lines.append(f'sentineltrace_classifications_total{{verdict="{label}"}} {count}')

            lines.extend([
                "# HELP sentineltrace_layer_latency_ms_sum Cumulative latency in ms per detection layer",
                "# TYPE sentineltrace_layer_latency_ms_sum counter",
            ])
            for layer, total_ms in sorted(self.layer_latency_sum_ms.items()):
                lines.append(f'sentineltrace_layer_latency_ms_sum{{layer="{layer}"}} {total_ms:.4f}')

            lines.extend([
                "# HELP sentineltrace_layer_latency_ms_count Number of evaluations per detection layer",
                "# TYPE sentineltrace_layer_latency_ms_count counter",
            ])
            for layer, cnt in sorted(self.layer_latency_count.items()):
                lines.append(f'sentineltrace_layer_latency_ms_count{{layer="{layer}"}} {cnt}')

        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()
