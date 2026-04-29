"""
JWT token utilities.

Handles creation, verification, and decoding of JSON Web Tokens for authentication.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

# HTTPBearer security scheme for FastAPI
security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload data to encode (typically {"sub": user_id})
        expires_delta: Optional custom expiration time
        
    Returns:
        Encoded JWT token string
        
    Example:
        >>> token = create_access_token({"sub": "123"})
        >>> print(token)
        eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    to_encode = data.copy()
    
    # Set expiration time (timezone-aware)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    to_encode.update({"exp": expire})
    
    # Encode token
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt


def verify_token(token: str) -> dict | None:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string to verify
        
    Returns:
        Decoded payload dict if valid, None if invalid/expired
        
    Example:
        >>> token = create_access_token({"sub": "123"})
        >>> payload = verify_token(token)
        >>> print(payload)
        {'sub': '123', 'exp': 1234567890}
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def decode_token(token: str) -> int:
    """
    Decode JWT token and extract user ID.
    
    Args:
        token: JWT token string
        
    Returns:
        User ID as integer
        
    Raises:
        HTTPException: If token is invalid or user_id missing
        
    Example:
        >>> token = create_access_token({"sub": "123"})
        >>> user_id = decode_token(token)
        >>> print(user_id)
        123
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID"
            )
        return int(user_id)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """
    FastAPI dependency to get current user ID from Bearer token.
    
    Extracts user ID from Authorization header: "Bearer <token>"
    Used as a dependency in protected route handlers.
    
    Args:
        credentials: HTTP Authorization header with Bearer token
        
    Returns:
        User ID as integer
        
    Raises:
        HTTPException: If token is invalid or missing
        
    Usage:
        @router.get("/protected")
        async def protected_route(user_id: int = Depends(get_current_user_id)):
            return {"user_id": user_id}
    """
    return decode_token(credentials.credentials)