"""
Gateway Service Dependencies
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import jwt
import time
from datetime import datetime, timedelta

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger

settings = get_settings("gateway")
logger = get_service_logger("gateway-dependencies")

# Security
security = HTTPBearer(auto_error=False)


async def webhook_rate_limit(request: Request) -> bool:
    """Rate limiting for webhook endpoints"""
    # For now, allow all webhook requests
    # TODO: Implement proper rate limiting
    return True


async def verify_api_key(request: Request) -> bool:
    """Verify API key for protected endpoints"""

    # Check for API key in header
    api_key = request.headers.get("X-API-Key")

    # Also check query parameter for webhooks
    if not api_key:
        api_key = request.query_params.get("api_key")

    # For development, allow requests without API key
    if settings.environment == "development" and not api_key:
        return True

    # TODO: Implement proper API key validation
    # For now, accept any non-empty API key in development
    if settings.environment == "development" and api_key:
        return True

    # In production, validate against database or secure storage
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Add your API key validation logic here
    # This could involve checking against a database, Redis, or other secure storage
    valid_api_keys = [
        "dev-api-key-1",  # Replace with actual validation
        "dev-api-key-2",
    ]

    if api_key not in valid_api_keys and settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Get current user from JWT token"""

    if not credentials:
        return None

    try:
        # Decode JWT token
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )

        # Check token expiration
        exp = payload.get("exp")
        if exp and exp < time.time():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.JWTError as e:
        logger.warning(
            "jwt_validation_error",
            error=str(e),
            credentials_preview=credentials.credentials[:20] if credentials else None
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


async def require_auth(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Require authentication for protected endpoints"""

    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return current_user


async def require_admin(current_user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Require admin role for admin endpoints"""

    if not current_user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return current_user


async def get_conversation_id(
    conversation_id: str,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> str:
    """Validate and return conversation ID"""

    if not conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID is required"
        )

    # TODO: Add validation to check if user has access to this conversation
    # This would involve checking database permissions

    return conversation_id


async def validate_message_content(
    content: str,
    max_length: int = 10000
) -> str:
    """Validate message content"""

    if not content or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty"
        )

    if len(content) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message content too long. Maximum {max_length} characters allowed"
        )

    return content.strip()


async def validate_platform(platform: str) -> str:
    """Validate platform parameter"""

    valid_platforms = ["facebook", "whatsapp", "instagram", "telegram", "custom"]

    if platform not in valid_platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"
        )

    return platform


async def validate_language(language: str) -> str:
    """Validate language parameter"""

    supported_languages = settings.supported_languages

    if language not in supported_languages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language. Supported languages: {', '.join(supported_languages)}"
        )

    return language


class RateLimiter:
    """Simple rate limiter for specific endpoints"""

    def __init__(self):
        self.requests = {}

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int = 60
    ) -> bool:
        """Check if rate limit is exceeded"""

        current_time = time.time()
        window_start = current_time - window

        if key not in self.requests:
            self.requests[key] = []

        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if req_time > window_start
        ]

        # Check limit
        if len(self.requests[key]) >= limit:
            return False

        # Add current request
        self.requests[key].append(current_time)
        return True


# Global rate limiter instance
rate_limiter = RateLimiter()


async def rate_limit(
    limit: int = 100,
    window: int = 60,
    key_func: callable = None
):
    """Rate limiting dependency"""

    def dependency(request: Request):
        # Generate rate limit key
        if key_func:
            key = key_func(request)
        else:
            key = f"{request.client.host}:{request.url.path}"

        # Check rate limit
        if not rate_limiter.check_rate_limit(key, limit, window):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {limit} requests per {window} seconds."
            )

        return True

    return Depends(dependency)


def get_client_ip_rate_limit_key(request: Request) -> str:
    """Generate rate limit key based on client IP"""

    # Check for forwarded IP
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return f"ip:{forwarded_for.split(',')[0].strip()}:{request.url.path}"

    return f"ip:{request.client.host}:{request.url.path}"


def get_user_rate_limit_key(request: Request) -> str:
    """Generate rate limit key based on authenticated user"""

    user = getattr(request.state, "user", None)
    if user and user.get("sub"):
        return f"user:{user['sub']}:{request.url.path}"

    return get_client_ip_rate_limit_key(request)


# Common rate limiting dependencies
webhook_rate_limit = rate_limit(
    limit=1000,  # Higher limit for webhooks
    window=60,
    key_func=get_client_ip_rate_limit_key
)

api_rate_limit = rate_limit(
    limit=100,
    window=60,
    key_func=get_user_rate_limit_key
)

admin_rate_limit = rate_limit(
    limit=50,
    window=60,
    key_func=get_user_rate_limit_key
)