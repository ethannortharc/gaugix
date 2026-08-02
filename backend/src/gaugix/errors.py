"""Error envelope: every failure leaves the API as `{"error": {code, message, details?}}`.

ARCHITECTURE §7. Exception handlers are installed by the app factory.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gaugix.logging_setup import get_logger

log = get_logger("gaugix.errors")


class GaugixError(Exception):
    """Base class for errors that map onto the API error envelope."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFoundError(GaugixError):
    status_code = 404
    code = "not_found"


class ConflictError(GaugixError):
    status_code = 409
    code = "conflict"


class ValidationError(GaugixError):
    status_code = 422
    code = "validation_error"


class UnprocessableError(GaugixError):
    status_code = 422
    code = "unprocessable"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def install_error_handlers(app: FastAPI) -> None:
    """Attach the envelope handlers to a FastAPI app."""

    @app.exception_handler(GaugixError)
    async def _gaugix(_: Request, exc: GaugixError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Request payload failed validation",
                # jsonable: pydantic errors can carry exception objects in `ctx`
                details=[{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()],
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=str(request.url.path), error=str(exc))
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "An unexpected error occurred"),
        )
