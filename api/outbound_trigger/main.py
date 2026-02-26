"""
Outbound call trigger API.

Dispatches a LiveKit agent to place an outbound phone call.
Deployed as an AWS Lambda function via Mangum.
All endpoints except /health require API key (Authorization: Bearer <key> or X-API-Key: <key>).
"""

from fastapi import Depends, FastAPI
from mangum import Mangum

from api.common.auth import verify_api_key
from src.routes.trigger import router as trigger_router
from src.routes.rooms import router as rooms_router

app = FastAPI(
    title="LogiCall Outbound Trigger",
    version="1.0.0",
    docs_url="/docs",
    openapi_tags=[
        {"name": "trigger", "description": "Outbound call dispatch"},
        {"name": "rooms", "description": "Room management and observability"},
    ],
)

# OpenAPI security: so /docs "Authorize" sends the API key
app.openapi_schema = None  # allow schema to be built with security

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key (or use Authorization: Bearer &lt;key&gt;)",
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "Authorization: Bearer &lt;your-api-key&gt;",
        },
    }
    openapi_schema["security"] = [{"ApiKeyHeader": []}, {"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Protected routes: require valid API key (env API_KEY or LOGICALL_API_KEY)
app.include_router(trigger_router, dependencies=[Depends(verify_api_key)])
app.include_router(rooms_router, dependencies=[Depends(verify_api_key)])


@app.get("/health")
async def health():
    return {"status": "ok"}


handler = Mangum(app, lifespan="off")
