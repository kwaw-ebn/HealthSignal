import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import User, get_db

SECRET=os.getenv("JWT_SECRET","")
ALGORITHM="HS256"; TOKEN_HOURS=8
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")
bearer=HTTPBearer(auto_error=False)

def hash_password(value): return pwd.hash(value)
def verify_password(value,hashed): return pwd.verify(value,hashed)
def token_for(user):
    if not SECRET: raise RuntimeError("JWT_SECRET is not configured")
    payload={"sub":user.username,"role":user.role,"exp":datetime.now(timezone.utc)+timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload,SECRET,algorithm=ALGORITHM)
def current_user(credentials:HTTPAuthorizationCredentials=Depends(bearer),db:Session=Depends(get_db)):
    if not credentials or not SECRET: raise HTTPException(401,"Authentication required")
    try: username=jwt.decode(credentials.credentials,SECRET,algorithms=[ALGORITHM])["sub"]
    except (JWTError,KeyError): raise HTTPException(401,"Invalid or expired session")
    user=db.scalar(select(User).where(User.username==username,User.active.is_(True)))
    if not user: raise HTTPException(401,"User account unavailable")
    return user
def allow(*roles):
    def check(user:User=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,"Your role cannot perform this action")
        return user
    return check
