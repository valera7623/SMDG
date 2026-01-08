# app/core/middleware.py
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core import audit_logger

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        method = request.method
        url = request.url.path
        user_agent = request.headers.get("user-agent", "unknown")

        response = await call_next(request)

        status_code = response.status_code
        success = status_code < 400

        audit_logger.log_operation(
            action=f"{method} {url}",
            filename="",
            user="api",
            ip=client_ip,
            reason=f"Status: {status_code}, UA: {user_agent[:100]}",
            success=success,
            metadata={
                "method": method,
                "path": url,
                "status": status_code,
                "user_agent": user_agent
            }
        )

        return response