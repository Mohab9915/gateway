"""
Chatbot Gateway Service - Main Application
API Gateway for the Chatbot Microservices Architecture
"""
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import uvicorn
import asyncio
import time
import httpx
from typing import Dict, Any, List, Optional

# Simple configuration
settings = type('Settings', (), {
    'cors_origins': ["*"],
    'service_port': 8000,
    'environment': 'development',
    'debug': True,
    'log_level': 'info',
    'message_processor_url': "https://messageprocessor-production.up.railway.app",
    'ai_nlp_service_url': "https://ai-nlp-service-production.up.railway.app",
    'integration_service_url': "https://integration-service-production.up.railway.app",
    'jwt_secret_key': 'test-secret-key',
    'jwt_algorithm': 'HS256'
})()

# Simple logger
class SimpleLogger:
    def info(self, msg, **kwargs):
        print(f"INFO: {msg}")

    def warning(self, msg, **kwargs):
        print(f"WARNING: {msg}")

    def error(self, msg, **kwargs):
        print(f"ERROR: {msg}")

logger = SimpleLogger()

# Simple request logger
def log_requests(request, call_next):
    return call_next(request)

# Try to import dependencies
try:
    from .routers import conversations, messages, webhooks, health, monitoring
except ImportError as e:
    logger.warning(f"Could not import routers: {e}")
    conversations = None
    messages = None
    webhooks = None
    health = None
    monitoring = None

try:
    from .middleware import RateLimitMiddleware, SecurityHeadersMiddleware, MetricsMiddleware
except ImportError as e:
    logger.warning(f"Could not import middleware: {e}")
    RateLimitMiddleware = None
    SecurityHeadersMiddleware = None
    MetricsMiddleware = None

try:
    from .dependencies import get_current_user, verify_api_key
except ImportError as e:
    logger.warning(f"Could not import dependencies: {e}")
    def get_current_user():
        return None
    def verify_api_key(request):
        return True

try:
    from .exceptions import setup_exception_handlers
except ImportError as e:
    logger.warning(f"Could not import exceptions: {e}")
    def setup_exception_handlers(app):
        pass

# Initialize settings and logger already defined above

# Initialize security
security = HTTPBearer(auto_error=False)

# Service registry - list of available microservices
SERVICE_REGISTRY = {
    "message-processor": {
        "url": settings.message_processor_url,
        "health_endpoint": "/health",
        "timeout": 30.0,
        "retries": 3,
    },
    "ai-nlp-service": {
        "url": settings.ai_nlp_service_url,
        "health_endpoint": "/health",
        "timeout": 30.0,
        "retries": 3,
    },
    "integration-service": {
        "url": settings.integration_service_url,
        "health_endpoint": "/health",
        "timeout": 30.0,
        "retries": 3,
    },
}


