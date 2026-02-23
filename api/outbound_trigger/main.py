"""
Outbound call trigger API.

Dispatches a LiveKit agent to place an outbound phone call.
Deployed as an AWS Lambda function via Mangum.
"""

from fastapi import FastAPI
from mangum import Mangum

from src.routes.trigger import router as trigger_router

app = FastAPI(
    title="LogiCall Outbound Trigger",
    version="1.0.0",
    docs_url="/docs",
)

app.include_router(trigger_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
