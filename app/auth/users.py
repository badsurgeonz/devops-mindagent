from app.config import cfg

_DEFAULT_USERS = [
    {
        "id": "1",
        "tenant_id": "tenant-a",
        "username": "demo",
        "password": "demo1234",
        "roles": ["developer"],
        "permissions": [
            "chat:use",
            "history:read",
            "history:delete",
            "tool:logs:read",
            "tool:redis:read",
            "trace:read",
            "kb:manage",
        ],
    }
]


class UserStore:
    def __init__(self, db=None) -> None:
        from app.auth.security import hash_password

        self.db = db
        self._memory = {}
        for u in (cfg.auth.seed_users or _DEFAULT_USERS):
            salt, digest = hash_password(u["password"])
            self._memory[u["username"]] = {
                "id": u.get("id", "0"),
                "tenant_id": u["tenant_id"],
                "username": u["username"],
                "salt": salt,
                "digest": digest,
                "roles": u.get("roles", []),
                "permissions": u.get("permissions", []),
            }

    async def seed_defaults(self) -> None:
        if self.db is not None:
            from app.db.repo import UserRepo

            await UserRepo(self.db).seed_if_empty(cfg.auth.seed_users or _DEFAULT_USERS)

    async def authenticate(self, username: str, password: str) -> dict | None:
        if self.db is not None:
            from app.db.repo import UserRepo

            user = await UserRepo(self.db).authenticate(username, password)
            if user is not None:
                return user
        mem = self._memory.get(username)
        if mem is None:
            return None
        from app.auth.security import verify_password

        salt, digest = mem["salt"], mem["digest"]
        if not verify_password(password, salt, digest):
            return None
        return {
            "id": mem["id"],
            "tenant_id": mem["tenant_id"],
            "username": mem["username"],
            "roles": mem["roles"],
            "permissions": mem["permissions"],
        }