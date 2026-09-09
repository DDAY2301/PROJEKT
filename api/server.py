from pathlib import Path

from fastapi.staticfiles import StaticFiles

from api.main import app

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

# API routes are registered by api.main first. The static site is mounted last,
# so /health, /auth/* and /projects/* remain API endpoints while /builder/
# and the public landing page are served by the same origin.
app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="site")
