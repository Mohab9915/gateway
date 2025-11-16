"""
Monitoring Router - System monitoring and metrics
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
import time
import psutil
import os

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger
from ..dependencies import verify_api_key, require_admin
from ..middleware import MetricsMiddleware

settings = get_settings("gateway")
logger = get_service_logger("monitoring")

router = APIRouter()

# Global metrics middleware reference (will be set in main.py)
metrics_middleware: Optional[MetricsMiddleware] = None


@router.get("/metrics")
async def get_metrics(api_key: str = Depends(verify_api_key)):
    """Get basic system metrics"""

    try:
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Process metrics
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()
        process_cpu = process.cpu_percent()

        metrics = {
            "timestamp": time.time(),
            "system": {
                "cpu_percent": cpu_percent,
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used,
                    "free": memory.free
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100
                }
            },
            "process": {
                "pid": os.getpid(),
                "memory": {
                    "rss": process_memory.rss,
                    "vms": process_memory.vms,
                    "percent": process.memory_percent()
                },
                "cpu_percent": process_cpu,
                "num_threads": process.num_threads(),
                "create_time": process.create_time()
            }
        }

        # Add gateway metrics if available
        if metrics_middleware:
            metrics["gateway"] = metrics_middleware.get_metrics()

        return metrics

    except Exception as e:
        logger.error(
            "get_metrics_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve metrics"
        )


@router.get("/health-summary")
async def get_health_summary(
    current_user: Dict = Depends(require_admin),
    api_key: str = Depends(verify_api_key)
):
    """Get comprehensive health summary for admin dashboard"""

    try:
        # Get system metrics
        system_metrics = await get_metrics(api_key)

        # Service health check would be implemented here
        # This would check the health of all downstream services

        health_summary = {
            "timestamp": time.time(),
            "overall_status": "healthy",  # Would be calculated based on all checks
            "services": {
                "gateway": {
                    "status": "healthy",
                    "cpu_percent": system_metrics["system"]["cpu_percent"],
                    "memory_percent": system_metrics["system"]["memory"]["percent"],
                    "uptime": time.time() - system_metrics["process"]["create_time"]
                },
                "message-processor": {
                    "status": "unknown",  # Would check actual service
                    "response_time": None
                },
                "ai-nlp-service": {
                    "status": "unknown",  # Would check actual service
                    "response_time": None
                },
                "integration-service": {
                    "status": "unknown",  # Would check actual service
                    "response_time": None
                }
            },
            "system": {
                "cpu_percent": system_metrics["system"]["cpu_percent"],
                "memory_percent": system_metrics["system"]["memory"]["percent"],
                "disk_percent": system_metrics["system"]["disk"]["percent"]
            },
            "alerts": []  # Would contain any active alerts
        }

        return health_summary

    except Exception as e:
        logger.error(
            "get_health_summary_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve health summary"
        )


@router.get("/performance")
async def get_performance_metrics(
    current_user: Dict = Depends(require_admin),
    api_key: str = Depends(verify_api_key)
):
    """Get detailed performance metrics"""

    try:
        # This would pull metrics from Prometheus or other monitoring systems
        # For now, return a placeholder

        performance_metrics = {
            "timestamp": time.time(),
            "response_times": {
                "avg": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0
            },
            "request_rates": {
                "requests_per_second": 0.0,
                "requests_per_minute": 0.0
            },
            "error_rates": {
                "error_rate_5m": 0.0,
                "error_rate_1h": 0.0
            },
            "throughput": {
                "messages_processed": 0,
                "conversations_created": 0
            }
        }

        if metrics_middleware:
            gateway_metrics = metrics_middleware.get_metrics()
            performance_metrics["gateway"] = {
                "request_count": gateway_metrics.get("request_count", 0),
                "error_count": gateway_metrics.get("error_count", 0),
                "avg_response_time": gateway_metrics.get("avg_response_time", 0),
                "last_minute_requests": gateway_metrics.get("last_minute_requests", 0)
            }

        return performance_metrics

    except Exception as e:
        logger.error(
            "get_performance_metrics_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve performance metrics"
        )


@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    limit: int = 100,
    current_user: Dict = Depends(require_admin),
    api_key: str = Depends(verify_api_key)
):
    """Get recent logs (placeholder - would integrate with log aggregation system)"""

    try:
        # This would integrate with ELK stack, Loki, or similar
        # For now, return recent error logs from the logger

        logs = [
            {
                "timestamp": time.time(),
                "level": "INFO",
                "message": "Sample log entry - this would be replaced with actual logs",
                "service": "gateway",
                "trace_id": None
            }
        ]

        return {
            "logs": logs,
            "total": len(logs),
            "level": level,
            "limit": limit
        }

    except Exception as e:
        logger.error(
            "get_logs_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve logs"
        )


@router.get("/alerts")
async def get_alerts(
    current_user: Dict = Depends(require_admin),
    api_key: str = Depends(verify_api_key)
):
    """Get active alerts"""

    try:
        # This would integrate with alerting system like Prometheus Alertmanager
        alerts = []

        # Example alert logic
        system_metrics = await get_metrics(api_key)

        if system_metrics["system"]["cpu_percent"] > 80:
            alerts.append({
                "id": "high-cpu",
                "severity": "warning",
                "message": f"High CPU usage: {system_metrics['system']['cpu_percent']}%",
                "timestamp": time.time(),
                "service": "system"
            })

        if system_metrics["system"]["memory"]["percent"] > 80:
            alerts.append({
                "id": "high-memory",
                "severity": "warning",
                "message": f"High memory usage: {system_metrics['system']['memory']['percent']}%",
                "timestamp": time.time(),
                "service": "system"
            })

        return {
            "alerts": alerts,
            "total": len(alerts),
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(
            "get_alerts_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve alerts"
        )


@router.post("/test-alert")
async def test_alert(
    alert_data: Dict[str, Any],
    current_user: Dict = Depends(require_admin),
    api_key: str = Depends(verify_api_key)
):
    """Test alert endpoint for development"""

    try:
        logger.info(
            "test_alert_received",
            alert_data=alert_data,
            user=current_user.get("sub")
        )

        return {
            "status": "alert_tested",
            "timestamp": time.time(),
            "alert": alert_data
        }

    except Exception as e:
        logger.error(
            "test_alert_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to test alert"
        )


def set_metrics_middleware(middleware: MetricsMiddleware):
    """Set the global metrics middleware reference"""
    global metrics_middleware
    metrics_middleware = middleware