"""
Webhooks Router - Handle incoming webhooks from various platforms
"""
from fastapi import APIRouter, Request, HTTPException, status, Depends, BackgroundTasks
from fastapi.responses import Response
from typing import Dict, Any, List, Optional
import hashlib
import hmac
import json
import time
import httpx
import os

from ..dependencies import verify_api_key, webhook_rate_limit

# Simple configuration
settings = type('Settings', (), {
    'facebook_verify_token': os.getenv("FACEBOOK_VERIFY_TOKEN", "test-verify-token-12345"),
    'facebook_app_secret': os.getenv("FACEBOOK_APP_SECRET", ""),
    'message_processor_url': "https://messageprocessor-production.up.railway.app",
    'ai_nlp_service_url': "https://ai-nlp-service-production.up.railway.app"
})()

# Simple logger
class SimpleLogger:
    def info(self, msg, **kwargs):
        print(f"INFO: {msg} {kwargs}")

    def warning(self, msg, **kwargs):
        print(f"WARNING: {msg} {kwargs}")

    def error(self, msg, **kwargs):
        print(f"ERROR: {msg} {kwargs}")

logger = SimpleLogger()

router = APIRouter()

# HTTP client for service communication
webhook_client = httpx.AsyncClient(timeout=30.0)


@router.get("/facebook")
async def facebook_webhook_verify(
    request: Request,
    hub_mode: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    hub_verify_token: Optional[str] = None
):
    """Verify Facebook webhook endpoint"""

    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook verification request"
        )

    if not hub_verify_token or hub_verify_token != settings.facebook_verify_token:
        logger.warning(
            "facebook_webhook_verification_failed",
            received_token=hub_verify_token,
            expected_token=settings.facebook_verify_token
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verify token"
        )

    logger.info(
        "facebook_webhook_verified",
        challenge=hub_challenge
    )

    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/facebook")
async def facebook_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(webhook_rate_limit)
):
    """Handle Facebook webhook events"""

    start_time = time.time()

    try:
        # Get request body
        body = await request.body()
        payload_size = len(body)

        # Parse JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(
                "facebook_webhook_json_parse_error",
                error=str(e),
                body_preview=body[:200]
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )

        # Verify webhook signature (if configured)
        if settings.facebook_app_secret:
            signature = request.headers.get("x-hub-signature-256", "")
            if not verify_facebook_signature(body, signature, settings.facebook_app_secret):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Log webhook receipt
        logger.info(f"Facebook webhook received", platform="facebook", payload_size=payload_size)

        # Extract messages from payload
        messages = extract_facebook_messages(payload)
        messages_count = len(messages)

        # Process messages in background
        background_tasks.add_task(
            process_facebook_messages,
            messages,
            payload
        )

        processing_time = time.time() - start_time

        # Log successful processing
        logger.info(f"Facebook webhook processed",
                   platform="facebook",
                   processing_time=processing_time,
                   messages_extracted=messages_count)

        return {"status": "received", "messages_count": messages_count}

    except HTTPException as e:
        logger.error(f"Facebook webhook HTTP error: {str(e)}")
        raise
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Facebook webhook processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )


@router.get("/whatsapp")
async def whatsapp_webhook_verify(
    request: Request,
    hub_mode: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    hub_verify_token: Optional[str] = None
):
    """Verify WhatsApp webhook endpoint"""

    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook verification request"
        )

    if not hub_verify_token or hub_verify_token != settings.facebook_verify_token:  # WhatsApp uses same verify token
        logger.warning(
            "whatsapp_webhook_verification_failed",
            received_token=hub_verify_token,
            expected_token=settings.facebook_verify_token
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verify token"
        )

    logger.info(
        "whatsapp_webhook_verified",
        challenge=hub_challenge
    )

    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/whatsapp")
async def whatsapp_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(webhook_rate_limit)
):
    """Handle WhatsApp webhook events"""

    start_time = time.time()

    try:
        # Get request body
        body = await request.body()
        payload_size = len(body)

        # Parse JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(
                "whatsapp_webhook_json_parse_error",
                error=str(e),
                body_preview=body[:200]
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )

        # Log webhook receipt
        logger.info(f"WhatsApp webhook received", platform="whatsapp", payload_size=payload_size)

        # Extract messages from payload
        messages = extract_whatsapp_messages(payload)
        messages_count = len(messages)

        # Process messages in background
        background_tasks.add_task(
            process_whatsapp_messages,
            messages,
            payload
        )

        processing_time = time.time() - start_time

        # Log successful processing
        logger.info(f"WhatsApp webhook processed",
                   platform="whatsapp",
                   processing_time=processing_time,
                   messages_extracted=messages_count)

        return {"status": "received", "messages_count": messages_count}

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"WhatsApp webhook processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )


