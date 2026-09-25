from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import Principal
from app.auth.security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证凭据")
    try:
        claims = decode_token(credentials.credentials)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期") from exc
    principal = Principal.from_claims(claims)
    if not principal.user_id or not principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 缺少身份信息")
    return principal


def require_permissions(*perms: str):
    async def checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        missing = [p for p in perms if not principal.has_perm(p)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {', '.join(missing)}",
            )
        return principal

    return checker