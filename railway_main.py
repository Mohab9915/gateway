"""
Gateway Service for Railway Deployment
API Gateway with routing, authentication, and rate limiting
"""

import os
import asyncio
import time
import json
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import httpx
import structlog
import redis.asyncio as redis
import uuid
import hashlib
import jwt

logger = structlog.get_logger()

# Environment variables
PORT = os.getenv("PORT", "8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Service URLs (will be provided by Railway internal networking)
MESSAGE_PROCESSOR_URL = os.getenv("MESSAGE_PROCESSOR_URL", "http://message_processor:8001")
AI_NLP_URL = os.getenv("AI_NLP_URL", "http://ai-nlp-service:8002")
CONVERSATION_MANAGER_URL = os.getenv("CONVERSATION_MANAGER_URL", "http://conversation-manager:8003")
RESPONSE_GENERATOR_URL = os.getenv("RESPONSE_GENERATOR_URL", "http://response-generator:8004")

# Rate limiting settings
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "3600"))  # 1 hour

# Pydantic models
class AuthRequest(BaseModel):
    user_id: str
    api_key: Optional[str] = None

class AuthResponse(BaseModel):
    token: str
    expires_in: int
    user_id: str

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    user_id: str
    context: Dict[str, Any] = Field(default_factory=dict)
    options: List[str] = Field(default_factory=lambda: ["intent", "entities"])

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    message_id: str
    processing_time_ms: float
    metadata: Dict[str, Any] = Field(default_factory=dict)

class HealthResponse(BaseModel):
    status: str
    services: Dict[str, str]
    timestamp: datetime

# Security
security = HTTPBearer()

class RedisManager:
    """Redis connection manager for caching and rate limiting"""

    def __init__(self):
        self.client = None

    async def initialize(self):
        """Initialize Redis connection"""
        try:
            self.client = redis.from_url(REDIS_URL)
            await self.client.ping()
            logger.info("Redis connection initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {str(e)}")
            self.client = None

class RateLimiter:
    """Rate limiting implementation"""

    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager

    async def is_allowed(self, key: str, limit: int, window: int) -> bool:
        """Check if request is allowed based on rate limit"""
        if not self.redis.client:
            return True  # Allow if Redis is not available

        current_time = int(time.time())
        window_start = current_time - window

        # Remove old entries
        await self.redis.client.zremrangebyscore(key, 0, window_start)

        # Count current requests
        request_count = await self.redis.client.zcard(key)

        if request_count >= limit:
            return False

        # Add current request
        await self.redis.client.zadd(key, {str(current_time): current_time})
        await self.redis.client.expire(key, window)

        return True

class AuthService:
    """Authentication service"""

    def __init__(self):
        self.secret_key = JWT_SECRET_KEY
        self.algorithm = JWT_ALGORITHM

    def create_token(self, user_id: str) -> str:
        """Create JWT token"""
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")

class ServiceRegistry:
    """Service registry for managing downstream services"""

    def __init__(self):
        self.services = {
            "message_processor": MESSAGE_PROCESSOR_URL,
            "ai_nlp": AI_NLP_URL,
            "conversation_manager": CONVERSATION_MANAGER_URL,
            "response_generator": RESPONSE_GENERATOR_URL
        }

    async def health_check(self) -> Dict[str, str]:
        """Check health of all services"""
        health_status = {}

        async with httpx.AsyncClient(timeout=10.0) as client:
            for service_name, service_url in self.services.items():
                try:
                    response = await client.get(f"{service_url}/health")
                    health_status[service_name] = "healthy" if response.status_code == 200 else "unhealthy"
                except Exception:
                    health_status[service_name] = "unreachable"

        return health_status

class GatewayService:
    """Main gateway service"""

    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.rate_limiter = RateLimiter(redis_manager)
        self.auth_service = AuthService()
        self.service_registry = ServiceRegistry()

    async def authenticate_request(self, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
        """Authenticate incoming request"""
        token = credentials.credentials
        return self.auth_service.verify_token(token)

    async def rate_limit_request(self, user_id: str) -> bool:
        """Apply rate limiting to request"""
        key = f"rate_limit:{user_id}"
        return await self.rate_limiter.is_allowed(key, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)

    async def route_to_service(self, service_name: str, path: str, method: str = "GET", data: Dict = None, headers: Dict = None) -> Dict[str, Any]:
        """Route request to appropriate service"""
        service_url = self.service_registry.services.get(service_name)
        if not service_url:
            raise HTTPException(status_code=503, detail=f"Service {service_name} not available")

        full_url = f"{service_url}{path}"

        request_headers = {
            "Content-Type": "application/json",
            **(headers or {})
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    response = await client.get(full_url, headers=request_headers)
                elif method == "POST":
                    response = await client.post(full_url, json=data, headers=request_headers)
                elif method == "PUT":
                    response = await client.put(full_url, json=data, headers=request_headers)
                elif method == "DELETE":
                    response = await client.delete(full_url, headers=request_headers)
                else:
                    raise HTTPException(status_code=405, detail=f"Method {method} not allowed")

                response.raise_for_status()

                try:
                    return response.json()
                except:
                    return {"status": "success", "data": response.text}

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"Service {service_name} timeout")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail=f"Service {service_name} unavailable")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

