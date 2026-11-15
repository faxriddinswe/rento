"""Integration test against the real MinIO from docker compose (no fakes)."""

import uuid

import httpx

from app.services.storage import S3Storage


async def test_presigned_post_roundtrip_and_policy_enforcement():
    st = S3Storage()
    await st.ensure_bucket()
    await st.ping()
    key = f"tenants/{uuid.uuid4()}/readings/{uuid.uuid4()}.png"
    post = await st.presign_post(key, "image/png", max_bytes=1000)
    async with httpx.AsyncClient() as http:
        ok = await http.post(
            post.url, data=post.fields, files={"file": ("a.png", b"\x89PNG" + b"0" * 100)}
        )
        assert ok.status_code in (200, 201, 204), ok.text
        info = await st.head(key)
        assert info is not None and info.content_type == "image/png" and info.size == 104
        assert (await st.get(key)).startswith(b"\x89PNG")
        assert "X-Amz-Signature" in await st.presign_get(key)
        # storage-side policy: too big is refused by MinIO itself
        key2 = key.replace(".png", "-big.png")
        post2 = await st.presign_post(key2, "image/png", max_bytes=1000)
        big = await http.post(post2.url, data=post2.fields, files={"file": ("a.png", b"0" * 5000)})
        assert big.status_code == 400
        assert await st.head(key2) is None
        # wrong content type is refused by policy too
        post3 = await st.presign_post(key2, "image/png", max_bytes=1000)
        fields = {**post3.fields, "Content-Type": "text/html"}
        bad = await http.post(post3.url, data=fields, files={"file": ("a.png", b"abc")})
        assert bad.status_code == 403
