"""
Gateway Service Exception Handlers
"""
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Dict, Any, Optional
import time

from shared.utils.logger import get_service_logger

logger = get_service_logger("gateway-exceptions")


class ChatbotException(Exception):
    """Base exception for chatbot service"""

    def __init__(
        self,
        message: str,
        error_code: str = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Dict[str, Any] = None
    ):
        self.message = message
        self.error_code = error_code or "INTERNAL_ERROR"
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ServiceUnavailableException(ChatbotException):
    """Exception for when a downstream service is unavailable"""

    def __init__(self, service_name: str, details: Dict[str, Any] = None):
        super().__init__(
            message=f"Service {service_name} is currently unavailable",
            error_code="SERVICE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"service": service_name, **(details or {})}
        )


class AuthenticationException(ChatbotException):
    """Exception for authentication failures"""

    def __init__(self, message: str = "Authentication failed", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details or {}
        )


class AuthorizationException(ChatbotException):
    """Exception for authorization failures"""

    def __init__(self, message: str = "Access denied", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details or {}
        )


class RateLimitException(ChatbotException):
    """Exception for rate limiting"""

    def __init__(self, message: str = "Rate limit exceeded", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details or {}
        )


class ValidationException(ChatbotException):
    """Exception for validation errors"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details or {}
        )


def create_error_response(
    error_code: str,
    message: str,
    status_code: int,
    details: Dict[str, Any] = None,
    request_id: str = None
) -> JSONResponse:
    """Create standardized error response"""

    response_data = {
        "error": {
            "code": error_code,
            "message": message,
            "timestamp": time.time(),
            "request_id": request_id,
        }
    }

    if details:
        response_data["error"]["details"] = details

    return JSONResponse(
        status_code=status_code,
        content=response_data
    )


async def chatbot_exception_handler(request: Request, exc: ChatbotException):
    """Handler for custom chatbot exceptions"""

    request_id = getattr(request.state, "request_id", None)

    logger.error(
        "chatbot_exception",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )

    return create_error_response(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        request_id=request_id
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler for HTTP exceptions"""

    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )

    # Map HTTP status codes to error codes
    error_code_map = {
        status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
        status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
        status.HTTP_403_FORBIDDEN: "FORBIDDEN",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_429_TOO_MANY_REQUESTS: "TOO_MANY_REQUESTS",
        status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR",
        status.HTTP_502_BAD_GATEWAY: "BAD_GATEWAY",
        status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
        status.HTTP_504_GATEWAY_TIMEOUT: "GATEWAY_TIMEOUT",
    }

    error_code = error_code_map.get(exc.status_code, "HTTP_ERROR")

    return create_error_response(
        error_code=error_code,
        message=exc.detail,
        status_code=exc.status_code,
        request_id=request_id
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handler for validation exceptions"""

    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        "validation_exception",
        errors=exc.errors(),
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )

    # Format validation errors
    formatted_errors = []
    for error in exc.errors():
        formatted_errors.append({
            "field": ".".join(str(x) for x in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    return create_error_response(
        error_code="VALIDATION_ERROR",
        message="Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details={"validation_errors": formatted_errors},
        request_id=request_id
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handler for unexpected exceptions"""

    request_id = getattr(request.state, "request_id", None)

    logger.error(
        "unexpected_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        exc_info=True,
    )

    return create_error_response(
        error_code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=request_id
    )


def setup_exception_handlers(app: FastAPI):
    """Setup all exception handlers for the FastAPI app"""

    # Custom exceptions
    app.add_exception_handler(ChatbotException, chatbot_exception_handler)

    # HTTP exceptions
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Validation exceptions
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # General exception handler (must be last)
    app.add_exception_handler(Exception, general_exception_handler)

    logger.info(
        "exception_handlers_configured",
        handlers_count=5
    )