from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import api.main as core
import api.robust_generation  # noqa: F401 - patches planning/build/QA for local models
import api.premium_generation  # noqa: F401 - enforces premium deterministic design quality floor
import api.premium_quality  # noqa: F401 - rejects weak or fabricated output before publishing
import api.enhanced_runtime  # noqa: F401 - patches core.generate_project
import api.revisions  # noqa: F401 - registers post-build revision routes
import api.retry_routes  # noqa: F401 - registers failed-build retry route

app = core.app
DIST_DIR = Path(__file__).resolve().parent.parent / "dist"


# Chrome/Chromium Local Network Access can add a private-network preflight when
# an HTTPS frontend calls the loopback service. The existing CORS middleware
# already validates the normal request; this response header opts the local
# service into that additional browser check. It exposes nothing beyond the
# machine because 127.0.0.1 remains loopback-only.
@app.middleware("http")
async def allow_loopback_private_network(request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network", "").lower() == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# Keep the historical /builder/ URL working everywhere, but always route it to
# the stable single-file entry point. This route is registered before the
# static mount, so it takes precedence locally and through a tunnel.
@app.get("/builder/", include_in_schema=False)
async def builder_redirect():
    return RedirectResponse(url="/builder.html", status_code=307)


# API routes are registered before the static mount. The enhanced runtime adds
# observable design/build/audit/fix/publish states while keeping the same API.
# Static files are mounted last so /health, /auth/* and /projects/* remain API
# endpoints and the landing page / builder share the same origin locally.
app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="site")
