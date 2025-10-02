from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .endpoints import projects, builds, resources, ws, templates
from ..utils.logger import setup_logger
from .deps import register_fs
from ..exceptions import (
    DNSBuilderError,
    ConfigFileMissingError,
    ReferenceNotFoundError,
    ConfigValidationError,
)

app = FastAPI(title="DNSBuilder API")

@app.on_event("startup")
async def startup_event():
    setup_logger(debug=True)
    app.state.fs = register_fs(use_vfs=True)

# Exception Handler
@app.exception_handler(DNSBuilderError)
async def dnsbuilder_exception_handler(request: Request, exc: DNSBuilderError):
    status_code = 400  # Default
    if isinstance(exc, (ConfigFileMissingError, ReferenceNotFoundError)):
        status_code = 404
    elif isinstance(exc, ConfigValidationError):
        status_code = 422

    return JSONResponse(
        status_code=status_code,
        content={"error": exc.__class__.__name__, "message": str(exc)},
    )


# Router
app.include_router(projects.router, prefix="/api", tags=["Projects & Config"])
app.include_router(builds.router, prefix="/api", tags=["Builds"])
app.include_router(resources.router, prefix="/api", tags=["Resources"])
app.include_router(templates.router, prefix="/api", tags=["Templates"])
app.include_router(ws.router, prefix="/api", tags=["WebSocket"])
