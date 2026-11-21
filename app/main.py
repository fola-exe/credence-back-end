import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.errors import AppError, error_envelope, validation_fields
from app.core.logging import log_event, new_request_id, redact_public_token, setup_logging
from app.core.rate_limit import limiter
from app.core.startup import StartupConfigurationError, check_database, validate_startup
from app.modules.auth.service import auth_routes
from app.modules.businesses.router import business_routes
from app.modules.capacity.router import capacity_routes
from app.modules.debtors.router import debtor_routes
from app.modules.payments.router import payment_routes
from app.modules.public.router import public_routes
from app.modules.transactions.router import transaction_routes

setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup()
    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.include_router(auth_routes)
app.include_router(business_routes)
app.include_router(debtor_routes)
app.include_router(capacity_routes)
app.include_router(transaction_routes)
app.include_router(public_routes)
app.include_router(payment_routes)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def request_id_for(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


def legacy_error(status_code: int) -> tuple[str, str]:
    if status_code == 401:
        return "UNAUTHORIZED", "Authentication is required."
    if status_code == 404:
        return "NOT_FOUND", "The requested resource was not found."
    if status_code == 409:
        return "CONFLICT", "The request conflicts with the current state."
    if status_code == 429:
        return "RATE_LIMITED", "Too many requests. Please try again later."
    if status_code >= 500:
        return "INTERNAL_ERROR", "An unexpected error occurred."
    return "VALIDATION_ERROR", "The request is invalid."


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    request.state.request_id = request_id
    started = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    path = redact_public_token(request.url.path)
    response.headers["X-Request-ID"] = request_id
    if path.startswith("/public/"):
        response.headers["Referrer-Policy"] = "no-referrer"

    log_event(
        "request",
        request_id=request_id,
        method=request.method,
        path=path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    request_id = request_id_for(request)
    payload = exc.envelope()
    if exc.http_status >= 500:
        payload["error"]["request_id"] = request_id

    log_event(
        "error",
        request_id=request_id,
        code=exc.code,
        status_code=exc.http_status,
        path=redact_public_token(request.url.path),
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=payload,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    request_id = request_id_for(request)
    log_event(
        "error",
        request_id=request_id,
        code="VALIDATION_ERROR",
        status_code=422,
        path=redact_public_token(request.url.path),
    )
    return JSONResponse(
        status_code=422,
        content=error_envelope(
            "VALIDATION_ERROR",
            "The request is invalid.",
            fields=validation_fields(exc.errors()),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException):
    request_id = request_id_for(request)
    code, message = legacy_error(exc.status_code)
    payload = error_envelope(code, message)
    if exc.status_code >= 500:
        payload["error"]["request_id"] = request_id

    log_event(
        "error",
        request_id=request_id,
        code=code,
        status_code=exc.status_code,
        path=redact_public_token(request.url.path),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=dict(exc.headers or {}),
    )


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request: Request, exc: RateLimitExceeded):
    request_id = request_id_for(request)
    log_event(
        "error",
        request_id=request_id,
        code="RATE_LIMITED",
        status_code=429,
        path=redact_public_token(request.url.path),
    )
    return JSONResponse(
        status_code=429,
        content=error_envelope(
            "RATE_LIMITED",
            "Too many requests. Please try again later.",
        ),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    request_id = request_id_for(request)
    log_event(
        "unhandled_error",
        request_id=request_id,
        error_type=type(exc).__name__,
        path=redact_public_token(request.url.path),
    )
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
            extra={"request_id": request_id},
        ),
    )


@app.get("/health")
def health():
    return {"status": "Working"}


@app.get("/health/ready")
def readiness():
    try:
        check_database()
    except StartupConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "Ready"}
