"""
Base API router.

Provides fundamental endpoints like health checks, system status,
and API version information.

Author: AI Textbook Generator Team
Date: 2026-04-26
"""

from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db, check_db_connection
from app.config import settings


router = APIRouter()


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint.
    
    Returns simple OK status without checking external dependencies.
    Useful for load balancer health checks where we want fast responses.
    
    Returns:
        dict: Health status with timestamp
        
    Example Response:
        {
            "status": "ok",
            "timestamp": "2026-04-26T10:30:00Z"
        }
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/health/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_async_db)) -> Dict[str, Any]:
    """
    Detailed health check with dependency verification.
    
    Checks:
        - API server status
        - Database connectivity
        - Configuration validity
    
    Returns:
        dict: Detailed health status of all components
        
    Raises:
        HTTPException: If any critical component is unhealthy (500)
        
    Example Response:
        {
            "status": "healthy",
            "timestamp": "2026-04-26T10:30:00Z",
            "components": {
                "api": "ok",
                "database": "ok",
                "config": "ok"
            },
            "version": "1.0.0",
            "environment": "development"
        }
    """
    components = {}
    overall_healthy = True
    
    # Check API (always ok if this code is running)
    components["api"] = "ok"
    
    # Check database connection
    try:
        db_healthy = await check_db_connection()
        components["database"] = "ok" if db_healthy else "error"
        if not db_healthy:
            overall_healthy = False
    except Exception as e:
        components["database"] = f"error: {str(e)}"
        overall_healthy = False
    
    # Check config (verify critical settings exist)
    try:
        assert settings.SECRET_KEY, "SECRET_KEY not set"
        assert settings.DATABASE_URL, "DATABASE_URL not configured"
        components["config"] = "ok"
    except AssertionError as e:
        components["config"] = f"error: {str(e)}"
        overall_healthy = False
    
    response = {
        "status": "healthy" if overall_healthy else "unhealthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": components,
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }
    
    # Return 500 if any component is unhealthy
    if not overall_healthy:
        raise HTTPException(status_code=500, detail=response)
    
    return response


@router.get("/version")
async def get_version() -> Dict[str, str]:
    """
    Get API version information.
    
    Returns:
        dict: Version and build information
        
    Example Response:
        {
            "version": "1.0.0",
            "api": "v1",
            "environment": "development"
        }
    """
    return {
        "version": "1.0.0",
        "api": "v1",
        "environment": settings.ENVIRONMENT,
    }


@router.get("/ping")
async def ping() -> Dict[str, str]:
    """
    Simple ping endpoint.
    
    Minimal response for connectivity testing.
    
    Returns:
        dict: Pong response
        
    Example Response:
        {"message": "pong"}
    """
    return {"message": "pong"}