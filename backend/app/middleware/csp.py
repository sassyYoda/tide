"""SEC-05 — Content-Security-Policy header injection.

CSP shape locked per L-04 (CONTEXT.md). 'unsafe-inline' on style-src is required by
Tailwind v4 (CSS-in-JS hashed-class injection at runtime). Risk is mitigated by
default-src 'self' + frame-ancestors 'none'. Future tightening to nonce-based CSP is a
v1.x task if XSS surfaces.

Wired in plan 06-03 (Wave 1): inserted into app.add_middleware AFTER CORSMiddleware
so CORS headers attach first; CSP attaches on the response on the way out. Order:
CORS -> CSP -> RateLimit -> routers.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://tile.openfreemap.org; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: https://tile.openfreemap.org; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self' https://*.run.app https://us.cloud.langfuse.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


class CSPMiddleware(BaseHTTPMiddleware):
    """Attach Content-Security-Policy + companion defense headers to every response."""

    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP_POLICY
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


__all__ = ["CSPMiddleware", "CSP_POLICY"]
