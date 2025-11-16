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

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger, WebhookLogger
from shared.models.database import PlatformType
from ..dependencies import verify_api_key, webhook_rate_limit
from ..exceptions import ValidationException, AuthenticationException

settings = get_settings("gateway")
logger = get_service_logger("webhooks")
webhook_logger = WebhookLogger(logger)

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
                raise AuthenticationException("Invalid webhook signature")

        # Log webhook receipt
        webhook_logger.log_webhook_received(
            platform="facebook",
            webhook_type="messages",
            payload_size=payload_size
        )

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
        webhook_logger.log_webhook_processed(
            platform="facebook",
            webhook_type="messages",
            processing_time=processing_time,
            messages_extracted=messages_count
        )

        return {"status": "received", "messages_count": messages_count}

    except AuthenticationException as e:
        webhook_logger.log_webhook_error(
            platform="facebook",
            webhook_type="auth",
            error=str(e)
        )
        raise
    except Exception as e:
        processing_time = time.time() - start_time
        webhook_logger.log_webhook_error(
            platform="facebook",
            webhook_type="messages",
            error=str(e),
            error_type=type(e).__name__
        )
        logger.error(
            "facebook_webhook_processing_error",
            error=str(e),
            processing_time=processing_time,
            exc_info=True
        )
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
        webhook_logger.log_webhook_received(
            platform="whatsapp",
            webhook_type="messages",
            payload_size=payload_size
        )

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
        webhook_logger.log_webhook_processed(
            platform="whatsapp",
            webhook_type="messages",
            processing_time=processing_time,
            messages_extracted=messages_count
        )

        return {"status": "received", "messages_count": messages_count}

    except Exception as e:
        processing_time = time.time() - start_time
        webhook_logger.log_webhook_error(
            platform="whatsapp",
            webhook_type="messages",
            error=str(e),
            error_type=type(e).__name__
        )
        logger.error(
            "whatsapp_webhook_processing_error",
            error=str(e),
            processing_time=processing_time,
            exc_info=True
        )
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
        webhook_logger.log_webhook_received(
            platform="instagram",
            webhook_type="messages",
            payload_size=payload_size
        )

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
        webhook_logger.log_webhook_processed(
            platform="instagram",
            webhook_type="messages",
            processing_time=processing_time,
            messages_extracted=messages_count
        )

        return {"status": "received", "messages_count": messages_count}

    except Exception as e:
        processing_time = time.time() - start_time
        webhook_logger.log_webhook_error(
            platform="instagram",
            webhook_type="messages",
            error=str(e),
            error_type=type(e).__name__
        )
        logger.error(
            "instagram_webhook_processing_error",
            error=str(e),
            processing_time=processing_time,
            exc_info=True
        )
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
            logger.error(
                "facebook_message_processing_error",
                status_code=response.status_code,
                response=response.text
            )

    except Exception as e:
        logger.error(
            "facebook_message_background_processing_error",
            error=str(e),
            exc_info=True
        )


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
            logger.error(
                "whatsapp_message_processing_error",
                status_code=response.status_code,
                response=response.text
            )

    except Exception as e:
        logger.error(
            "whatsapp_message_background_processing_error",
            error=str(e),
            exc_info=True
        )


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
            logger.error(
                "instagram_message_processing_error",
                status_code=response.status_code,
                response=response.text
            )

    except Exception as e:
        logger.error(
            "instagram_message_background_processing_error",
            error=str(e),
            exc_info=True
        )


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
        logger.error(
            "facebook_message_extraction_error",
            error=str(e),
            payload_preview=str(payload)[:500]
        )

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
        logger.error(
            "whatsapp_message_extraction_error",
            error=str(e),
            payload_preview=str(payload)[:500]
        )

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
        logger.error(
            "instagram_message_extraction_error",
            error=str(e),
            payload_preview=str(payload)[:500]
        )

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