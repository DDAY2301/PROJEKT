"""Patch GitHub bundle publishing so generated sites can contain image bytes."""

from __future__ import annotations

import base64

import httpx

import api.main as core


async def github_put_bundle_binary(repo_name: str, files: dict, message: str):
    await core.ensure_repo(repo_name)
    async with httpx.AsyncClient(timeout=90, headers=core.github_headers()) as client:
        for path, content in files.items():
            url = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}/contents/{path}"
            existing = await client.get(url)
            if isinstance(content, bytes):
                raw = content
            else:
                raw = str(content).encode("utf-8")
            payload = {
                "message": message,
                "content": base64.b64encode(raw).decode("ascii"),
            }
            if existing.status_code == 200:
                payload["sha"] = existing.json()["sha"]
            response = await client.put(url, json=payload)
            if response.status_code >= 400:
                raise core.HTTPException(502, f"GitHub write failed for {path}: {response.text[:300]}")


core.github_put_bundle = github_put_bundle_binary