@router.post("/instagram")
async def instagram_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(webhook_rate_limit)
):
    """Handle Instagram webhook events"""

    start_time = time.time()

    try:
        # Get request body
        body = await request.body()
        payload_size = len(body)

        # Parse JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(
                "instagram_webhook_json_parse_error",
                error=str(e),
                body_preview=body[:200]
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )

        # Log webhook receipt
        logger.info(f"Instagram webhook received", platform="instagram", payload_size=payload_size)

        # Extract messages from payload
        messages = extract_instagram_messages(payload)
        messages_count = len(messages)

        # Process messages in background
        background_tasks.add_task(
            process_instagram_messages,
            messages,
            payload
        )

        processing_time = time.time() - start_time

        # Log successful processing
        logger.info(f"Instagram webhook processed",
                   platform="instagram",
                   processing_time=processing_time,
                   messages_extracted=messages_count)

        return {"status": "received", "messages_count": messages_count}

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Instagram webhook processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )


# Background processing functions
async def process_facebook_messages(messages: List[Dict[str, Any]], raw_payload: Dict[str, Any]):
    """Process Facebook messages in background"""

    try:
        # Send to message processor service
        response = await webhook_client.post(
            f"{settings.message_processor_url}/api/v1/webhooks/facebook",
            json={
                "messages": messages,
                "raw_payload": raw_payload,
                "platform": "facebook",
                "timestamp": time.time()
            }
        )

        if response.status_code != 200:
            logger.error(f"Facebook message processing error: {response.status_code}")

    except Exception as e:
        logger.error(f"Facebook message background processing error: {str(e)}")


async def process_whatsapp_messages(messages: List[Dict[str, Any]], raw_payload: Dict[str, Any]):
    """Process WhatsApp messages in background"""

    try:
        # Send to message processor service
        response = await webhook_client.post(
            f"{settings.message_processor_url}/api/v1/webhooks/whatsapp",
            json={
                "messages": messages,
                "raw_payload": raw_payload,
                "platform": "whatsapp",
                "timestamp": time.time()
            }
        )

        if response.status_code != 200:
            logger.error(f"WhatsApp message processing error: {response.status_code}")

    except Exception as e:
        logger.error(f"WhatsApp message background processing error: {str(e)}")


async def process_instagram_messages(messages: List[Dict[str, Any]], raw_payload: Dict[str, Any]):
    """Process Instagram messages in background"""

    try:
        # Send to message processor service
        response = await webhook_client.post(
            f"{settings.message_processor_url}/api/v1/webhooks/instagram",
            json={
                "messages": messages,
                "raw_payload": raw_payload,
                "platform": "instagram",
                "timestamp": time.time()
            }
        )

        if response.status_code != 200:
            logger.error(f"Instagram message processing error: {response.status_code}")

    except Exception as e:
        logger.error(f"Instagram message background processing error: {str(e)}")


# Message extraction functions
def extract_facebook_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract messages from Facebook webhook payload"""

    messages = []

    try:
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                if "message" in messaging:
                    message_data = {
                        "sender_id": messaging["sender"]["id"],
                        "recipient_id": messaging["recipient"]["id"],
                        "message_id": messaging["message"]["mid"],
                        "text": messaging["message"].get("text", ""),
                        "timestamp": messaging.get("timestamp"),
                        "seq": messaging["message"].get("seq", 0),
                        "platform": "facebook",
                        "page_id": entry["id"]
                    }

                    # Add attachments if present
                    if "attachments" in messaging["message"]:
                        message_data["attachments"] = messaging["message"]["attachments"]

                    messages.append(message_data)

    except Exception as e:
        logger.error(f"Facebook message extraction error: {str(e)}")

    return messages


def extract_whatsapp_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract messages from WhatsApp webhook payload"""

    messages = []

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if "messages" in change.get("value", {}):
                    for message in change["value"]["messages"]:
                        message_data = {
                            "sender_id": message["from"],
                            "recipient_id": change["value"]["metadata"]["phone_number_id"],
                            "message_id": message["id"],
                            "text": message.get("text", {}).get("body", ""),
                            "timestamp": message.get("timestamp"),
                            "platform": "whatsapp",
                            "phone_number_id": change["value"]["metadata"]["phone_number_id"]
                        }

                        # Add message type
                        if "type" in message:
                            message_data["message_type"] = message["type"]

                        messages.append(message_data)

    except Exception as e:
        logger.error(f"WhatsApp message extraction error: {str(e)}")

    return messages


def extract_instagram_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract messages from Instagram webhook payload"""

    messages = []

    try:
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                if "message" in messaging:
                    message_data = {
                        "sender_id": messaging["sender"]["id"],
                        "recipient_id": messaging["recipient"]["id"],
                        "message_id": messaging["message"]["mid"],
                        "text": messaging["message"].get("text", ""),
                        "timestamp": messaging.get("timestamp"),
                        "platform": "instagram",
                        "page_id": entry["id"]
                    }

                    messages.append(message_data)

    except Exception as e:
        logger.error(f"Instagram message extraction error: {str(e)}")

    return messages


def verify_facebook_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Verify Facebook webhook signature"""

    if not signature.startswith("sha256="):
        return False

    expected_signature = hmac.new(
        app_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(
        signature,
        f"sha256={expected_signature}"
    )