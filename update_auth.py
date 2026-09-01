import sys
import re

with open('backend/routers/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Import Request
content = content.replace("from fastapi import APIRouter, Depends, HTTPException", "from fastapi import APIRouter, Depends, HTTPException, Request")

# Add helper
helper = """
def check_rate_limit(request: Request, action: str = "auth", limit: int = 5, window: int = 60):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    if not redis_manager.rate_limit(f"{action}:{ip}", limit=limit, window=window):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
"""
content = content.replace("def _user_response", helper.lstrip() + "\n\ndef _user_response")

# Add to register
content = content.replace("def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:", "def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:\n    check_rate_limit(request, 'register', 3, 3600)")

# Add to login
content = content.replace("def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:", "def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:\n    check_rate_limit(request, 'login', 5, 60)")

# Add to forgot_password
content = content.replace("def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):", "def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):\n    check_rate_limit(request, 'forgot', 3, 600)")

# Add to reset_password
content = content.replace("def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):", "def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):\n    check_rate_limit(request, 'reset', 5, 600)")

with open('backend/routers/auth.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added rate limiting to auth.py")