# Global instances
redis_manager = RedisManager()
gateway_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global gateway_service

    logger.info("Starting Gateway Service...")

    await redis_manager.initialize()
    gateway_service = GatewayService(redis_manager)

    logger.info("Gateway Service started successfully")

    yield

    # Cleanup
    if redis_manager.client:
        await redis_manager.client.close()

    logger.info("Gateway Service shutdown complete")

# FastAPI application
app = FastAPI(
    title="Gateway Service",
    description="API Gateway for chatbot microservices",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests"""
    start_time = time.time()

    response = await call_next(request)

    process_time = time.time() - start_time
    logger.info(
        "Request processed",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code,
        process_time=process_time
    )

    response.headers["X-Process-Time"] = str(process_time)
    return response

# Routes
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Gateway Service",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    services_health = await gateway_service.service_registry.health_check()

    all_healthy = all(status == "healthy" for status in services_health.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services_health,
        timestamp=datetime.utcnow()
    )

@app.post("/auth/token", response_model=AuthResponse)
async def create_token(request: AuthRequest):
    """Create authentication token"""
    # In a real implementation, you would validate the API key
    # For now, we'll create a token for any user_id

    token = gateway_service.auth_service.create_token(request.user_id)

    return AuthResponse(
        token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user_id=request.user_id
    )

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth_data: Dict = Depends(gateway_service.authenticate_request)):
    """Main chat endpoint"""
    try:
        # Rate limiting
        if not await gateway_service.rate_limit_request(auth_data["sub"]):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        start_time = time.time()
        user_id = auth_data["sub"]

        # Create or get conversation
        if not request.conversation_id:
            conversation_data = await gateway_service.route_to_service(
                "conversation_manager",
                "/api/v1/conversations",
                method="POST",
                data={"user_id": user_id, "session_id": str(uuid.uuid4())}
            )
            conversation_id = conversation_data["id"]
        else:
            conversation_id = request.conversation_id

        # Add user message to conversation
        await gateway_service.route_to_service(
            "conversation_manager",
            f"/api/v1/conversations/{conversation_id}/messages",
            method="POST",
            data={
                "conversation_id": conversation_id,
                "content": request.message,
                "message_type": "user"
            }
        )

        # Process message through NLP
        nlp_result = await gateway_service.route_to_service(
            "ai_nlp",
            "/api/v1/process/text",
            method="POST",
            data={
                "text": request.message,
                "options": request.options,
                "context": request.context
            }
        )

        # Generate response
        response_data = await gateway_service.route_to_service(
            "response_generator",
            "/api/v1/generate",
            method="POST",
            data={
                "message": request.message,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "nlp_results": nlp_result["results"],
                "context": request.context
            }
        )

        # Add assistant message to conversation
        message_data = await gateway_service.route_to_service(
            "conversation_manager",
            f"/api/v1/conversations/{conversation_id}/messages",
            method="POST",
            data={
                "conversation_id": conversation_id,
                "content": response_data["response"],
                "message_type": "assistant",
                "metadata": response_data.get("metadata", {})
            }
        )

        processing_time = (time.time() - start_time) * 1000

        return ChatResponse(
            response=response_data["response"],
            conversation_id=conversation_id,
            message_id=message_data["message_id"],
            processing_time_ms=processing_time,
            metadata={
                "nlp_results": nlp_result["results"],
                "response_metadata": response_data.get("metadata", {})
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, auth_data: Dict = Depends(gateway_service.authenticate_request)):
    """Get conversation details"""
    try:
        return await gateway_service.route_to_service(
            "conversation_manager",
            f"/api/v1/conversations/{conversation_id}"
        )
    except Exception as e:
        logger.error(f"Error getting conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get conversation")

@app.get("/api/v1/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 50,
    auth_data: Dict = Depends(gateway_service.authenticate_request)
):
    """Get conversation messages"""
    try:
        return await gateway_service.route_to_service(
            "conversation_manager",
            f"/api/v1/conversations/{conversation_id}/messages?limit={limit}"
        )
    except Exception as e:
        logger.error(f"Error getting conversation messages: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get conversation messages")

@app.get("/api/v1/users/{user_id}/conversations")
async def get_user_conversations(
    user_id: str,
    limit: int = 10,
    auth_data: Dict = Depends(gateway_service.authenticate_request)
):
    """Get user conversations"""
    try:
        # Users can only access their own conversations
        if auth_data["sub"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return await gateway_service.route_to_service(
            "conversation_manager",
            f"/api/v1/users/{user_id}/conversations?limit={limit}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user conversations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user conversations")

@app.post("/api/v1/nlp/process")
async def process_text(
    request: Dict[str, Any],
    auth_data: Dict = Depends(gateway_service.authenticate_request)
):
    """Process text through NLP service"""
    try:
        return await gateway_service.route_to_service(
            "ai_nlp",
            "/api/v1/process/text",
            method="POST",
            data=request
        )
    except Exception as e:
        logger.error(f"Error processing text: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process text")

@app.get("/api/v1/status")
async def get_status(auth_data: Dict = Depends(gateway_service.authenticate_request)):
    """Get gateway and services status"""
    services_health = await gateway_service.service_registry.health_check()

    return {
        "gateway": "running",
        "services": services_health,
        "rate_limiting": {
            "requests_per_hour": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW
        },
        "timestamp": datetime.utcnow(),
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "railway_main:app",
        host="0.0.0.0",
        port=int(PORT),
        reload=False,
        log_level="info"
    )