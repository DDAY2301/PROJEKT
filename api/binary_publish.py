"""GitHub bundle publishing helpers.

Normal incremental publishing remains available for legacy callers. Full-site
replacement uses one atomic Git tree/commit so a ZIP import or AI revision is
never visible half-written and obsolete files disappear from the current tree.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import httpx

import api.main as core


def _raw(content: Any) -> bytes:
    return content if isinstance(content, bytes) else str(content).encode("utf-8")


def _safe_repo_path(path: Any) -> str:
    safe_path = str(path).strip().replace("\\", "/").lstrip("/")
    if (
        not safe_path
        or safe_path.startswith(".")
        or any(part in {"", ".", ".."} for part in safe_path.split("/"))
    ):
        raise core.HTTPException(422, f"Unsafe repository path: {path}")
    return safe_path


def _normalise_bundle(files: dict) -> dict[str, Any]:
    normalised: dict[str, Any] = {}
    for path, content in files.items():
        safe_path = _safe_repo_path(path)
        if safe_path in normalised:
            raise core.HTTPException(422, f"Duplicate repository path after normalization: {safe_path}")
        normalised[safe_path] = content
    return normalised


def _git_blob_sha(content: Any) -> str:
    data = _raw(content)
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _expected_bundle_manifest(files: dict) -> dict[str, str]:
    return {path: _git_blob_sha(content) for path, content in _normalise_bundle(files).items()}


def _tree_blob_manifest(tree_items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("path") or ""): str(item.get("sha") or "")
        for item in tree_items
        if item.get("type") == "blob" and item.get("path") and item.get("sha")
    }


def _tree_matches_bundle(files: dict, tree_items: list[dict[str, Any]]) -> tuple[bool, dict[str, str], dict[str, str]]:
    expected = _expected_bundle_manifest(files)
    actual = _tree_blob_manifest(tree_items)
    return expected == actual, expected, actual


async def _read_bundle_state(
    client: httpx.AsyncClient,
    api: str,
    files: dict,
) -> dict[str, Any]:
    ref = await client.get(f"{api}/git/ref/heads/main")
    if ref.status_code >= 400:
        raise core.HTTPException(502, f"Could not read repository head: {ref.text[:300]}")
    head_sha = str((ref.json().get("object") or {}).get("sha") or "")
    if not head_sha:
        raise core.HTTPException(502, "Repository main branch has no head commit")

    commit = await client.get(f"{api}/git/commits/{head_sha}")
    if commit.status_code >= 400:
        raise core.HTTPException(502, f"Could not read repository commit: {commit.text[:300]}")
    commit_data = commit.json()
    tree_sha = str((commit_data.get("tree") or {}).get("sha") or "")
    if not tree_sha:
        raise core.HTTPException(502, "Repository head commit has no tree")

    tree = await client.get(f"{api}/git/trees/{tree_sha}", params={"recursive": "1"})
    if tree.status_code >= 400:
        raise core.HTTPException(502, f"Could not read repository tree: {tree.text[:300]}")
    tree_data = tree.json()
    if tree_data.get("truncated"):
        raise core.HTTPException(409, "Repository tree is too large for exact replacement verification")

    exact, expected, actual = _tree_matches_bundle(files, list(tree_data.get("tree") or []))
    return {
        "head": head_sha,
        "tree": tree_sha,
        "exact": exact,
        "expected": expected,
        "actual": actual,
    }


async def github_bundle_state(repo_name: str, files: dict) -> dict[str, Any]:
    """Return current main tree state compared with the exact desired bundle."""
    if not files:
        raise core.HTTPException(422, "Bundle cannot be empty")
    await core.ensure_repo(repo_name)
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    async with httpx.AsyncClient(timeout=120, headers=core.github_headers()) as client:
        return await _read_bundle_state(client, api, files)


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
    """Replace the complete main-branch tree in one verified commit.

    The tree is created from scratch without a base tree, so files absent from
    the desired bundle disappear. If a restart retries a bundle that is already
    the exact current tree, the write is idempotently reused instead of creating
    another commit.
    """
    normalised = _normalise_bundle(files)
    if not normalised or "index.html" not in {path.lower() for path in normalised}:
        raise core.HTTPException(422, "Atomic website replacement requires index.html")

    await core.ensure_repo(repo_name)
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    headers = core.github_headers()

    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        before_state = await _read_bundle_state(client, api, normalised)
        parent_sha = str(before_state["head"])

        # Restart/idempotency protection: if the already-active repository tree
        # is byte-for-byte the requested bundle, do not create a duplicate commit.
        if before_state["exact"]:
            return {
                "before": parent_sha,
                "after": parent_sha,
                "tree": str(before_state["tree"]),
                "files": str(len(normalised)),
                "verified": "true",
                "reused_existing": "true",
                "commit_count_delta": "0",
            }

        tree_entries: list[dict[str, str]] = []
        for safe_path, content in sorted(normalised.items()):
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
            if blob_sha != _git_blob_sha(content):
                raise core.HTTPException(502, f"GitHub blob verification failed for {safe_path}")
            tree_entries.append(
                {
                    "path": safe_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        # IMPORTANT: intentionally no base_tree. This is a full replacement.
        tree = await client.post(f"{api}/git/trees", json={"tree": tree_entries})
        if tree.status_code >= 400:
            raise core.HTTPException(502, f"Could not create replacement tree: {tree.text[:300]}")
        tree_sha = str(tree.json().get("sha") or "")
        if not tree_sha:
            raise core.HTTPException(502, "GitHub returned no replacement tree SHA")

        staged_tree = await client.get(f"{api}/git/trees/{tree_sha}", params={"recursive": "1"})
        if staged_tree.status_code >= 400:
            raise core.HTTPException(502, f"Could not verify replacement tree: {staged_tree.text[:300]}")
        staged_data = staged_tree.json()
        if staged_data.get("truncated"):
            raise core.HTTPException(409, "Replacement tree is too large for exact verification")
        exact_staged, expected, actual_staged = _tree_matches_bundle(normalised, list(staged_data.get("tree") or []))
        if not exact_staged:
            missing = sorted(set(expected) - set(actual_staged))[:8]
            extra = sorted(set(actual_staged) - set(expected))[:8]
            raise core.HTTPException(
                502,
                f"Replacement tree verification failed before commit; missing={missing}, extra={extra}",
            )

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

        created = await client.get(f"{api}/git/commits/{commit_sha}")
        if created.status_code >= 400:
            raise core.HTTPException(502, f"Could not verify replacement commit: {created.text[:300]}")
        created_data = created.json()
        created_tree = str((created_data.get("tree") or {}).get("sha") or "")
        parents = [str(item.get("sha") or "") for item in (created_data.get("parents") or [])]
        if created_tree != tree_sha or parents != [parent_sha]:
            raise core.HTTPException(502, "Replacement commit does not have the expected tree and single parent")

        update = await client.patch(
            f"{api}/git/refs/heads/main",
            json={"sha": commit_sha, "force": False},
        )
        if update.status_code >= 400:
            raise core.HTTPException(502, f"Could not activate replacement commit: {update.text[:300]}")

        after_state = await _read_bundle_state(client, api, normalised)
        if (
            str(after_state["head"]) != commit_sha
            or str(after_state["tree"]) != tree_sha
            or not bool(after_state["exact"])
        ):
            raise core.HTTPException(502, "Repository head verification failed after atomic replacement")

    return {
        "before": parent_sha,
        "after": commit_sha,
        "tree": tree_sha,
        "files": str(len(tree_entries)),
        "verified": "true",
        "reused_existing": "false",
        "commit_count_delta": "1",
    }


core.github_put_bundle = github_put_bundle_binary
core.github_replace_bundle = github_replace_bundle_atomic
core.github_bundle_state = github_bundle_state
