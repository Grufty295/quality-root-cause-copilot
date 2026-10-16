"""Contratos HTTP de autenticacion. Lo que entra y sale por la API, nada mas."""

from pydantic import BaseModel

from app.modules.auth.models import CurrentUser


class DemoLoginIn(BaseModel):
    username: str


class ScopeOut(BaseModel):
    plant_id: str
    line_id: str | None


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    scopes: list[ScopeOut]

    @classmethod
    def from_model(cls, user: CurrentUser) -> "UserOut":
        return cls(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            scopes=[ScopeOut(plant_id=s.plant_id, line_id=s.line_id) for s in user.scopes],
        )
