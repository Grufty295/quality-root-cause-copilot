from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.routes import router as agent_router
from app.core.errors import AppError
from app.core.security import OriginCheckMiddleware
from app.modules.auth.routes import router as auth_router
from app.modules.ncr.routes import router as ncr_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    deps = getattr(app.state, "agent_deps", None)
    if deps is not None:
        from app.agent.runtime import close_deps

        await close_deps(deps)


app = FastAPI(title="Agente 8D", lifespan=lifespan)
app.add_middleware(OriginCheckMiddleware)
app.include_router(auth_router)
app.include_router(ncr_router)
app.include_router(agent_router)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Unico lugar donde los errores de dominio se convierten en HTTP."""
    headers = {}
    retry_after = getattr(exc, "retry_after_s", None)
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
