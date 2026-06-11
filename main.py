from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from configs.base import settings
from modules.auth.routes import router as auth_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Add GZip compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

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

@app.get("/")
def read_root():
    return {"message": "Welcome to Computer Vision API"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)


