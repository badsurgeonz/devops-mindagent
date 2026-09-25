from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    username: str
    roles: list = field(default_factory=list)
    permissions: set = field(default_factory=set)

    @classmethod
    def from_claims(cls, claims: dict) -> "Principal":
        return cls(
            user_id=str(claims.get("sub", "")),
            tenant_id=str(claims.get("tenant_id", "")),
            username=str(claims.get("username", "")),
            roles=list(claims.get("roles") or []),
            permissions=set(claims.get("permissions") or []),
        )

    def has_perm(self, perm: str) -> bool:
        return perm in self.permissions