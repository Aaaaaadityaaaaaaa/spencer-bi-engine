import uuid
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge
from logger import request_id_var

# Prometheus metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"]
)

class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(req_id)
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            
            # Record metrics
            route = request.url.path
            http_requests_total.labels(
                method=request.method,
                endpoint=route,
                status_code=response.status_code
            ).inc()
            
            return response
        finally:
            duration = time.time() - start_time
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)
            request_id_var.reset(token)
