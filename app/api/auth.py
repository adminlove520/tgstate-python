import time
from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from ..core.config import get_app_settings
from ..core.security import verify_password, generate_session_id, get_session_expiry
from .. import database

router = APIRouter()

class LoginRequest(BaseModel):
    password: str

COOKIE_NAME = "tgstate_session"

# Simple in-memory rate limiter
# IP -> list of timestamps
login_attempts = {}
MAX_ATTEMPTS = 10
TIME_WINDOW = 300  # 5 minutes

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = login_attempts.get(ip, [])
    # Filter out old attempts
    attempts = [t for t in attempts if now - t < TIME_WINDOW]
    login_attempts[ip] = attempts
    
    if len(attempts) >= MAX_ATTEMPTS:
        return True
    return False

def add_attempt(ip: str):
    login_attempts.setdefault(ip, []).append(time.time())

@router.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    
    if is_rate_limited(client_ip):
        return JSONResponse(status_code=429, content={"status": "error", "message": "尝试次数过多，请稍后再试"})

    settings = get_app_settings()
    stored_hash = settings.get("PASS_HASH")
    
    # 兼容旧明文密码（虽然 init_db 应该已经迁移了，但为了稳健）
    stored_plain = settings.get("PASS_WORD")
    
    input_pwd = payload.password.strip()
    
    auth_success = False
    
    if stored_hash:
        if verify_password(input_pwd, stored_hash):
            auth_success = True
    elif stored_plain:
        # Fallback to plain text check (should not happen if migration worked)
        if input_pwd == stored_plain.strip():
            auth_success = True
            
    if auth_success:
        # Create Session
        session_id = generate_session_id()
        expires_at = get_session_expiry(days=7)
        ua = request.headers.get("user-agent", "unknown")
        
        database.create_session(session_id, expires_at, client_ip, ua)
        
        response = JSONResponse(content={"status": "ok", "message": "登录成功"})
        
        # Determine secure flag
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="Lax",
            path="/",
            secure=is_https,
            max_age=7 * 24 * 60 * 60, # 7 days
            expires=expires_at
        )
        return response
    else:
        add_attempt(client_ip)
        # Uniform error message
        return JSONResponse(status_code=401, content={"status": "error", "message": "认证失败"})

@router.post("/api/auth/logout")
async def logout(request: Request):
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        database.delete_session(session_id)
        
    response = JSONResponse(content={"status": "ok", "message": "已退出登录"})
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, samesite="Lax")
    return response
