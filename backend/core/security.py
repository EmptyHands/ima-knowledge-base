"""安全工具 - 密码哈希(bcrypt) + JWT"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from .config import get_config

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    config = get_config()
    expire = datetime.utcnow() + timedelta(days=config.jwt_expire_days)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[str]:
    config = get_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None
