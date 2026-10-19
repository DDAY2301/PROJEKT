"""Offline regression tests for Project Visibility local Ollama inventory.

No model downloads, no inference, no customer repository writes.
"""
import asyncio
import unittest
from unittest.mock import patch

import httpx

from api import model_router as router


class InventorySmoke(unittest.TestCase):
    def test_inventory_parses_ollama_tags(self):
        tags = {"models": [
            {"name": "qwen3.5:4b", "size": 3500000000,
             "details": {"parameter_size": "4B", "quantization_level": "Q4_K_M"}},
            {"name": "", "size": 1},
        ]}
        found = router._inventory_names(tags)
        self.assertEqual(list(found), ["qwen3.5:4b"])
        self.assertEqual(found["qwen3.5:4b"]["parameters"], "4B")

    def test_catalog_never_confuses_installed_with_loaded(self):
        installed = router._inventory_names({"models": [
            {"name": "qwen3.5:4b", "size": 3500000000},
            {"name": "qwen2.5-coder:7b", "size": 4700000000},
        ]})
        loaded = router._inventory_names({"models": [{"name": "qwen2.5-coder:7b", "size_vram": 1000}]})
        entries = {row["name"]: row for row in router._model_catalog(installed, loaded, active="qwen3.5:4b")}
        self.assertTrue(entries["qwen3.5:4b"]["installed"])
        self.assertFalse(entries["qwen3.5:4b"]["loaded"])
        self.assertTrue(entries["qwen3.5:4b"]["selected"])
        self.assertTrue(entries["qwen2.5-coder:7b"]["loaded"])
        self.assertFalse(entries["qwen2.5-coder:7b"]["selected"])
        self.assertFalse(entries["qwen3.5:9b"]["installed"])

    def test_models_with_no_names_cannot_be_reported_running(self):
        self.assertEqual(router._inventory_names({"models": [{"digest": "abc"}]}), {})
        self.assertEqual(router._inventory_names(None), {})

    def test_offline_ollama_never_reports_online(self):
        class OfflineClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, url):
                raise httpx.ConnectError("offline")

        with patch.object(router.httpx, "AsyncClient", OfflineClient):
            result = asyncio.run(router.local_model_runtime(user_id="ci-user"))
        self.assertFalse(result["ollama_online"])
        self.assertFalse(any(x["loaded"] for x in result["models"]))
        self.assertIn("active_model", result)


if __name__ == "__main__":
    unittest.main()
