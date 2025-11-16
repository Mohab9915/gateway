"""
Conversations Router - Proxy conversation-related requests
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from typing import Dict, Any, List, Optional
import httpx
import time

from shared.config.settings import get_settings
from shared.utils.logger import get_service_logger
from ..dependencies import verify_api_key, get_conversation_id, get_current_user
from ..exceptions import ServiceUnavailableException

settings = get_settings("gateway")
logger = get_service_logger("conversations")

router = APIRouter()

# HTTP client for service communication
conversations_client = httpx.AsyncClient(timeout=30.0)


@router.get("/")
async def list_conversations(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """List conversations with optional filtering"""

    try:
        # Prepare query parameters
        params = {
            "limit": limit,
            "offset": offset,
        }

        if platform:
            params["platform"] = platform

        if status:
            params["status"] = status

        # Proxy request to message processor service
        response = await conversations_client.get(
            f"{settings.message_processor_url}/api/v1/conversations",
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
                "list_conversations_error",
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve conversations"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e)
        )
        raise ServiceUnavailableException("message-processor")

    except Exception as e:
        logger.error(
            "list_conversations_unexpected_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str = Depends(get_conversation_id),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Get conversation by ID"""

    try:
        # Proxy request to message processor service
        response = await conversations_client.get(
            f"{settings.message_processor_url}/api/v1/conversations/{conversation_id}",
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
                detail="Conversation not found"
            )
        else:
            logger.error(
                "get_conversation_error",
                conversation_id=conversation_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve conversation"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e),
            conversation_id=conversation_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_conversation_unexpected_error",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/")
async def create_conversation(
    conversation_data: Dict[str, Any],
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Create a new conversation"""

    try:
        # Add user context if available
        if current_user:
            conversation_data["created_by"] = current_user.get("sub")
            conversation_data["user_email"] = current_user.get("email", "")

        # Proxy request to message processor service
        response = await conversations_client.post(
            f"{settings.message_processor_url}/api/v1/conversations",
            json=conversation_data,
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
                detail="Invalid conversation data"
            )
        else:
            logger.error(
                "create_conversation_error",
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to create conversation"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e)
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "create_conversation_unexpected_error",
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str = Depends(get_conversation_id),
    conversation_data: Dict[str, Any] = None,
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Update conversation"""

    try:
        # Add user context if available
        if current_user:
            conversation_data["updated_by"] = current_user.get("sub")
            conversation_data["user_email"] = current_user.get("email", "")

        # Proxy request to message processor service
        response = await conversations_client.put(
            f"{settings.message_processor_url}/api/v1/conversations/{conversation_id}",
            json=conversation_data,
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
                detail="Conversation not found"
            )
        elif response.status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid conversation data"
            )
        else:
            logger.error(
                "update_conversation_error",
                conversation_id=conversation_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to update conversation"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e),
            conversation_id=conversation_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "update_conversation_unexpected_error",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str = Depends(get_conversation_id),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Delete conversation"""

    try:
        # Proxy request to message processor service
        response = await conversations_client.delete(
            f"{settings.message_processor_url}/api/v1/conversations/{conversation_id}",
            headers={
                "X-User-ID": current_user.get("sub") if current_user else None,
                "X-User-Email": current_user.get("email", "") if current_user else "",
            }
        )

        if response.status_code == 200:
            return {"message": "Conversation deleted successfully"}
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        else:
            logger.error(
                "delete_conversation_error",
                conversation_id=conversation_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to delete conversation"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e),
            conversation_id=conversation_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "delete_conversation_unexpected_error",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str = Depends(get_conversation_id),
    limit: int = Query(50, ge=1, le=100, description="Number of messages to return"),
    before: Optional[str] = Query(None, description="Get messages before this message ID"),
    after: Optional[str] = Query(None, description="Get messages after this message ID"),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Get messages for a specific conversation"""

    try:
        # Prepare query parameters
        params = {"limit": limit}

        if before:
            params["before"] = before

        if after:
            params["after"] = after

        # Proxy request to message processor service
        response = await conversations_client.get(
            f"{settings.message_processor_url}/api/v1/conversations/{conversation_id}/messages",
            params=params,
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
                detail="Conversation not found"
            )
        else:
            logger.error(
                "get_conversation_messages_error",
                conversation_id=conversation_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve conversation messages"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e),
            conversation_id=conversation_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_conversation_messages_unexpected_error",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{conversation_id}/analytics")
async def get_conversation_analytics(
    conversation_id: str = Depends(get_conversation_id),
    current_user: Optional[Dict] = Depends(get_current_user),
    api_key: str = Depends(verify_api_key)
):
    """Get analytics for a specific conversation"""

    try:
        # Proxy request to message processor service
        response = await conversations_client.get(
            f"{settings.message_processor_url}/api/v1/conversations/{conversation_id}/analytics",
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
                detail="Conversation not found"
            )
        else:
            logger.error(
                "get_conversation_analytics_error",
                conversation_id=conversation_id,
                status_code=response.status_code,
                response=response.text
            )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to retrieve conversation analytics"
            )

    except httpx.RequestError as e:
        logger.error(
            "conversations_service_connection_error",
            error=str(e),
            conversation_id=conversation_id
        )
        raise ServiceUnavailableException("message-processor")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_conversation_analytics_unexpected_error",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )