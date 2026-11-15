import io
from datetime import date

import pytest
from pypdf import PdfReader

from app.services.pdf import (
    CONTRACT_PLACEHOLDERS,
    _fetch_blocked,
    fmt_money,
    render_contract_text,
)
from tests.helpers import auth, make_world, signup

RENT = 300_000_000


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


async def _bill(w, through="2026-02-05"):
    await w.client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": through}, headers=w.oh
    )
    return (await w.client.get(f"/leases/{w.lease_id}/invoices", headers=w.oh)).json()


def test_money_format():
    assert fmt_money(300_000_000) == "3 000 000"
    assert fmt_money(12345) == "123.45" and fmt_money(-5000) == "-50"


def test_external_resources_blocked():
    with pytest.raises(ValueError):
        _fetch_blocked("file:///etc/passwd")


def test_sandbox_blocks_template_attacks_and_unknown_placeholders():
    ctx = {k: "x" for k in CONTRACT_PLACEHOLDERS}
    assert render_contract_text("Hi {{ tenant_name }}", ctx) == "Hi x"
    from app.errors import Unprocessable

    for bad in (
        "{{ nope }}",
        "{{ ''.__class__.__mro__ }}",
        "{% for %}",
        "{{ cycler.__init__.__globals__ }}",
    ):
        with pytest.raises(Unprocessable):
            render_contract_text(bad, ctx)


async def test_invoice_pdf_content_and_caching(client, storage):
    w = await make_world(client)
    inv = (await _bill(w))[0]
    r = await client.get(f"/invoices/{inv['id']}/pdf", headers=w.th)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    txt = text_of(r.content)
    assert inv["number"] in txt and "3 000 000" in txt and "HISOB-FAKTURA" in txt
    assert "yuridik maslahat emas" in txt
    assert any(k.startswith("documents/invoices/") for k in storage.objects)
    n = len(storage.objects)
    again = await client.get(f"/invoices/{inv['id']}/pdf", headers=w.th)
    assert again.content == r.content and len(storage.objects) == n  # served from storage


async def test_invoice_pdf_shows_previous_balance_and_void(client):
    w = await make_world(client)
    _jan, feb = sorted(await _bill(w), key=lambda i: i["period_start"])
    r = await client.get(f"/invoices/{feb['id']}/pdf", headers=w.oh)
    txt = text_of(r.content)
    assert "6 000 000" in txt  # previous 3 000 000 + current 3 000 000 = total due
    await client.post(f"/invoices/{feb['id']}/void", json={"reason": "x"}, headers=w.oh)
    assert "BEKOR QILINGAN" in text_of(
        (await client.get(f"/invoices/{feb['id']}/pdf", headers=w.oh)).content
    )


async def test_invoice_pdf_isolation(client):
    a, b = await make_world(client), await make_world(client)
    inv = (await _bill(b))[0]
    for h in (a.th, a.oh):
        assert (await client.get(f"/invoices/{inv['id']}/pdf", headers=h)).status_code == 403
    assert (await client.get(f"/invoices/{inv['id']}/pdf", headers=b.th)).status_code == 200
    assert (await client.get(f"/invoices/{inv['id']}/pdf")).status_code == 401


async def test_contract_default_custom_template_and_versions(client):
    w = await make_world(client)
    t = (await client.get("/settings/contract-template", headers=w.oh)).json()
    assert t["is_default"] and "{{ tenant_name }}" in t["body"]
    d1 = (await client.post(f"/leases/{w.lease_id}/contract", headers=w.oh)).json()
    assert d1["version"] == 1
    pdf = (await client.get(f"/documents/{d1['id']}/download", headers=w.th)).content
    txt = text_of(pdf)
    assert "FAKE Tenant" in txt and "3 000 000" in txt and "yuridik maslahat emas" in txt
    # custom template
    r = await client.put(
        "/settings/contract-template",
        headers=w.oh,
        json={"body": "MY CONTRACT for {{ tenant_name }} rent {{ monthly_rent }}"},
    )
    assert r.status_code == 200 and r.json()["version"] == 1
    d2 = (await client.post(f"/leases/{w.lease_id}/contract", headers=w.oh)).json()
    assert d2["version"] == 2
    assert "MY CONTRACT for FAKE Tenant rent 3 000 000" in text_of(
        (await client.get(f"/documents/{d2['id']}/download", headers=w.oh)).content
    )
    # old version still available (versioned storage)
    assert "IJARA SHARTNOMASI" in text_of(
        (await client.get(f"/documents/{d1['id']}/download", headers=w.oh)).content
    )
    docs = (await client.get(f"/leases/{w.lease_id}/documents", headers=w.th)).json()
    assert [d["version"] for d in docs] == [2, 1]


async def test_template_validation_and_permissions(client):
    w = await make_world(client)
    for body in ("Hello {{ unknown_placeholder }} and more", "Broken {% if %} template here"):
        r = await client.put("/settings/contract-template", headers=w.oh, json={"body": body})
        assert r.status_code == 422 and r.json()["error"]["code"] == "template_error"
    assert (
        await client.put(
            "/settings/contract-template",
            headers=w.th,
            json={"body": "Tenant tries this {{ tenant_name }}"},
        )
    ).status_code == 403
    assert (await client.get("/settings/contract-template", headers=w.th)).status_code == 403
    assert (await client.post(f"/leases/{w.lease_id}/contract", headers=w.th)).status_code == 403
    # script/html in a template is plain text, never executed or fetched
    ok = await client.put(
        "/settings/contract-template",
        headers=w.oh,
        json={"body": '<img src="file:///etc/passwd"><script>x</script> {{ tenant_name }}'},
    )
    assert ok.status_code == 200
    d = (await client.post(f"/leases/{w.lease_id}/contract", headers=w.oh)).json()
    assert "<script>" in text_of(
        (await client.get(f"/documents/{d['id']}/download", headers=w.oh)).content
    )


async def test_documents_isolation(client):
    a, b = await make_world(client), await make_world(client)
    d = (await client.post(f"/leases/{b.lease_id}/contract", headers=b.oh)).json()
    for h in (a.th, a.oh):
        assert (await client.get(f"/documents/{d['id']}/download", headers=h)).status_code == 403
        assert (await client.get(f"/leases/{b.lease_id}/documents", headers=h)).status_code == 403
    s = await signup(client)
    assert (await client.get("/settings/contract-template", headers=auth(s))).status_code == 200
    assert date.today()
