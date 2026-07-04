import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOTAL_ORDERS = 55
RATE_LIMIT = 17
WINDOW = 10  # seconds

# Fixed catalog of orders (IDs 1..55)
catalog = [{"id": i} for i in range(1, TOTAL_ORDERS + 1)]

# Stores created orders by idempotency key
idempotency_store = {}

# Rate-limit buckets
client_requests = defaultdict(deque)


class OrderCreate(BaseModel):
    item: str | None = None
    quantity: int | None = 1


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Never rate-limit browser preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "anonymous")

    now = time.time()
    bucket = client_requests[client]

    # Remove expired timestamps
    while bucket and bucket[0] <= now - WINDOW:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT:
        retry_after = max(1, int(WINDOW - (now - bucket[0])) + 1)
        return Response(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)

    return await call_next(request)


@app.post("/orders", status_code=201)
def create_order(
    order: OrderCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    # Return the same order if the key already exists
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    created = {
        "id": str(uuid.uuid4()),
        "item": order.item,
        "quantity": order.quantity,
    }

    idempotency_store[idempotency_key] = created
    return created


@app.get("/orders")
def list_orders(limit: int = 10, cursor: str | None = None):
    # Opaque cursor (treated as an index internally)
    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0

    limit = max(1, min(limit, TOTAL_ORDERS))

    items = catalog[start:start + limit]

    next_cursor = None
    if start + limit < TOTAL_ORDERS:
        next_cursor = str(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@app.get("/")
def root():
    return {"status": "ok"}
