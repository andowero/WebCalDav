from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

active_sessions = Gauge(
    "active_sessions",
    "Number of active sessions",
    registry=REGISTRY,
)

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests",
    ["route", "method", "status"],
    registry=REGISTRY,
)

caldav_request_duration_seconds = Histogram(
    "caldav_request_duration_seconds",
    "CalDAV request duration",
    ["operation"],
    registry=REGISTRY,
)

caldav_request_errors_total = Counter(
    "caldav_request_errors_total",
    "CalDAV request errors",
    ["operation"],
    registry=REGISTRY,
)
