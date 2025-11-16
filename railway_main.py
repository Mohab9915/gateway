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

# Advanced AI Response Generator using Qwen model
async def generate_human_response(original_text: str, intent: str, entities: list = None, language: str = "en") -> str:
    """Generate truly human-like responses using Qwen model with Palestinian/Jordanian personality"""

    # OpenRouter API configuration
    global OPENROUTER_API_KEY

    # Extract entities for context
    entity_context = ""
    if entities:
        entity_context = "\nContext: User mentioned: " + ", ".join([f"{e.get('text')} ({e.get('type')})" for e in entities[:3]])

    # Advanced prompt for human-like Palestinian personality
    prompt = f"""You are a Palestinian/Jordanian shop owner named "Abu Ahmad" - you run a small electronics shop in Amman. You're 45 years old, friendly, warm, and speak naturally with Palestinian/Jordanian dialect and cultural expressions.

Your personality:
- Warm and welcoming, uses "يا هلا", "أهلاً", "برافو عليك" naturally
- Uses Palestinian/Jordanian expressions like "يا حليلك", "شغل شايب", "لأ ولأ"
- Negotiates prices naturally like a real shop owner
- Sometimes switches to English for tech terms but mostly Arabic
- Never sounds like a robot or template - always natural and conversational
- Uses emojis naturally and sparingly 😊 👍
- Occasionally uses cultural references and local expressions

Customer message: "{original_text}"
Detected intent: {intent}{entity_context}

Respond naturally as Abu Ahmad would - short, friendly, human-like response. Don't be overly formal or use templates. Just talk like a real shop owner would."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://railway.app",
                    "X-Title": "Palestinian Chatbot"
                },
                json={
                    "model": "qwen/qwen-2.5-coder-32b-instruct",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are Abu Ahmad, a Palestinian/Jordanian electronics shop owner. Be natural, warm, and use authentic dialect. Never sound like a bot or template."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.9,
                    "max_tokens": 150,
                    "top_p": 0.95,
                    "frequency_penalty": 0.2,
                    "presence_penalty": 0.1
                }
            )

            if response.status_code == 200:
                result = response.json()
                ai_response = result["choices"][0]["message"]["content"].strip()

                # Clean up the response - remove any obvious AI patterns
                ai_response = ai_response.replace("As Abu Ahmad", "").replace("As a shop owner", "")
                ai_response = ai_response.replace("I would say", "").replace("Let me think", "")
                ai_response = re.sub(r'\[.*?\]', '', ai_response)  # Remove bracketed content
                ai_response = ai_response.strip()

                return ai_response if ai_response else "يا هلا! كيف يمكنني أخدمك؟"
            else:
                logger.warning("OpenRouter API error", status=response.status_code, response=response.text)
                return get_fallback_palestinian_response(original_text, intent, entities)

    except Exception as e:
        logger.error("Failed to generate AI response", error=str(e)
        return get_fallback_palestinian_response(original_text, intent, entities)

def get_fallback_palestinian_response(original_text: str, intent: str, entities: list = None) -> str:
    """Fallback responses when AI is not available"""

    # More natural fallback responses
    responses = {
        "greeting": ["يا هلا! كيفك؟ تفضل اكتب لي", "أهلاً وسهلا! شو بدك بالزمن؟", "مرحباً! شو أخبارك؟"],
        "product_inquiry": ["شو بتدور عليه بالضبط؟ عندي كل شء", "يلا! شو نوع السلعة؟ بفهمك اللي بدك", "أكيد! شو المودل أو النوع؟"],
        "price_inquiry": ["الأسعار كويسة جداً! شو الميزان بتدور عليه؟", "الأمور زينة! شو ميزاتك؟", "برافو! شو المواصفات كلها؟"],
        "support_request": ["لأ ولأ! شو المشكلة؟ أنا موجود", "يا حبيبي! إكتب لي القصة", "خليك بخير! شو في الأمر؟"],
        "buying_intent": ["برافو! هون المكان صح! شو بتحب؟", "ماشي الله! شو بدك بالضبط؟", "يلا صاحبي! شو عندك بالزمن؟"],
    }

    # Detect if Arabic text
    is_arabic = any(char in original_text for char in 'ابتجحخدرزسشصضطظعغفقكلمنهوىي')

    if intent in responses:
        return random.choice(responses[intent])
    elif is_arabic:
        return random.choice(["يا هلا! كيف يمكنني أخدمك؟", "شو بدك بالضبط؟ بكل سرور أساعدك", "تفضل! كيف أقدر أساعدك؟"])
    else:
        return random.choice(["Hey there! How can I help you today?", "What can I do for you?", "Welcome! What are you looking for?"])

# Backward compatibility function
def generate_palestinian_response(original_text: str, intent: str, entities: list = None, language: str = "en") -> str:
    """Wrapper for the async function - simplified version for now"""
    # For now return a fallback response, the actual AI generation is async
    return get_fallback_palestinian_response(original_text, intent, entities)

import re

import random

# Flexible Specialist Response Generator
async def generate_specialist_response(
    original_text: str,
    intent: str,
    entities: list = None,
    language: str = "en",
    product_info: str = "",
    product_name: str = "منتج",
    specialist_name: str = "خالد"
) -> str:
    """Generate response as configurable specialist using Qwen model"""

    global OPENROUTER_API_KEY

    entity_context = ""
    if entities:
        entity_context = "\nالمعلومات المذكورة: " + ", ".join([f"{e.get('text')} ({e.get('type')})" for e in entities[:3]])

    prompt = f"""أنت {specialist_name}، متخصص خدمة عملاء فلسطيني محترف. شغلك الرد على استفسارات الزبائن عن: {product_name}.

