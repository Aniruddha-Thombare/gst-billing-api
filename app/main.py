from fastapi import FastAPI
from app.config import settings
import app.models


app = FastAPI(
    title="GST Billing API",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None,
)

@app.get("/health")
def health():
    return {"status": "ok"}
