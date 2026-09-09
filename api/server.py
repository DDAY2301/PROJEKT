from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import api.main as core
import api.enhanced_runtime  # noqa: F401 - patches core.generate_project

app = core.app
DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

# Keep the historical /builder/ URL working everywhere, but always route it to
# the stable single-file entry point. This route is registered before the
# static mount, so it takes precedence locally and through the Cloudflare
# tunnel.
@app.get("/builder/", include_in_schema=False)
async def builder_redirect():
    return RedirectResponse(url="/builder.html", status_code=307)


# API routes are registered before the static mount. The enhanced runtime adds
# observable design/build/audit/fix/publish states while keeping the same API.
# Static files are mounted last so /health, /auth/* and /projects/* remain API
# endpoints and the landing page / builder share the same origin locally.
app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="site")
