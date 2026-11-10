# FastAPI learning notes — Phase 1A

These notes describe the health/factory increment. Phase 1B adds [configuration and lifespan notes](configuration.md); Phase 1C adds [HTTP observability notes](http-observability.md); remaining architecture is still planned.

## Application factory

`create_app()` constructs and returns a FastAPI application. Calling it twice produces independent app state and route collections, which helps test isolation and later configuration. Defining the function does not connect to any external service. Uvicorn's `--factory` tells it to call the function to obtain the ASGI application.

ASGI is the interface between the server (Uvicorn) and the Python application (FastAPI). The server handles sockets/HTTP; the app selects routes and produces responses.

## Router composition

`APIRouter` groups HTTP routes. The health module declares `/health`; the composed API router adds `/api/v1`; the application includes that router. Keeping the prefix in one place prevents accidental duplicate or unversioned paths as modules grow.

The health module stays in the presentation layer because it has no business operation or database query to delegate. A service/repository pair would not serve a purpose here.

## Response schemas

`HealthResponse` is a Pydantic model with two `Literal` string fields. `get_health()` constructs that model; FastAPI validates/serializes it using `response_model` and publishes the schema through OpenAPI. Unexpected fields are forbidden, and no environment variables or credentials are copied into the response.

OpenAPI is a machine-readable API contract. `/docs` is an interactive interface generated from it. Serving the HTML does not prove a browser rendered or exercised it.

## Liveness versus readiness

A liveness response means the API can handle this request. It must not imply the database, queue, worker, model provider, or entire product is ready. A DB-aware readiness check is a separate future concern. There is intentionally no database session or dependency check in the implemented health route.

The endpoint is public and read-only. Later auth dependencies must not accidentally protect this liveness check.

## Async handler and HTTP tests

The tiny handler is `async def` and does no blocking work. This is different from using a blocking database query or provider call inside an event loop; those require the session/thread boundaries chosen for later modules.

The tests use HTTPX's `AsyncClient` and `ASGITransport` to send real ASGI requests without a TCP socket. AnyIO's existing pytest integration runs the async tests on asyncio. The transport does not automatically execute lifespan startup/shutdown; Phase 1B now supplies explicit lifecycle coverage through `LifespanManager`. Separate Uvicorn smoke checks verify actual server startup, HTTP responses, and graceful shutdown.

`pytest.mark.parametrize` checks multiple invalid paths with one test definition. The factory-isolation test changes one app and requests the other to catch accidental shared application state. The OpenAPI test checks the published schema rather than just calling the Python handler directly.

## Review questions

Discuss one at a time:

1. What could go wrong in tests if every test reused one global, mutable FastAPI app?
2. Why should this liveness endpoint still return 200 when Groq is unavailable?
3. What does the Pydantic response model add beyond returning an ordinary dictionary?
4. Which behavior is not verified by HTTPX ASGITransport alone when startup hooks are added?

## Independent exercise

Add a test that `POST /api/v1/health` returns 405 without adding a POST endpoint. Explain why a route can exist while a particular HTTP method is rejected. Try the test before asking for the solution.
