"""
Chatbot Gateway Service - Main Application
API Gateway for the Chatbot Microservices Architecture
"""
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import uvicorn
import asyncio
import time
import httpx
from typing import Dict, Any, List, Optional

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger, log_requests
from shared.models.database import Conversation, Message
from .routers import conversations, messages, webhooks, health, monitoring
from .middleware import RateLimitMiddleware, SecurityHeadersMiddleware, MetricsMiddleware
from .dependencies import get_current_user, verify_api_key
from .exceptions import ChatbotException, setup_exception_handlers

# Initialize settings
settings = get_settings("gateway")
logger = get_service_logger("gateway")

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


# Add security headers
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting
rate_limit_middleware = RateLimitMiddleware()
app.add_middleware(type(rate_limit_middleware))

# Add metrics collection
metrics_middleware = MetricsMiddleware(app)

# Add request logging
app.middleware("http")(log_requests)

# Set metrics middleware reference for monitoring router
monitoring.set_metrics_middleware(metrics_middleware)


# Exception handlers
setup_exception_handlers(app)


# Include routers
app.include_router(
    health.router,
    prefix="/health",
    tags=["Health"]
)

app.include_router(
    monitoring.router,
    prefix="/monitoring",
    tags=["Monitoring"]
)

app.include_router(
    conversations.router,
    prefix="/api/v1/conversations",
    tags=["Conversations"],
    dependencies=[Depends(verify_api_key)]
)

app.include_router(
    messages.router,
    prefix="/api/v1/messages",
    tags=["Messages"],
    dependencies=[Depends(verify_api_key)]
)

app.include_router(
    webhooks.router,
    prefix="/webhooks",
    tags=["Webhooks"]
)


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