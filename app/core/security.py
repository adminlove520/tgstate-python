import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate a password hash."""
    return pwd_context.hash(password)

def generate_session_id() -> str:
    """Generate a secure random session ID."""
    return secrets.token_urlsafe(32)

def get_session_expiry(days: int = 7) -> int:
    """Get session expiry timestamp (unix epoch)."""
    return int((datetime.now() + timedelta(days=days)).timestamp())
