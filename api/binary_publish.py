"""GitHub bundle publishing helpers.

Normal incremental publishing remains available for legacy callers. Full-site
replacement uses one atomic Git tree/commit so a ZIP import or AI revision is
never visible half-written and obsolete files disappear from the current tree.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

import api.main as core


def _raw(content: Any) -> bytes:
    return content if isinstance(content, bytes) else str(content).encode("utf-8")


async def github_put_bundle_binary(repo_name: str, files: dict, message: str):
    """Legacy incremental writer used by existing generated-site flows."""
    await core.ensure_repo(repo_name)
    async with httpx.AsyncClient(timeout=90, headers=core.github_headers()) as client:
        for path, content in files.items():
            url = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}/contents/{path}"
            existing = await client.get(url)
            payload = {
                "message": message,
                "content": base64.b64encode(_raw(content)).decode("ascii"),
            }
            if existing.status_code == 200:
                payload["sha"] = existing.json()["sha"]
            response = await client.put(url, json=payload)
            if response.status_code >= 400:
                raise core.HTTPException(502, f"GitHub write failed for {path}: {response.text[:300]}")


async def github_replace_bundle_atomic(repo_name: str, files: dict, message: str) -> dict[str, str]:
    """Replace the complete main-branch tree in exactly one commit.

    A tree is created from scratch without a base tree, therefore files absent
    from the provided bundle are intentionally removed from the new repository
    version. The previous commit remains in Git history and can be rolled back.
    """
    if not files or "index.html" not in {str(path).lower() for path in files}:
        raise core.HTTPException(422, "Atomic website replacement requires index.html")

    await core.ensure_repo(repo_name)
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    headers = core.github_headers()

    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        ref = await client.get(f"{api}/git/ref/heads/main")
        if ref.status_code >= 400:
            raise core.HTTPException(502, f"Could not read repository head: {ref.text[:300]}")
        parent_sha = str((ref.json().get("object") or {}).get("sha") or "")
        if not parent_sha:
            raise core.HTTPException(502, "Repository main branch has no head commit")

        tree_entries: list[dict[str, str]] = []
        for path, content in sorted(files.items(), key=lambda item: str(item[0])):
            safe_path = str(path).strip().replace("\\", "/").lstrip("/")
            if not safe_path or safe_path.startswith(".") or ".." in safe_path.split("/"):
                raise core.HTTPException(422, f"Unsafe repository path: {path}")

            blob = await client.post(
                f"{api}/git/blobs",
                json={
                    "content": base64.b64encode(_raw(content)).decode("ascii"),
                    "encoding": "base64",
                },
            )
            if blob.status_code >= 400:
                raise core.HTTPException(502, f"Could not stage {safe_path}: {blob.text[:260]}")
            blob_sha = str(blob.json().get("sha") or "")
            if not blob_sha:
                raise core.HTTPException(502, f"GitHub returned no blob SHA for {safe_path}")
            tree_entries.append(
                {
                    "path": safe_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        tree = await client.post(f"{api}/git/trees", json={"tree": tree_entries})
        if tree.status_code >= 400:
            raise core.HTTPException(502, f"Could not create replacement tree: {tree.text[:300]}")
        tree_sha = str(tree.json().get("sha") or "")
        if not tree_sha:
            raise core.HTTPException(502, "GitHub returned no replacement tree SHA")

        commit = await client.post(
            f"{api}/git/commits",
            json={
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha],
            },
        )
        if commit.status_code >= 400:
            raise core.HTTPException(502, f"Could not create replacement commit: {commit.text[:300]}")
        commit_sha = str(commit.json().get("sha") or "")
        if not commit_sha:
            raise core.HTTPException(502, "GitHub returned no replacement commit SHA")

        update = await client.patch(
            f"{api}/git/refs/heads/main",
            json={"sha": commit_sha, "force": False},
        )
        if update.status_code >= 400:
            raise core.HTTPException(502, f"Could not activate replacement commit: {update.text[:300]}")

    return {
        "before": parent_sha,
        "after": commit_sha,
        "tree": tree_sha,
        "files": str(len(tree_entries)),
    }


core.github_put_bundle = github_put_bundle_binary
core.github_replace_bundle = github_replace_bundle_atomic
