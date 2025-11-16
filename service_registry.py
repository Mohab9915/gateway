"""
Enhanced Service Registry with Advanced Health Monitoring
Provides service discovery, health checking, and load balancing
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import httpx
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.settings import get_settings
from shared.logging import get_structured_logger

logger = get_structured_logger(__name__)

class ServiceStatus(Enum):
    """Service health status"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

class LoadBalancingStrategy(Enum):
    """Load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    RANDOM = "random"
    HEALTH_BASED = "health_based"

@dataclass
class ServiceInstance:
    """Represents a single service instance"""
    id: str
    name: str
    host: str
    port: int
    health_endpoint: str = "/health"
    metrics_endpoint: str = "/metrics"
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_health_check: Optional[datetime] = None
    consecutive_failures: int = 0
    max_failures: int = 3
    response_time_ms: float = 0.0
    connection_count: int = 0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    @property
    def base_url(self) -> str:
        """Get base URL for service instance"""
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        """Get health check URL"""
        return f"{self.base_url}{self.health_endpoint}"

    def is_healthy(self) -> bool:
        """Check if service is considered healthy"""
        return (
            self.status in [ServiceStatus.HEALTHY, ServiceStatus.DEGRADED] and
            self.consecutive_failures < self.max_failures
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['last_health_check'] = self.last_health_check.isoformat() if self.last_health_check else None
        data['status'] = self.status.value
        data['is_healthy'] = self.is_healthy()
        return data

@dataclass
class ServiceRegistration:
    """Service registration configuration"""
    name: str
    instances: List[ServiceInstance]
    load_balancing_strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN
    health_check_interval: int = 30  # seconds
    timeout: float = 5.0
    retry_attempts: int = 2

class ServiceRegistry:
    """
    Advanced service registry with health monitoring and load balancing
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.settings = get_settings()
        self.redis_url = redis_url or self.settings.REDIS_URL
        self.redis_client: Optional[redis.Redis] = None
        self.http_client: Optional[httpx.AsyncClient] = None

        # Service registry storage
        self.services: Dict[str, ServiceRegistration] = {}
        self.instance_counters: Dict[str, int] = {}  # For round-robin

        # Background task management
        self.health_check_task: Optional[asyncio.Task] = None
        self.metrics_task: Optional[asyncio.Task] = None
        self.running = False

        # Statistics
        self.total_requests = 0
        self.total_failures = 0
        self.last_stats_reset = datetime.utcnow()

    async def start(self):
        """Start the service registry and background tasks"""
        logger.info("Starting Service Registry...")

        # Initialize Redis connection
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Using in-memory storage only.")

        # Initialize HTTP client
        self.http_client = httpx.AsyncClient(timeout=10.0)

        # Start background tasks
        self.running = True
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        self.metrics_task = asyncio.create_task(self._metrics_collection_loop())

        # Load existing services from Redis or register defaults
        await self._load_services_from_cache()
        await self._register_default_services()

        logger.info("Service Registry started successfully")

    async def stop(self):
        """Stop the service registry and cleanup"""
        logger.info("Stopping Service Registry...")

        self.running = False

        # Cancel background tasks
        if self.health_check_task:
            self.health_check_task.cancel()
        if self.metrics_task:
            self.metrics_task.cancel()

        # Close HTTP client
        if self.http_client:
            await self.http_client.aclose()

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()

        logger.info("Service Registry stopped")

    async def register_service(self, service_name: str, host: str, port: int,
                             health_endpoint: str = "/health",
                             metadata: Dict[str, Any] = None) -> str:
        """Register a new service instance"""

        instance_id = f"{service_name}_{host}_{port}_{int(time.time())}"

        instance = ServiceInstance(
            id=instance_id,
            name=service_name,
            host=host,
            port=port,
            health_endpoint=health_endpoint,
            metadata=metadata or {}
        )

        # Add to existing service registration or create new one
        if service_name not in self.services:
            self.services[service_name] = ServiceRegistration(
                name=service_name,
                instances=[instance]
            )
            self.instance_counters[service_name] = 0
        else:
            self.services[service_name].instances.append(instance)

        # Cache in Redis
        await self._cache_service_registration(service_name)

        logger.info(
            f"Registered service instance: {instance_id}",
            extra={"service_name": service_name, "host": host, "port": port}
        )

        # Perform initial health check
        await self._check_instance_health(instance)

        return instance_id

    async def deregister_service(self, service_name: str, instance_id: str) -> bool:
        """Deregister a service instance"""

        if service_name not in self.services:
            return False

        instances = self.services[service_name].instances
        original_count = len(instances)

        # Remove the instance
        self.services[service_name].instances = [
            inst for inst in instances if inst.id != instance_id
        ]

        # Remove service if no instances left
        if not self.services[service_name].instances:
            del self.services[service_name]
            del self.instance_counters[service_name]

        # Update cache
        await self._cache_service_registration(service_name)

        removed = len(self.services[service_name].instances) < original_count if service_name in self.services else True

        if removed:
            logger.info(f"Deregistered service instance: {instance_id}")

        return removed

    async def get_healthy_instance(self, service_name: str) -> Optional[ServiceInstance]:
        """Get a healthy service instance using load balancing"""

        if service_name not in self.services:
            return None

        registration = self.services[service_name]
        healthy_instances = [inst for inst in registration.instances if inst.is_healthy()]

        if not healthy_instances:
            return None

        # Apply load balancing strategy
        if registration.load_balancing_strategy == LoadBalancingStrategy.ROUND_ROBIN:
            return self._round_robin_selection(service_name, healthy_instances)
        elif registration.load_balancing_strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            return self._least_connections_selection(healthy_instances)
        elif registration.load_balancing_strategy == LoadBalancingStrategy.RANDOM:
            return self._random_selection(healthy_instances)
        elif registration.load_balancing_strategy == LoadBalancingStrategy.HEALTH_BASED:
            return self._health_based_selection(healthy_instances)
        else:
            return healthy_instances[0]

    async def get_all_healthy_instances(self, service_name: str) -> List[ServiceInstance]:
        """Get all healthy instances for a service"""

        if service_name not in self.services:
            return []

        return [inst for inst in self.services[service_name].instances if inst.is_healthy()]

    async def get_service_status(self, service_name: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive service status"""

        if service_name:
            if service_name not in self.services:
                return {"error": f"Service {service_name} not found"}

            return self._get_service_info(service_name)

        # Return status for all services
        all_services = {}
        for svc_name in self.services:
            all_services[svc_name] = self._get_service_info(svc_name)

        return {
            "total_services": len(self.services),
            "total_instances": sum(len(reg.instances) for reg in self.services.values()),
            "healthy_instances": sum(
                len([inst for inst in reg.instances if inst.is_healthy()])
                for reg in self.services.values()
            ),
            "services": all_services,
            "registry_stats": self._get_registry_stats()
        }

    async def proxy_request(self, service_name: str, method: str, path: str,
                           **kwargs) -> Tuple[Optional[httpx.Response], Optional[ServiceInstance]]:
        """Proxy request to a healthy service instance"""

        instance = await self.get_healthy_instance(service_name)
        if not instance:
            return None, None

        # Update connection count
        instance.connection_count += 1
        self.total_requests += 1

        url = f"{instance.base_url}{path}"

        try:
            response = await self.http_client.request(method, url, **kwargs)

            # Update instance metrics
            instance.response_time_ms = float(response.headers.get('X-Response-Time', 0))
            instance.connection_count -= 1

            return response, instance

        except Exception as e:
            instance.connection_count -= 1
            self.total_failures += 1

            logger.error(
                f"Request to service {service_name} failed: {str(e)}",
                extra={"instance_id": instance.id, "url": url}
            )

            # Mark instance as unhealthy after consecutive failures
            instance.consecutive_failures += 1
            if instance.consecutive_failures >= instance.max_failures:
                instance.status = ServiceStatus.UNHEALTHY

            return None, instance

    # Private methods

    async def _health_check_loop(self):
        """Background health checking loop"""

        while self.running:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(30)  # Health check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(5)

    async def _metrics_collection_loop(self):
        """Background metrics collection loop"""

        while self.running:
            try:
                await self._collect_metrics()
                await asyncio.sleep(60)  # Collect metrics every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metrics collection loop error: {e}")
                await asyncio.sleep(10)

    async def _perform_health_checks(self):
        """Perform health checks on all registered instances"""

        for service_name, registration in self.services.items():
            tasks = []
            for instance in registration.instances:
                tasks.append(self._check_instance_health(instance))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_instance_health(self, instance: ServiceInstance) -> bool:
        """Check health of a single instance"""

        try:
            start_time = time.time()

            response = await self.http_client.get(
                instance.health_url,
                timeout=5.0
            )

            response_time = (time.time() - start_time) * 1000
            instance.response_time_ms = response_time
            instance.last_health_check = datetime.utcnow()

            if response.status_code == 200:
                # Success - reset failure count
                instance.consecutive_failures = 0

                # Update status based on response time
                if response_time < 500:
                    instance.status = ServiceStatus.HEALTHY
                elif response_time < 2000:
                    instance.status = ServiceStatus.DEGRADED
                else:
                    instance.status = ServiceStatus.UNHEALTHY

                return True
            else:
                instance.consecutive_failures += 1
                instance.status = ServiceStatus.UNHEALTHY
                return False

        except Exception as e:
            instance.consecutive_failures += 1
            instance.status = ServiceStatus.UNHEALTHY
            instance.last_health_check = datetime.utcnow()

            logger.debug(
                f"Health check failed for {instance.id}: {str(e)}"
            )

            return False

    async def _collect_metrics(self):
        """Collect metrics from all instances"""

        for service_name, registration in self.services.items():
            for instance in registration.instances:
                if instance.is_healthy():
                    try:
                        response = await self.http_client.get(
                            f"{instance.base_url}{instance.metrics_endpoint}",
                            timeout=5.0
                        )

                        if response.status_code == 200:
                            metrics = response.json()
                            instance.metadata.update({
                                'last_metrics': metrics,
                                'metrics_collected_at': datetime.utcnow().isoformat()
                            })

                    except Exception as e:
                        logger.debug(f"Failed to collect metrics from {instance.id}: {e}")

    async def _cache_service_registration(self, service_name: str):
        """Cache service registration in Redis"""

        if not self.redis_client:
            return

        try:
            if service_name in self.services:
                registration = self.services[service_name]
                cache_key = f"service_registry:{service_name}"

                cache_data = {
                    'name': registration.name,
                    'instances': [inst.to_dict() for inst in registration.instances],
                    'load_balancing_strategy': registration.load_balancing_strategy.value,
                    'cached_at': datetime.utcnow().isoformat()
                }

                await self.redis_client.setex(
                    cache_key,
                    3600,  # 1 hour TTL
                    json.dumps(cache_data)
                )

        except Exception as e:
            logger.error(f"Failed to cache service registration: {e}")

    async def _load_services_from_cache(self):
        """Load service registrations from Redis cache"""

        if not self.redis_client:
            return

        try:
            keys = await self.redis_client.keys("service_registry:*")

            for key in keys:
                service_name = key.replace("service_registry:", "")
                cache_data = await self.redis_client.get(key)

                if cache_data:
                    data = json.loads(cache_data)

                    # Recreate instances
                    instances = []
                    for inst_data in data['instances']:
                        instance = ServiceInstance(**inst_data)
                        if inst_data.get('last_health_check'):
                            instance.last_health_check = datetime.fromisoformat(
                                inst_data['last_health_check']
                            )
                        instances.append(instance)

                    # Recreate registration
                    registration = ServiceRegistration(
                        name=data['name'],
                        instances=instances,
                        load_balancing_strategy=LoadBalancingStrategy(
                            data['load_balancing_strategy']
                        )
                    )

                    self.services[service_name] = registration
                    self.instance_counters[service_name] = 0

            logger.info(f"Loaded {len(self.services)} services from cache")

        except Exception as e:
            logger.error(f"Failed to load services from cache: {e}")

    async def _register_default_services(self):
        """Register default microservices"""

        default_services = [
            {"name": "message-processor", "host": "localhost", "port": 8001},
            {"name": "ai-nlp-service", "host": "localhost", "port": 8002},
            {"name": "conversation-manager", "host": "localhost", "port": 8003},
            {"name": "response-generator", "host": "localhost", "port": 8006},
        ]

        for service in default_services:
            try:
                await self.register_service(**service)
            except Exception as e:
                logger.warning(f"Failed to register default service {service['name']}: {e}")

    def _round_robin_selection(self, service_name: str, instances: List[ServiceInstance]) -> ServiceInstance:
        """Round-robin load balancing"""

        self.instance_counters[service_name] %= len(instances)
        selected_index = self.instance_counters[service_name]
        self.instance_counters[service_name] += 1

        return instances[selected_index]

    def _least_connections_selection(self, instances: List[ServiceInstance]) -> ServiceInstance:
        """Least connections load balancing"""

        return min(instances, key=lambda x: x.connection_count)

    def _random_selection(self, instances: List[ServiceInstance]) -> ServiceInstance:
        """Random load balancing"""

        import random
        return random.choice(instances)

    def _health_based_selection(self, instances: List[ServiceInstance]) -> ServiceInstance:
        """Health-based load balancing (prefer healthy with low response time)"""

        # Score instances based on health and response time
        scored_instances = []
        for instance in instances:
            score = 0
            if instance.status == ServiceStatus.HEALTHY:
                score = 100 - min(instance.response_time_ms / 10, 50)
            elif instance.status == ServiceStatus.DEGRADED:
                score = 50 - min(instance.response_time_ms / 20, 25)
            else:
                score = 10

            scored_instances.append((score, instance))

        # Return instance with highest score
        return max(scored_instances, key=lambda x: x[0])[1]

    def _get_service_info(self, service_name: str) -> Dict[str, Any]:
        """Get detailed information about a service"""

        if service_name not in self.services:
            return {"error": f"Service {service_name} not found"}

        registration = self.services[service_name]
        instances = [inst.to_dict() for inst in registration.instances]

        healthy_count = len([inst for inst in registration.instances if inst.is_healthy()])

        return {
            "name": registration.name,
            "total_instances": len(registration.instances),
            "healthy_instances": healthy_count,
            "unhealthy_instances": len(registration.instances) - healthy_count,
            "load_balancing_strategy": registration.load_balancing_strategy.value,
            "health_check_interval": registration.health_check_interval,
            "instances": instances,
            "status": "healthy" if healthy_count > 0 else "unhealthy"
        }

    def _get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""

        uptime = datetime.utcnow() - self.last_stats_reset

        return {
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "success_rate": (
                ((self.total_requests - self.total_failures) / self.total_requests * 100)
                if self.total_requests > 0 else 100
            ),
            "uptime_seconds": int(uptime.total_seconds()),
            "running": self.running
        }

# Global service registry instance
service_registry: Optional[ServiceRegistry] = None

async def get_service_registry() -> ServiceRegistry:
    """Get or create global service registry instance"""
    global service_registry

    if service_registry is None:
        service_registry = ServiceRegistry()
        await service_registry.start()

    return service_registry

async def shutdown_service_registry():
    """Shutdown the global service registry"""
    global service_registry

    if service_registry:
        await service_registry.stop()
        service_registry = None