شخصيتك:
- اسمك {specialist_name}، متخصص في هذا المنتج
- تتحدث باللهجة الفلسطينية الطبيعية
- أسلوبك مهني وبسيط، لغة واضحة ومباشرة
- دائماً ودود ومساعد

قواعد مهمة:
- رد دائماً عن المنتج المذكور فقط
- استخدم معلومات المنتج المعتمدة
- رد باللهجة الفلسطينية
- كن مهني وبسيط
- لا تخلق معلومات غير موجودة

معلومات المنتج:
{product_info}

رسالة الزبون: "{original_text}"
النية المحتسبة: {intent}{entity_context}

رد كـ{specialist_name} - استخدم اللهجة الفلسطينية المهنية، كن دقيقاً، رد بشكل طبيعي وودود.

مهم جداً: رد قصير جداً (جملة أو جملتين كحد أقصى)، مباشر، ومختصر. فقط أجب عن السؤال مباشرة."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://railway.app",
                    "X-Title": f"{specialist_name} - Specialist"
                },
                json={
                    "model": "qwen/qwen-2.5-coder-32b-instruct",
                    "messages": [
                        {
                            "role": "system",
                            "content": f"أنت {specialist_name}، متخصص خدمة عملاء فلسطيني. رد قصير ومباشر باللهجة الفلسطينية. لا تطيل ولا تشرح."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.5,
                    "max_tokens": 80,
                    "top_p": 0.8,
                    "frequency_penalty": 0.3,
                    "presence_penalty": 0.2
                }
            )

            if response.status_code == 200:
                result = response.json()
                ai_response = result["choices"][0]["message"]["content"].strip()
                ai_response = ai_response.replace(f"كـ{specialist_name}", "").replace(f"أنا {specialist_name}", "")
                ai_response = ai_response.replace("أود أن أقول", "")
                ai_response = re.sub(r'\[.*?\]', '', ai_response)
                ai_response = ai_response.strip()
                return ai_response if ai_response else f"أهلاً بك! كيف يمكنني أخدمك؟"
            else:
                logger.warning("OpenRouter API error", status=response.status_code)
                return get_specialist_fallback_response(original_text, intent, specialist_name)

    except Exception as e:
        logger.error("Failed to generate specialist response", error=str(e))
        return get_specialist_fallback_response(original_text, intent, specialist_name)

def get_specialist_fallback_response(original_text: str, intent: str, specialist_name: str = "خالد") -> str:
    """Fallback responses for specialist when AI is not available"""

    responses = {
        "greeting": [f"أهلاً بك! أنا {specialist_name}، كيف يمكنني أخدمك؟"],
        "product_inquiry": ["أكيد! شو بدك تعرف عن المنتج؟"],
        "price_inquiry": ["الأسعار كويسة جداً! شو بتحب تعرف؟"],
        "support_request": ["لاء ولأ! شو المشكلة؟ أنا موجود."],
        "buying_intent": ["ماشي الله! هون المكان صح."],
    }

    is_arabic = any(char in original_text for char in 'ابتجحخدرزسشصضطظعغفقكلمنهوىي')

    if intent in responses:
        return responses[intent][0]
    elif is_arabic:
        return "أهلاً بك! كيف يمكنني أخدمك؟"
    else:
        return "Hello! How can I help you?"

# Environment variables
PORT = os.getenv("PORT", "8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")

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
gateway_service: GatewayService = None

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

# Dependency injection
def get_gateway_service() -> GatewayService:
    """Get gateway service instance"""
    if gateway_service is None:
        raise HTTPException(status_code=503, detail="Gateway service not initialized")
    return gateway_service

def get_auth_service() -> AuthService:
    """Get auth service instance"""
    service = get_gateway_service()
    return service.auth_service

async def authenticate_request(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Authenticate incoming request"""
    auth_service = get_auth_service()
    token = credentials.credentials
    return auth_service.verify_token(token)

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
    service = get_gateway_service()
    services_health = await service.service_registry.health_check()

    all_healthy = all(status == "healthy" for status in services_health.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services_health,
        timestamp=datetime.utcnow()
    )

@app.post("/auth/token", response_model=AuthResponse)
async def create_token(request: AuthRequest, service: GatewayService = Depends(get_gateway_service)):
    """Create authentication token"""
    # In a real implementation, you would validate the API key
    # For now, we'll create a token for any user_id

    token = service.auth_service.create_token(request.user_id)

    return AuthResponse(
        token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user_id=request.user_id
    )

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, auth_data: Dict = Depends(authenticate_request)):
    """Main chat endpoint"""
    try:
        service = get_gateway_service()

        # Rate limiting
        if not await service.rate_limit_request(auth_data["sub"]):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        start_time = time.time()
        user_id = auth_data["sub"]

        # Create or get conversation
        if not request.conversation_id:
            conversation_data = await service.route_to_service(
                "conversation_manager",
                "/api/v1/conversations",
                method="POST",
                data={"user_id": user_id, "session_id": str(uuid.uuid4())}
            )
            conversation_id = conversation_data["id"]
        else:
            conversation_id = request.conversation_id

        # Add user message to conversation
        await service.route_to_service(
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
        nlp_result = await service.route_to_service(
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
        response_data = await service.route_to_service(
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
        message_data = await service.route_to_service(
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
async def get_conversation(conversation_id: str, auth_data: Dict = Depends(authenticate_request)):
    """Get conversation details"""
    try:
        service = get_gateway_service()
        return await service.route_to_service(
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
    auth_data: Dict = Depends(authenticate_request)
):
    """Get conversation messages"""
    try:
        service = get_gateway_service()
        return await service.route_to_service(
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
    auth_data: Dict = Depends(authenticate_request)
):
    """Get user conversations"""
    try:
        # Users can only access their own conversations
        if auth_data["sub"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        service = get_gateway_service()
        return await service.route_to_service(
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
    auth_data: Dict = Depends(authenticate_request)
):
    """Process text through NLP service"""
    try:
        service = get_gateway_service()
        return await service.route_to_service(
            "ai_nlp",
            "/api/v1/process/text",
            method="POST",
            data=request
        )
    except Exception as e:
        logger.error(f"Error processing text: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process text")

@app.get("/api/v1/status")
async def get_status(auth_data: Dict = Depends(authenticate_request)):
    """Get gateway and services status"""
    service = get_gateway_service()
    services_health = await service.service_registry.health_check()

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

# Facebook Webhook Endpoints
@app.get("/webhooks/facebook")
async def facebook_webhook_verify(request: Request):
    """Verify Facebook webhook endpoint"""

    # Get query parameters - Facebook uses dots in parameter names
    query_params = dict(request.query_params)

    # Facebook sends: hub.mode, hub.challenge, hub.verify_token
    mode = query_params.get("hub.mode") or query_params.get("hub_mode")
    challenge = query_params.get("hub.challenge") or query_params.get("hub_challenge")
    verify_token_param = query_params.get("hub.verify_token") or query_params.get("hub_verify_token")

    # Get verify token from environment or fallback
    expected_token = os.getenv("FACEBOOK_VERIFY_TOKEN", "test-verify-token-12345")

    logger.info("Facebook webhook verification request",
                mode=mode,
                challenge=challenge,
                verify_token=verify_token_param,
                expected_token=expected_token,
                query_params=query_params)

    if mode != "subscribe" or not challenge:
        logger.warning("Invalid webhook verification parameters",
                     mode=mode,
                     challenge=challenge,
                     query_params=query_params)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook verification request"
        )

    if not verify_token_param or verify_token_param != expected_token:
        logger.warning("Facebook webhook token mismatch",
                      received=verify_token_param,
                      expected=expected_token)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verify token"
        )

    logger.info("Facebook webhook verified successfully", challenge=challenge)
    return Response(content=challenge, media_type="text/plain")

@app.post("/webhooks/facebook")
async def facebook_webhook_handler(request: Request):
    """Handle Facebook webhook events"""

    try:
        # Get request body
        body = await request.body()
        payload = json.loads(body.decode('utf-8'))

        logger.info("Facebook webhook received", payload_size=len(body))

        # Extract messages from payload
        messages = []
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                if "message" in messaging and "text" in messaging["message"]:
                    message_data = {
                        "sender_id": messaging["sender"]["id"],
                        "recipient_id": messaging["recipient"]["id"],
                        "message_id": messaging["message"]["mid"],
                        "text": messaging["message"]["text"],
                        "timestamp": messaging.get("timestamp"),
                        "platform": "facebook",
                        "page_id": entry["id"]
                    }
                    messages.append(message_data)

        logger.info("Facebook messages extracted", count=len(messages))

        # Process each message (send to AI service for analysis and response generation)
        responses = []
        for message in messages:
            try:
                # Forward to AI/NLP service for processing
                ai_nlp_url = os.getenv("AI_NLP_URL", "https://ai-nlp-service-production.up.railway.app")
                response_generator_url = os.getenv("RESPONSE_GENERATOR_URL", "https://responce-generator-production.up.railway.app")

                # Step 1: Analyze message with AI/NLP service
                async with httpx.AsyncClient(timeout=30.0) as client:
                    ai_response = await client.post(
                        f"{ai_nlp_url}/api/v1/process/text",
                        json={
                            "text": message["text"],
                            "features": ["intent", "entities", "sentiment", "language"]
                        }
                    )

                    if ai_response.status_code != 200:
                        logger.warning("AI service returned error",
                                     status_code=ai_response.status_code,
                                     response=ai_response.text)
                        continue

                    ai_result = ai_response.json()

                    # Step 2: Forward to AI-NLP service for response generation
                    intent = ai_result['results']['intent']['intent']
                    entities = ai_result['results'].get('entities', {}).get('entities', [])
                    detected_language = ai_result['results'].get('language', {}).get('language', 'en')
                    original_text = message["text"]

                    # Get configurable product info from environment
                    product_info = os.getenv("PRODUCT_INFO", "")
                    product_name = os.getenv("PRODUCT_NAME", "منتج")
                    specialist_name = os.getenv("SPECIALIST_NAME", "خالد")

                    # Forward to AI-NLP service for response generation
                    ai_nlp_url = os.getenv("AI_NLP_URL", "https://ai-nlp-service-production.up.railway.app")

                    response_data = {
                        "text": original_text,
                        "intent": intent,
                        "entities": entities,
                        "language": detected_language,
                        "product_info": product_info,
                        "product_name": product_name,
                        "specialist_name": specialist_name,
                        "task": "generate_response"
                    }

                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            ai_response = await client.post(
                                f"{ai_nlp_url}/api/v1/generate-response",
                                json=response_data,
                                timeout=30.0
                            )

                            if ai_response.status_code == 200:
                                result = ai_response.json()
                                bot_response = result.get("response", "أهلاً بك! كيف يمكنني أخدمك؟")
                            else:
                                logger.warning("AI-NLP service error", status=ai_response.status_code, response=ai_response.text)
                                bot_response = "خدمة الذكاء الاصطناعي غير متاحة حالياً. برجع لاحقاً."

                    except Exception as e:
                        logger.error("Failed to call AI-NLP service", error=str(e))
                        bot_response = "حدث خطأ في معالجة الطلب. برجع لاحقاً."

                    responses.append({
                        "recipient_id": message["sender_id"],
                        "message_text": bot_response,
                        "original_message": message["text"],
                        "intent": intent,
                        "confidence": ai_result['results']['intent']['confidence']
                    })

                    logger.info("AI-powered response generated",
                               sender_id=message["sender_id"],
                               original_text=original_text,
                               intent=intent,
                               language=detected_language,
                               bot_response=bot_response)

            except Exception as e:
                logger.error("Failed to process message with AI services",
                           error=str(e),
                           sender_id=message["sender_id"])
                # Fallback response
                responses.append({
                    "recipient_id": message["sender_id"],
                    "message_text": "I'm here to help! Could you tell me more about what you need?",
                    "original_message": message["text"],
                    "error": str(e)
                })

        # For Facebook webhooks, we need to return a structured response
        # But the actual response content should be in the message_text field
        return {
            "status": "ok",
            "messages_processed": len(messages),
            "responses_generated": len(responses),
            "responses": responses,
            "timestamp": datetime.utcnow().isoformat()
        }

    except json.JSONDecodeError:
        logger.error("Invalid JSON in Facebook webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except Exception as e:
        logger.error("Facebook webhook processing error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "railway_main:app",
        host="0.0.0.0",
        port=int(PORT),
        reload=False,
        log_level="info"
    )