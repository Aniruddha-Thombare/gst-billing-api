from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import GSTBillingException
from app.routers import (
    auth as auth_router, invoices as invoice_router, 
    payments as payment_router, parties as party_router,
    refunds as refund_router, reports as report_router
)


# LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs code at application startup and shutdown.

    Anything BEFORE the yield runs once at startup.
    Anything AFTER the yield runs once at shutdown.
    """
    # STARTUP
    print(f"Starting {settings.APP_NAME} in {settings.ENVIRONMENT} mode")
    # Future: initialize Redis connection, warm up connection pool, etc.

    yield   # application runs here, handling requests

    # SHUTDOWN
    print("Shutting down - closing connections")
    # Future: close Redis, drain background task queues, etc.


# APP CREATION
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Multi-tenant GST Billing API",
    lifespan=lifespan,

    # In production, disable the docs endpoints
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)


# CORS MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    # In production: replace with your actual frontend domain(s)
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# GLOBAL EXCEPTION HANDLER
@app.exception_handler(GSTBillingException)
async def gst_exception_handler(
    _request: Request,
    exc: GSTBillingException,
) -> JSONResponse:
    """
    Catches ANY GSTBillingException raised anywhere in the application and
    returns one consistent JSON error format:
      {"error": {"code": "DUPLICATE_GSTIN", "message": "..."}}
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )


# ROUTERS (each registered exactly once)
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(invoice_router.router, prefix="/api/v1")
app.include_router(payment_router.invoice_payments_router, prefix="/api/v1")
app.include_router(payment_router.payments_router, prefix= "/api/v1")
app.include_router(party_router.router, prefix="/api/v1")
app.include_router(refund_router.router, prefix="/api/v1")
app.include_router(refund_router.refunds_router, prefix="/api/v1")
app.include_router(report_router.router, prefix="/api/v1")


# HEALTH CHECK
@app.get("/health", tags=["System"])
async def health_check():
    """
    Used by Docker health checks and load balancers.
    Returns 200 if the app is running.
    Does NOT check DB connectivity (that would be a separate /ready endpoint).
    """
    return {"status": "ok", "env": settings.ENVIRONMENT}