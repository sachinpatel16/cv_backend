from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from configs.base import settings
from modules.auth.routes import router as auth_router
from modules.peoplefind.routes import router as peoplefind_router
from modules.peoplecount.routes import router as peoplecount_router


from fastapi.staticfiles import StaticFiles
import os

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Ensure the storage directory exists before mounting to avoid errors
os.makedirs("storage", exist_ok=True)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# Add GZip compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add CORS middleware to support cookie exchange
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Exception Handlers to match the error response envelope in auth.md
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": exc.detail,
            "status": exc.status_code,
            "data": None
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_messages = []
    for err in errors:
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        error_messages.append(f"{loc}: {msg}")
    
    message = "; ".join(error_messages) if error_messages else "Validation Error"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,  # Map validation issues to 400 Bad Request
        content={
            "message": message,
            "status": status.HTTP_400_BAD_REQUEST,
            "data": None
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "message": "Internal server error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "data": None
        }
    )

# Include Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(peoplefind_router, prefix=settings.API_V1_STR)
app.include_router(peoplecount_router, prefix=settings.API_V1_STR)


@app.on_event("startup")
async def startup_event():
    from database.redis import init_redis
    await init_redis()

    import asyncio
    from modules.peoplefind.service import PeopleFindService
    asyncio.create_task(PeopleFindService.migrate_existing_heic())


@app.on_event("shutdown")
async def shutdown_event():
    from database.redis import close_redis
    await close_redis()



@app.get("/")
def read_root():
    return {"message": "Welcome to Computer Vision API"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)


