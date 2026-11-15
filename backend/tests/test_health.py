async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert "x-request-id" in r.headers


async def test_ready_reports_dependencies(client):
    r = await client.get("/ready")
    body = r.json()
    assert set(body["checks"]) == {"db", "redis", "storage"}


async def test_unknown_route_uses_error_format(client):
    r = await client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "http_error"
