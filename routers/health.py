"""
Health Check Router
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
import time
import asyncio
import httpx

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger
from ..dependencies import verify_api_key

settings = get_settings("gateway")
logger = get_service_logger("health")

router = APIRouter()

# Service health check client
health_client = httpx.AsyncClient(timeout=5.0)


@router.get("/")
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "service": "gateway",
        "timestamp": time.time(),
        "version": "1.0.0"
    }


@router.get("/detailed")
async def detailed_health_check(api_key: str = Depends(verify_api_key)):
    """Detailed health check with service dependencies"""

    health_status = {
        "service": "gateway",
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "checks": {},
        "dependencies": {}
    }

    # Check database connectivity (if configured)
    if hasattr(settings, 'database_url') and settings.database_url:
        db_healthy = await check_database_health()
        health_status["dependencies"]["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "last_check": time.time()
        }
        if not db_healthy:
            health_status["status"] = "degraded"

    # Check Redis connectivity
    redis_healthy = await check_redis_health()
    health_status["dependencies"]["redis"] = {
        "status": "healthy" if redis_healthy else "unhealthy",
        "last_check": time.time()
    }
    if not redis_healthy:
        health_status["status"] = "degraded"

    # Check downstream services
    services_to_check = [
        ("message-processor", settings.message_processor_url),
        ("ai-nlp-service", settings.ai_nlp_service_url),
        ("integration-service", settings.integration_service_url),
    ]

    for service_name, service_url in services_to_check:
        service_healthy = await check_service_health(service_url)
        health_status["dependencies"][service_name] = {
            "status": "healthy" if service_healthy else "unhealthy",
            "url": service_url,
            "last_check": time.time()
        }
        if not service_healthy:
            health_status["status"] = "degraded"

    return health_status


@router.get("/ready")
async def readiness_check(api_key: str = Depends(verify_api_key)):
    """Readiness check - indicates if service is ready to receive traffic"""

    # Check critical dependencies
    critical_checks = []

    # Check Redis (critical for rate limiting and caching)
    redis_healthy = await check_redis_health()
    critical_checks.append(redis_healthy)

    # Check at least one downstream service is healthy
    services_healthy = []
    for service_url in [settings.message_processor_url, settings.ai_nlp_service_url]:
        if await check_service_health(service_url):
            services_healthy.append(True)

    critical_checks.append(len(services_healthy) > 0)

    # Service is ready if all critical checks pass
    all_healthy = all(critical_checks)

    if all_healthy:
        return {
            "status": "ready",
            "timestamp": time.time(),
            "checks": {
                "redis": redis_healthy,
                "downstream_services": len(services_healthy) > 0
            }
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready"
        )


@router.get("/live")
async def liveness_check():
    """Liveness check - indicates if service is alive"""

    return {
        "status": "alive",
        "timestamp": time.time(),
        "uptime": time.time()  # In real implementation, track actual start time
    }


async def check_database_health() -> bool:
    """Check database connectivity"""
    try:
        # TODO: Implement actual database health check
        # This would involve creating a database connection and running a simple query

        # For now, return True if database_url is configured
        return bool(getattr(settings, 'database_url', None))

    except Exception as e:
        logger.error(
            "database_health_check_error",
            error=str(e)
        )
        return False


async def check_redis_health() -> bool:
    """Check Redis connectivity"""
    try:
        import redis.asyncio as redis

        redis_client = redis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.close()
        return True

    except Exception as e:
        logger.error(
            "redis_health_check_error",
            error=str(e),
            url=settings.redis_url
        )
        return False


async def check_service_health(service_url: str) -> bool:
    """Check if a downstream service is healthy"""
    if not service_url:
        return False

    try:
        health_url = f"{service_url.rstrip('/')}/health"
        response = await health_client.get(health_url, timeout=5.0)
        return response.status_code == 200

    except Exception as e:
        logger.debug(
            "service_health_check_failed",
            service=service_url,
            error=str(e)
        )
        return False


@router.get("/version")
async def version_info():
    """Get version information"""
    return {
        "service": "gateway",
        "version": "1.0.0",
        "build_info": {
            "timestamp": "2025-11-15T22:30:00Z",
            "git_commit": "abc123def",  # Would be actual commit hash
            "environment": settings.environment
        },
        "dependencies": {
            "fastapi": "0.104.1",
            "python": "3.11"
        }
    }


@router.get("/metrics")
async def health_metrics(api_key: str = Depends(verify_api_key)):
    """Health-related metrics"""

    return {
        "uptime_seconds": time.time(),  # Would be actual uptime
        "last_health_check": time.time(),
        "total_checks": 0,  # Would track actual check count
        "healthy_checks": 0,
        "unhealthy_checks": 0
    }