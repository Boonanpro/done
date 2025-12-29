"""
JWT Authentication Service for Done Chat
Supports both Bearer token and HttpOnly Cookie authentication
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple
from jose import JWTError, jwt
import bcrypt
import secrets
from pydantic import BaseModel

from app.config import settings


class TokenData(BaseModel):
    """JWT Token payload"""
    user_id: str
    email: str
    exp: datetime


class TokenPair(BaseModel):
    """Access token and refresh token pair"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


def get_jwt_secret() -> str:
    """Get JWT secret key (falls back to APP_SECRET_KEY)"""
    return settings.JWT_SECRET_KEY or settings.APP_SECRET_KEY


def get_refresh_secret() -> str:
    """Get refresh token secret (derived from JWT secret)"""
    return get_jwt_secret() + "_refresh"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    password_bytes = plain_password.encode('utf-8')[:72]  # bcrypt 72-byte limit
    return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    password_bytes = password.encode('utf-8')[:72]  # bcrypt 72-byte limit
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def create_access_token(user_id: str, email: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "type": "access",
    }
    encoded_jwt = jwt.encode(to_encode, get_jwt_secret(), algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(user_id: str, email: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT refresh token (longer-lived)"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),  # Unique token ID for revocation
    }
    encoded_jwt = jwt.encode(to_encode, get_refresh_secret(), algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_token_pair(user_id: str, email: str, remember_me: bool = False) -> TokenPair:
    """Create both access and refresh tokens"""
    access_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_expires = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS if remember_me else 1)
    
    access_token = create_access_token(user_id, email, access_expires)
    refresh_token = create_refresh_token(user_id, email, refresh_expires)
    
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(access_expires.total_seconds()),
    )


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT access token"""
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
        
        # Verify it's an access token
        if payload.get("type") != "access":
            # For backwards compatibility, allow tokens without type
            if "type" in payload:
                return None
        
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        exp: datetime = datetime.fromtimestamp(payload.get("exp"))
        
        if user_id is None:
            return None
        
        return TokenData(user_id=user_id, email=email, exp=exp)
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT refresh token"""
    try:
        payload = jwt.decode(token, get_refresh_secret(), algorithms=[settings.JWT_ALGORITHM])
        
        # Verify it's a refresh token
        if payload.get("type") != "refresh":
            return None
        
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        exp: datetime = datetime.fromtimestamp(payload.get("exp"))
        
        if user_id is None:
            return None
        
        return TokenData(user_id=user_id, email=email, exp=exp)
    except JWTError:
        return None


def refresh_tokens(refresh_token: str) -> Optional[TokenPair]:
    """
    Refresh access token using refresh token.
    Returns new token pair (token rotation for security).
    """
    token_data = decode_refresh_token(refresh_token)
    if not token_data:
        return None
    
    # Create new token pair (rotation)
    return create_token_pair(token_data.user_id, token_data.email, remember_me=True)
