from pathlib import Path

from fastapi.staticfiles import StaticFiles

import api.main as core
import api.enhanced_runtime  # noqa: F401 - patches core.generate_project

app = core.app
DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

# API routes are registered before the static mount. The enhanced runtime adds
# observable design/build/audit/fix/publish states while keeping the same API.
# Static files are mounted last so /health, /auth/* and /projects/* remain API
# endpoints and /builder/ plus the landing page share the same origin locally.
app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="site")
