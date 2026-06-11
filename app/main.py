from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import GSTBillingException
from app.routers import auth as auth_router


# LIFESPAN 
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs code at application startup and shutdown.
    
    Anything BEFORE the yield → runs at startup (once, when app boots)
    Anything AFTER the yield  → runs at shutdown (once, when app stops)
    
    Use for: DB connection pool warm-up, Redis connection, loading caches.
    Replaces the old @app.on_event("startup") pattern (deprecated in FastAPI).
    """
    # STARTUP
    print(f"Starting {settings.APP_NAME} in {settings.ENVIRONMENT} mode")
    # Future: initialize Redis connection, warm up connection pool, etc.

    yield   # application runs here — handling requests

    # SHUTDOWN
    print("Shutting down — closing connections")
    # Future: close Redis, drain background task queues, etc.


# APP CREATION
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Multi-tenant GST Billing API",
    lifespan=lifespan,

    # In production, disable the docs endpoints
    # They expose your API structure to anyone with the URL
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
    Catches ANY GSTBillingException raised anywhere in the application.
    
    Because every custom exception inherits from GSTBillingException,
    this single handler covers:
      - AuthenticationError (401)
      - DuplicateGSTINError (409)
      - InvoiceLockedError (409)
      - PaymentExceedsOutstandingError (422)
      - ALL others defined in exceptions.py
    
    Returns a consistent JSON error format across the entire API:
      {
        "error": {
          "code": "DUPLICATE_GSTIN",
          "message": "GSTIN '27AAPFU...' is already registered."
        }
      }
    
    This consistency means the frontend can write ONE error handler
    instead of parsing different error formats per endpoint.
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


# ROUTERS 
app.include_router(
    auth_router.router,
    prefix="/api/v1",    # all auth endpoints will be /api/v1/auth/...
)
# Future routers added here:
# app.include_router(invoice_router.router, prefix="/api/v1")
# app.include_router(payment_router.router, prefix="/api/v1")


# HEALTH CHECK 
@app.get("/health", tags=["System"])
async def health_check():
    """
    Used by Docker health checks and load balancers.
    Returns 200 if the app is running.
    Does NOT check DB connectivity here — that is a separate /ready endpoint.
    """
    return {"status": "ok", "env": settings.ENVIRONMENT}
