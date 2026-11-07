import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import RequestContextMiddleware
from app.core.request_logging import RequestLoggingMiddleware, unhandled_exception_handler
from app.core.error_reporting import init_error_reporting
from app.core.logging_config import configure_logging
from app.core.error_handlers import http_exception_handler, validation_exception_handler
from app.config import settings
from app.core.exceptions import GSTBillingException
from app.database import engine
from app.routers import (
    auth as auth_router, invoices as invoice_router, payments as payment_router,
    parties as party_router, refunds as refund_router, reports as report_router,
    gstr1 as gstr1_router, gstr3b as gstr3b_router, health as health_router,
    sales_summary as sales_summary_router, items as items_router, users as user_router,
    dashboard as dashboard_router,
)

configure_logging(settings.LOG_LEVEL)
init_error_reporting()
logger = logging.getLogger("app.main")


# LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Code before `yield` runs at startup, code after it at shutdown."""
    logger.info(
        "startup", extra={"app": settings.APP_NAME, "environment": settings.ENVIRONMENT}
    )
    yield
    logger.info("shutdown")
    await engine.dispose()  # close pooled DB connections cleanly


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

app.add_middleware(RequestContextMiddleware)

# CORS MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    # In production: replace with your actual frontend domain(s)
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added LAST so it is the outermost middleware: it times everything, CORS included.
app.add_middleware(RequestLoggingMiddleware)


# GLOBAL EXCEPTION HANDLERS
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
    log = logger.error if exc.status_code >= 500 else logger.info
    log("business_error", extra={"error_code": exc.code, "status_code": exc.status_code})
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )


app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# ROUTERS (each registered exactly once)
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(invoice_router.router, prefix="/api/v1")
app.include_router(payment_router.invoice_payments_router, prefix="/api/v1")
app.include_router(payment_router.payments_router, prefix="/api/v1")
app.include_router(party_router.router, prefix="/api/v1")
app.include_router(refund_router.router, prefix="/api/v1")
app.include_router(refund_router.refunds_router, prefix="/api/v1")
app.include_router(report_router.router, prefix="/api/v1")
app.include_router(gstr1_router.router, prefix="/api/v1")
app.include_router(gstr3b_router.router, prefix="/api/v1")
app.include_router(sales_summary_router.router, prefix="/api/v1")
app.include_router(health_router.router)
app.include_router(items_router.router, prefix="/api/v1")
app.include_router(user_router.router, prefix="/api/v1")
app.include_router(dashboard_router.router, prefix="/api/v1")