from prometheus_client import Counter, Gauge, Histogram, start_http_server


REQUESTS_TOTAL = Counter(
    "bot_requests_total",
    "Total number of requests processed by bot",
    ["handler"]
)

CACHE_HITS = Counter(
    "cache_hits_total",
    "Number of cache hits"
)

CACHE_MISSES = Counter(
    "cache_misses_total",
    "Number of cache misses"
)

RABBITMQ_PUBLISHED = Counter(
    "rabbitmq_messages_published_total",
    "Number of messages published to RabbitMQ",
    ["routing_key"]
)

ERRORS_TOTAL = Counter(
    "bot_errors_total",
    "Total number of errors",
    ["error_type"]
)

ACTIVE_USERS = Gauge(
    "active_users_count",
    "Number of users active in last 24 hours"
)

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "Request duration in seconds",
    ["handler"]
)


def start_metrics_server(port: int = 8001):
    start_http_server(port)
    print(f"Metrics server started on http://0.0.0.0:{port}/metrics")