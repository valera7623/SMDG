from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core import audit_logger


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        method = request.method
        url = request.url.path
        # FIX 1: user_agent может быть None — используем "unknown" как fallback
        user_agent = request.headers.get("user-agent") or "unknown"

        try:
            response = await call_next(request)
            status_code = response.status_code
            success = status_code < 400
            reason = f"Status: {status_code}, UA: {user_agent[:100]}"

            audit_logger.log_operation(
                action=f"{method} {url}",
                filename="",
                user="api",
                ip=client_ip,
                reason=reason,
                success=success,
                metadata={
                    "method": method,
                    "path": url,
                    "status": status_code,
                    "user_agent": user_agent
                }
            )

            return response

        # FIX 2: перехватываем исключение, логируем, пробрасываем дальше
        except Exception as e:
            audit_logger.log_operation(
                action=f"{method} {url}",
                filename="",
                user="api",
                ip=client_ip,
                reason=str(e),
                success=False,
                metadata={
                    "method": method,
                    "path": url,
                    "status": 500,
                    "user_agent": user_agent
                }
            )
            raise
