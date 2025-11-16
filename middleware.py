"""
Gateway Service Middleware
"""
from fastapi import Request, Response, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, Any, Optional, Callable
import time
import uuid
import redis.asyncio as redis
from collections import defaultdict, deque
import asyncio

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger

settings = get_settings("gateway")
logger = get_service_logger("middleware")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis"""

    def __init__(self, app, redis_url: str = None):
        super().__init__(app)
        self.redis_url = redis_url or settings.redis_url
        self.redis_client = None
        self.local_cache = defaultdict(lambda: deque(maxlen=100))
        self.window_size = settings.rate_limit_window
        self.max_requests = settings.rate_limit_requests

    async def startup(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info("rate_limit_redis_connected", url=self.redis_url)
        except Exception as e:
            logger.error(
                "rate_limit_redis_connection_failed",
                error=str(e),
                url=self.redis_url
            )
            # Fallback to local in-memory rate limiting
            self.redis_client = None

    async def shutdown(self):
        """Cleanup Redis connection"""
        if self.redis_client:
            await self.redis_client.close()

    async def get_client_ip(self, request: Request) -> str:
        """Get client IP address considering proxies"""
        # Check for forwarded IP headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct connection IP
        return request.client.host if request.client else "unknown"

    async def is_rate_limited(self, key: str) -> bool:
        """Check if the key is rate limited"""

        current_time = time.time()
        window_start = int(current_time) - self.window_size

        if self.redis_client:
            return await self._redis_rate_limit_check(key, window_start, current_time)
        else:
            return self._local_rate_limit_check(key, window_start, current_time)

    async def _redis_rate_limit_check(self, key: str, window_start: float, current_time: float) -> bool:
        """Check rate limit using Redis"""

        try:
            # Remove old entries
            await self.redis_client.zremrangebyscore(
                f"rate_limit:{key}",
                0,
                window_start
            )

            # Count current entries
            current_count = await self.redis_client.zcard(f"rate_limit:{key}")

            if current_count >= self.max_requests:
                return True

            # Add current request
            await self.redis_client.zadd(
                f"rate_limit:{key}",
                {str(uuid.uuid4()): current_time}
            )

            # Set expiration
            await self.redis_client.expire(f"rate_limit:{key}", self.window_size)

            return False

        except Exception as e:
            logger.error(
                "redis_rate_limit_check_error",
                error=str(e),
                key=key
            )
            # Fallback to local check
            return self._local_rate_limit_check(key, window_start, current_time)

    def _local_rate_limit_check(self, key: str, window_start: float, current_time: float) -> bool:
        """Check rate limit using local memory (fallback)"""

        # Clean old entries
        while self.local_cache[key] and self.local_cache[key][0] < window_start:
            self.local_cache[key].popleft()

        # Check current count
        if len(self.local_cache[key]) >= self.max_requests:
            return True

        # Add current request
        self.local_cache[key].append(current_time)
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Initialize Redis if not done
        if self.redis_client is None and self.redis_url:
            await self.startup()

        client_ip = await self.get_client_ip(request)
        rate_limit_key = f"rate_limit:{client_ip}:{request.url.path}"

        # Check rate limit
        if await self.is_rate_limited(rate_limit_key):
            logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=request.url.path,
                method=request.method,
            )

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded. Maximum {self.max_requests} requests per {self.window_size} seconds.",
                        "retry_after": self.window_size
                    }
                },
                headers={"Retry-After": str(self.window_size)}
            )

        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to all requests"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect request metrics"""

    def __init__(self, app):
        super().__init__(app)
        self.request_count = 0
        self.request_times = deque(maxlen=1000)
        self.error_count = 0
        self.status_codes = defaultdict(int)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        self.request_count += 1

        try:
            response = await call_next(request)
            response_time = time.time() - start_time

            # Record metrics
            self.request_times.append(response_time)
            self.status_codes[response.status_code] += 1

            # Add metrics headers
            response.headers["X-Response-Time"] = f"{response_time:.3f}s"

            return response

        except Exception as e:
            response_time = time.time() - start_time
            self.error_count += 1

            logger.error(
                "middleware_request_error",
                error=str(e),
                response_time=response_time,
                path=request.url.path,
                method=request.method,
            )

            raise

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "avg_response_time": sum(self.request_times) / len(self.request_times) if self.request_times else 0,
            "status_codes": dict(self.status_codes),
            "last_minute_requests": len([
                rt for rt in self.request_times
                if time.time() - rt < 60
            ])
        }


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Optional authentication middleware for public endpoints"""

    def __init__(self, app, require_auth: bool = False):
        super().__init__(app)
        self.require_auth = require_auth
        self.security = HTTPBearer(auto_error=False)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Add authentication info to request state
        credentials: Optional[HTTPAuthorizationCredentials] = await self.security(request)

        if credentials:
            # TODO: Validate JWT token and extract user info
            request.state.user = {
                "authenticated": True,
                "token": credentials.credentials,
                # Add more user info after JWT validation
            }
        else:
            request.state.user = {
                "authenticated": False,
            }

        return await call_next(request)