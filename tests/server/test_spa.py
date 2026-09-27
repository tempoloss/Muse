from pathlib import Path

import httpx

from tests.server.support import WRITE


async def test_client_routes_fall_back_to_the_shell_with_a_csp(client: httpx.AsyncClient) -> None:
    response = await client.get("/library/whatever")

    assert (response.status_code, response.text) == (200, "<p>shell</p>")
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "DENY"


async def test_built_files_get_their_type_and_cache_policy(client: httpx.AsyncClient) -> None:
    asset = await client.get("/assets/a.js")
    worker = await client.get("/sw.js")
    head = await client.head("/")

    assert asset.headers["content-type"] == "text/javascript; charset=utf-8"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "content-security-policy" not in asset.headers
    assert worker.headers["cache-control"] == "no-cache"
    assert (head.status_code, head.content) == (200, b"")


async def test_files_outside_the_web_directory_are_never_served(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    response = await client.get("/%2e%2e/secret.txt")

    assert response.text == "<p>shell</p>"


async def test_unknown_api_paths_are_json_404_without_a_session(client: httpx.AsyncClient) -> None:
    for path in ("/api/nope", "/api"):
        response = await client.get(path)

        assert (response.status_code, response.json()) == (404, {"detail": "not found"})
        assert response.headers["content-type"] == "application/json"
    assert (await client.get("/api/nope")).headers["cache-control"] == "no-store"


async def test_a_missing_build_is_reported_as_503(client: httpx.AsyncClient, web_dir: Path) -> None:
    (web_dir / "index.html").unlink()

    response = await client.get("/")

    assert (response.status_code, response.text) == (503, "web client not built")
    assert response.headers["content-type"].startswith("text/plain")


async def test_state_changes_need_an_allowed_origin(client: httpx.AsyncClient) -> None:
    missing = await client.post("/api/plays", json={})
    foreign = await client.post("/api/plays", json={}, headers={"Origin": "https://evil.example"})
    allowed = await client.post("/api/plays", json={}, headers=WRITE)

    for response in (missing, foreign):
        assert (response.status_code, response.json()) == (403, {"detail": "bad origin"})
        assert response.headers["cache-control"] == "no-store"
    assert allowed.status_code == 405


async def test_plain_http_visitors_are_sent_to_https(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/library/x?tab=1", headers={"cf-visitor": '{"scheme": "http"}'}, follow_redirects=False
    )

    assert response.status_code == 308
    assert response.headers["location"] == "https://testserver.local/library/x?tab=1"
