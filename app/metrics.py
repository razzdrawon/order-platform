"""
Prometheus metrics definitions for the Order Orchestration Platform.

All metric objects are module-level singletons — importing this module from
anywhere in the app always returns the same registered metric instances.

Metric types used here:

  Counter   — monotonically increasing number (total orders, total errors).
              Never resets except on process restart.
              Use .inc() to increment.

  Histogram — records the distribution of values (request latency).
              Automatically creates _bucket, _sum, and _count time series.
              Use .observe(value) to record a measurement.

Label cardinality warning: every unique combination of label values creates
a new time series in Prometheus. Never use high-cardinality values like
order_id or customer_id as labels — use only low-cardinality values like
HTTP method, route template, or status code.
"""
from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# HTTP metrics
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    name="http_requests_total",
    documentation="Total HTTP requests by method, path template, and status code.",
    labelnames=["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    name="http_request_duration_seconds",
    documentation="HTTP request latency in seconds by method and path template.",
    labelnames=["method", "path"],
    # Buckets tuned for a web API: from 5ms to 10s
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Business metrics
# ---------------------------------------------------------------------------

ORDERS_CREATED_TOTAL = Counter(
    name="orders_created_total",
    documentation="Total orders successfully created.",
)

ORDERS_CANCELLED_TOTAL = Counter(
    name="orders_cancelled_total",
    documentation="Total orders cancelled.",
)

INVENTORY_ERRORS_TOTAL = Counter(
    name="inventory_errors_total",
    documentation="Total inventory-related errors by type.",
    labelnames=["error_type"],
    # error_type values: insufficient_inventory, optimistic_lock
)

JOBS_COMPLETED_TOTAL = Counter(
    name="jobs_completed_total",
    documentation="Total async order jobs completed successfully.",
)

JOBS_FAILED_TOTAL = Counter(
    name="jobs_failed_total",
    documentation="Total async order jobs that failed.",
)
