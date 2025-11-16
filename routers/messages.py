"""
Messages Router - Proxy message-related requests
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from typing import Dict, Any, List, Optional
import httpx
import time

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger
from ..dependencies import verify_api_key, get_conversation_id, get_current_user, validate_message_content
from ..exceptions import ServiceUnavailableException

settings = get_settings("gateway")
logger = get_service_logger("messages")

router = APIRouter()

# HTTP client for service communication
messages_client = httpx.AsyncClient(timeout=30.0)


@router.post("/")
async def send_message(
    message_data: Dict[str, Any],
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Send a message to a conversation"""

    try:
        # Validate required fields
        if "conversation_id" not in message_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="conversation_id is required"
            )

        if "content" not in message_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="content is required"
            )

        # Validate message content
        await validate_message_content(message_data["content"])

        # Add user context if available
        if current_user:
            message_data["sender_id"] = current_user.get("sub")
            message_data["sender_email"] = current_user.get("email", "")

        # Set default message type if not specified
        if "message_type" not in message_data:
            message_data["message_type"] = "text"

        # Proxy request to message processor service
        response = await messages_client.post(
            f"{settings.message_processor_url}/api/v1/messages",
            json=message_data,
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 201:
            return response.json()
        elif response.status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid message data"
            )
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        else:
            logger.error(
                "send_message_error",
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to send message"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "send_message_unexpected_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{message_id}")
async def get_message(
    message_id: str = Path(..., description="Message ID"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Get message by ID"""

    try:
        # Proxy request to message processor service
        response = await messages_client.get(
            f"{settings.message_processor_url}/api/v1/messages/{message_id}",
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        else:
            logger.error(
                "get_message_error",
                message_id=message_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve message"
            )

    except httpx.RequestError as e:
        logger.error(
            "messages_service_connection_error",
            error=str(e),
            message_id=message_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_message_unexpected_error",
            message_id=message_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.put("/{message_id}")
async def update_message(
    message_id: str = Path(..., description="Message ID"),
    message_data: Dict[str, Any] = None,
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Update message (typically for status updates)"""

    try:
        # Add user context if available
        if current_user:
            message_data["updated_by"] = current_user.get("sub")
            message_data["user_email"] = current_user.get("email", "")

        # Proxy request to message processor service
        response = await messages_client.put(
            f"{settings.message_processor_url}/api/v1/messages/{message_id}",
            json=message_data,
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        elif response.status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid message data"
            )
        else:
            logger.error(
                "update_message_error",
                message_id=message_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to update message"
            )

    except httpx.RequestError as e:
        logger.error(
            "messages_service_connection_error",
            error=str(e),
            message_id=message_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "update_message_unexpected_error",
            message_id=message_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/{message_id}/mark-seen")
async def mark_message_as_seen(
    message_id: str = Path(..., description="Message ID"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Mark message as seen"""

    try:
        # Proxy request to message processor service
        response = await messages_client.post(
            f"{settings.message_processor_url}/api/v1/messages/{message_id}/mark-seen",
            json={
                "seen_by": current_user.get("sub") if current_user else None,
                "seen_at": time.time()
            },
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        else:
            logger.error(
                "mark_message_seen_error",
                message_id=message_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to mark message as seen"
            )

    except httpx.RequestError as e:
        logger.error(
            "messages_service_connection_error",
            error=str(e),
            message_id=message_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "mark_message_seen_unexpected_error",
            message_id=message_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/")
async def list_messages(
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    platform: Optional[str] = Query(None, description="Filter by platform"),
    message_type: Optional[str] = Query(None, description="Filter by message type"),
    direction: Optional[str] = Query(None, description="Filter by direction (inbound/outbound)"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """List messages with optional filtering"""

    try:
        # Prepare query parameters
        params = {
            "limit": limit,
            "offset": offset,
        }

        if conversation_id:
            params["conversation_id"] = conversation_id

        if platform:
            params["platform"] = platform

        if message_type:
            params["message_type"] = message_type

        if direction:
            params["direction"] = direction

        # Proxy request to message processor service
        response = await messages_client.get(
            f"{settings.message_processor_url}/api/v1/messages",
            params=params,
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                "list_messages_error",
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve messages"
            )

    except httpx.RequestError as e:
        logger.error(
            "messages_service_connection_error",
            error=str(e)
        )
        raise ServiceUnavailableException("message-processor")

    except Exception as e:
        logger.error(
            "list_messages_unexpected_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/search")
async def search_messages(
    query: str = Query(..., description="Search query"),
    conversation_id: Optional[str] = Query(None, description="Search within specific conversation"),
    platform: Optional[str] = Query(None, description="Search within specific platform"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Search messages by content"""

    try:
        # Prepare query parameters
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
        }

        if conversation_id:
            params["conversation_id"] = conversation_id

        if platform:
            params["platform"] = platform

        # Proxy request to message processor service
        response = await messages_client.get(
            f"{settings.message_processor_url}/api/v1/messages/search",
            params=params,
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                "search_messages_error",
                query=query,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to search messages"
            )

    except httpx.RequestError as e:
        logger.error(
            "messages_service_connection_error",
            error=str(e),
            query=query
        )
        raise ServiceUnavailableException("message-processor")

    except Exception as e:
        logger.error(
            "search_messages_unexpected_error",
            query=query,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )