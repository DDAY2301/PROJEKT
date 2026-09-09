"""GitHub Pages publishing for generated customer sites."""

import asyncio

import httpx

import api.main as core


async def publish_generated_site(repo_name: str) -> str:
    """Make the generated repo public and enable GitHub Pages from main/root.

    Returns the deterministic GitHub Pages URL. GitHub may need a short period
    after this call before the site is reachable.
    """
    headers = core.github_headers()
    repo_api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        repo = await client.get(repo_api)
        if repo.status_code >= 400:
            raise RuntimeError(f"GitHub repository lookup failed: {repo.text[:300]}")

        repo_data = repo.json()
        if repo_data.get("private"):
            changed = await client.patch(repo_api, json={"private": False})
            if changed.status_code >= 400:
                raise RuntimeError(f"Could not make generated repository public: {changed.text[:300]}")

        pages_url = f"{repo_api}/pages"
        pages = await client.get(pages_url)
        if pages.status_code == 404:
            created = await client.post(
                pages_url,
                json={"source": {"branch": "main", "path": "/"}},
            )
            if created.status_code not in {201, 202}:
                raise RuntimeError(f"Could not enable GitHub Pages: {created.text[:300]}")
        elif pages.status_code >= 400:
            raise RuntimeError(f"GitHub Pages lookup failed: {pages.text[:300]}")
        else:
            current = pages.json()
            source = current.get("source") or {}
            if source.get("branch") != "main" or source.get("path") != "/":
                updated = await client.put(
                    pages_url,
                    json={"source": {"branch": "main", "path": "/"}},
                )
                if updated.status_code not in {200, 204}:
                    raise RuntimeError(f"Could not update GitHub Pages source: {updated.text[:300]}")

    # The URL is stable even while GitHub is still building the first version.
    return f"https://{core.GITHUB_OWNER.lower()}.github.io/{repo_name}/"


async def wait_for_generated_site(url: str, seconds: int = 90) -> bool:
    """Best-effort readiness check; publishing stays successful if Pages is slow."""
    deadline = asyncio.get_running_loop().time() + seconds
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await client.get(url)
                if 200 <= response.status_code < 400:
                    return True
            except Exception:
                pass
            await asyncio.sleep(3)
    return False
