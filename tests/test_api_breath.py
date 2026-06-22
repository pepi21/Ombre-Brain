"""Tiny dashboard route checks without pytest."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _route_by_path(server, path):
    for route in server.mcp._custom_starlette_routes:
        if route.path == path:
            return route
    raise AssertionError(f"missing route: {path}")


def _payload(response):
    return json.loads(response.body.decode("utf-8"))


async def test_api_breath_route_returns_ranked_active_buckets():
    import server

    route = _route_by_path(server, "/api/breath")

    class FakeBucketManager:
        async def list_all(self, include_archive=False):
            assert include_archive is False
            return [
                {
                    "id": "low",
                    "content": "plain memory",
                    "metadata": {"name": "Low", "type": "dynamic", "score": 2},
                },
                {
                    "id": "resolved",
                    "content": "old done memory",
                    "metadata": {"name": "Done", "resolved": True, "score": 999},
                },
                {
                    "id": "pin",
                    "content": "[[core]] memory",
                    "metadata": {"name": "Pinned", "pinned": True, "score": 999},
                },
            ]

    class FakeDecayEngine:
        def calculate_score(self, metadata):
            return metadata["score"]

    old_bucket_mgr = server.bucket_mgr
    old_decay_engine = server.decay_engine
    try:
        server.bucket_mgr = FakeBucketManager()
        server.decay_engine = FakeDecayEngine()
        response = await route.endpoint(SimpleNamespace(query_params={"n": "10"}))
    finally:
        server.bucket_mgr = old_bucket_mgr
        server.decay_engine = old_decay_engine

    data = _payload(response)
    assert [item["id"] for item in data["results"]] == ["pin", "low"]
    assert data["buckets"] == data["results"]
    assert data["total"] == 2
    assert data["results"][0]["content_preview"] == "core memory"


def test_frontend_static_assets_are_wired():
    import server

    for route in ["/", "/dashboard", "/static/{name}", "/favicon.ico"]:
        _route_by_path(server, route)
    for name in ["icon.svg", "favicon.svg", "manifest.json", "RRPL.ttf"]:
        assert Path("frontend", name).exists(), name


if __name__ == "__main__":
    asyncio.run(test_api_breath_route_returns_ranked_active_buckets())
    test_frontend_static_assets_are_wired()
    print("dashboard route checks passed")