class ServiceRegistry:
    """Manage microservice registration and health checking"""

    def __init__(self, services: Dict[str, Dict[str, Any]]):
        self.services = services
        self.health_status = {}
        self.client = httpx.AsyncClient(timeout=30.0)
        self.logger = get_service_logger("service-registry")

    async def check_service_health(self, service_name: str) -> bool:
        """Check health of a specific service"""
        if service_name not in self.services:
            return False

        service_config = self.services[service_name]
        url = f"{service_config['url']}{service_config['health_endpoint']}"

        try:
            response = await self.client.get(url, timeout=5.0)
            is_healthy = response.status_code == 200
            self.health_status[service_name] = {
                "healthy": is_healthy,
                "last_check": time.time(),
                "status_code": response.status_code,
                "response_time": response.elapsed.total_seconds(),
            }

            if not is_healthy:
                self.logger.warning(
                    "service_unhealthy",
                    service=service_name,
                    status_code=response.status_code,
                    url=url,
                )

            return is_healthy

        except Exception as e:
            self.health_status[service_name] = {
                "healthy": False,
                "last_check": time.time(),
                "error": str(e),
            }

            self.logger.error(
                "service_health_check_failed",
                service=service_name,
                error=str(e),
                url=url,
            )

            return False

    async def check_all_services(self) -> Dict[str, bool]:
        """Check health of all registered services"""
        tasks = [
            self.check_service_health(service_name)
            for service_name in self.services.keys()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            service_name: result
            for service_name, result in zip(self.services.keys(), results)
        }

    async def get_healthy_service(self, service_name: str) -> Optional[str]:
        """Get URL of a healthy service instance"""
        if await self.check_service_health(service_name):
            return self.services[service_name]["url"]

        return None

    async def proxy_request(
        self,
        service_name: str,
        path: str,
        method: str = "GET",
        **kwargs
    ) -> httpx.Response:
        """Proxy request to a specific service"""
        service_url = await self.get_healthy_service(service_name)
        if not service_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Service {service_name} is not available"
            )

        full_url = f"{service_url}{path}"

        try:
            response = await self.client.request(method, full_url, **kwargs)
            return response

        except httpx.TimeoutException:
            self.logger.error(
                "service_request_timeout",
                service=service_name,
                url=full_url,
                method=method,
            )

            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Service {service_name} request timeout"
            )

        except httpx.ConnectError:
            self.logger.error(
                "service_connection_error",
                service=service_name,
                url=full_url,
                method=method,
            )

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Cannot connect to service {service_name}"
            )
        except Exception as e:
            self.logger.error(
                "service_request_error",
                service=service_name,
                url=full_url,
                method=method,
                error=str(e),
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Service {service_name} request failed: {str(e)}"
            )


# Global service registry instance
service_registry = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global service_registry

    logger.info("gateway_startup", version="1.0.0")

    # Initialize service registry
    service_registry = ServiceRegistry(SERVICE_REGISTRY)

    # Start background health checking
    health_check_task = asyncio.create_task(periodic_health_check())

    try:
        yield
    finally:
        # Cleanup
        health_check_task.cancel()
        await service_registry.client.aclose()
        logger.info("gateway_shutdown")


# Initialize FastAPI app
app = FastAPI(
    title="Chatbot Gateway Service",
    description="API Gateway for Chatbot Microservices Architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add security headers (optional)
if SecurityHeadersMiddleware:
    app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting (optional)
if RateLimitMiddleware:
    try:
        rate_limit_middleware = RateLimitMiddleware()
        app.add_middleware(type(rate_limit_middleware))
    except Exception as e:
        logger.warning(f"Could not add rate limiting middleware: {e}")

# Add metrics collection (optional)
if MetricsMiddleware:
    try:
        metrics_middleware = MetricsMiddleware(app)
        # Set metrics middleware reference for monitoring router
        if monitoring:
            monitoring.set_metrics_middleware(metrics_middleware)
    except Exception as e:
        logger.warning(f"Could not add metrics middleware: {e}")

# Add request logging
app.middleware("http")(log_requests)


# Exception handlers
setup_exception_handlers(app)


# Include routers (with fallbacks)
try:
    if health:
        app.include_router(
            health.router,
            prefix="/health",
            tags=["Health"]
        )
except Exception as e:
    logger.warning(f"Could not include health router: {e}")

try:
    if monitoring:
        app.include_router(
            monitoring.router,
            prefix="/monitoring",
            tags=["Monitoring"]
        )
except Exception as e:
    logger.warning(f"Could not include monitoring router: {e}")

try:
    if conversations:
        app.include_router(
            conversations.router,
            prefix="/api/v1/conversations",
            tags=["Conversations"],
            dependencies=[Depends(verify_api_key)]
        )
except Exception as e:
    logger.warning(f"Could not include conversations router: {e}")

try:
    if messages:
        app.include_router(
            messages.router,
            prefix="/api/v1/messages",
            tags=["Messages"],
            dependencies=[Depends(verify_api_key)]
        )
except Exception as e:
    logger.warning(f"Could not include messages router: {e}")

# Add Facebook webhook directly to avoid import issues
@app.get("/webhooks/facebook")
async def facebook_webhook_verify(
    request: Request,
    hub_mode: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    hub_verify_token: Optional[str] = None
):
    """Verify Facebook webhook endpoint"""

    import os

    # Get verify token from environment or fallback
    verify_token = os.getenv("FACEBOOK_VERIFY_TOKEN", "test-verify-token-12345")

    print(f"🔍 Facebook webhook verification:")
    print(f"   hub_mode: {hub_mode}")
    print(f"   hub_challenge: {hub_challenge}")
    print(f"   hub_verify_token: {hub_verify_token}")
    print(f"   expected_token: {verify_token}")

    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook verification request"
        )

    if not hub_verify_token or hub_verify_token != verify_token:
        print(f"❌ Token mismatch: received '{hub_verify_token}', expected '{verify_token}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verify token"
        )

    print(f"✅ Webhook verified successfully!")
    return Response(content=hub_challenge, media_type="text/plain")


