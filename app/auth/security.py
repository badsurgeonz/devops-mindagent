import hashlib
import hmac
import secrets
import time
import uuid

import jwt

from app.config import cfg


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return salt, digest


def verify_password(password: str, salt: str, digest: str) -> bool:
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, digest)


def create_access_token(principal: dict, user_id: str) -> str:
    now = int(time.time())
    claims = {
        "jti": uuid.uuid4().hex,
        "sub": user_id,
        "tenant_id": principal["tenant_id"],
        "username": principal["username"],
        "roles": principal["roles"],
        "permissions": principal["permissions"],
        "iat": now,
        "exp": now + cfg.auth.access_expire_seconds,
        "iss": cfg.auth.issuer,
    }
    return jwt.encode(claims, cfg.auth.secret, algorithm=cfg.auth.algorithm)


def decode_token(token: str) -> dict:
    if not cfg.auth.secret:
        raise ValueError("JWT_SECRET 未配置")
    return jwt.decode(
        token,
        cfg.auth.secret,
        algorithms=[cfg.auth.algorithm],
        issuer=cfg.auth.issuer,
        options={"verify_aud": False},
    )