@app.post("/webhooks/facebook")
async def facebook_webhook_handler(request: Request):
    """Handle Facebook webhook events"""

    import os
    import json

    # Get verify token
    verify_token = os.getenv("FACEBOOK_VERIFY_TOKEN", "test-verify-token-12345")

    try:
        # Get request body
        body = await request.body()
        payload = json.loads(body.decode('utf-8'))

        print(f"📨 Facebook webhook received: {len(body)} bytes")
        print(f"📋 Entries: {len(payload.get('entry', []))}")

        # Process messages (simplified for now)
        messages = []
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                if "message" in messaging and "text" in messaging["message"]:
                    messages.append({
                        "sender_id": messaging["sender"]["id"],
                        "text": messaging["message"]["text"],
                        "platform": "facebook"
                    })

        print(f"📝 Found {len(messages)} message(s)")

        # Here you would process with your AI services
        # For now, just acknowledge receipt

        return {"status": "received", "messages_count": len(messages)}

    except Exception as e:
        print(f"❌ Facebook webhook processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

logger.info("✅ Facebook webhook endpoint added directly to Gateway")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "chatbot-gateway",
        "version": "1.0.0",
        "status": "running",
        "timestamp": time.time(),
    }


@app.get("/api/v1/status")
async def gateway_status(
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Get comprehensive gateway status"""

    # Check all services health
    services_health = await service_registry.check_all_services()

    return {
        "gateway": {
            "status": "healthy",
            "version": "1.0.0",
            "environment": settings.environment,
            "timestamp": time.time(),
        },
        "services": services_health,
        "service_registry": service_registry.health_status,
        "authentication": {
            "authenticated": current_user is not None,
            "user_id": current_user.get("sub") if current_user else None,
        }
    }


@app.post("/api/v1/proxy/{service_name}/{path:path}")
async def proxy_to_service(
    service_name: str,
    path: str,
    request: Request,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Generic proxy endpoint for service requests"""

    if service_name not in SERVICE_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {service_name} not found"
        )

    # Get request body
    body = await request.body()

    # Prepare headers
    headers = dict(request.headers)

    # Add user context to headers if authenticated
    if current_user:
        headers["X-User-ID"] = current_user.get("sub")
        headers["X-User-Email"] = current_user.get("email", "")

    # Remove host header
    headers.pop("host", None)

    # Proxy request
    response = await service_registry.proxy_request(
        service_name=service_name,
        path=f"/{path}",
        method=request.method,
        headers=headers,
        content=body,
        params=request.query_params,
    )

    # Return response
    return JSONResponse(
        content=response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        status_code=response.status_code,
        headers=dict(response.headers),
    )


# Background tasks
async def periodic_health_check():
    """Periodic health checking of all services"""
    while True:
        try:
            await service_registry.check_all_services()
            await asyncio.sleep(30)  # Check every 30 seconds
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(
                "periodic_health_check_error",
                error=str(e),
                exc_info=True,
            )
            await asyncio.sleep(60)  # Wait longer on error


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True,
    )