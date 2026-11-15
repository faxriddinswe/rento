from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.api.deps import CurrentActor, Session, StorageDep, authorize
from app.domain.policies import Action
from app.errors import NotFound
from app.models.entities import (
    ContractTemplate,
    Document,
    Invoice,
    InvoiceLine,
    Lease,
    PaymentAllocation,
    Property,
    Unit,
    User,
)
from app.schemas import DocumentOut, TemplateIn, TemplateOut
from app.services.access import get_lease
from app.services.audit import audit
from app.services.clock import today_local
from app.services.pdf import (
    CONTRACT_PLACEHOLDERS,
    DEFAULT_CONTRACT,
    fmt_date,
    fmt_money,
    render_contract_pdf,
    render_contract_text,
    render_invoice_pdf,
)

router = APIRouter(tags=["documents"])
PDF = "application/pdf"


async def _lease_context(session: Session, lease: Lease) -> dict[str, str]:
    unit = await session.get(Unit, lease.unit_id)
    assert unit is not None
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    owner = await session.get(User, prop.owner_id)
    tenant = await session.get(User, lease.tenant_id) if lease.tenant_id else None
    return {
        "today": fmt_date(today_local()),
        "owner_name": owner.full_name if owner else "",
        "tenant_name": tenant.full_name if tenant else "________________",
        "property_name": prop.name,
        "address": prop.address,
        "unit_name": unit.name,
        "start_date": fmt_date(lease.start_date),
        "end_date": fmt_date(lease.end_date) if lease.end_date else "muddatsiz",
        "monthly_rent": fmt_money(lease.monthly_rent),
        "deposit": fmt_money(lease.deposit),
        "billing_day": str(lease.billing_day),
        "due_days": str(lease.due_days),
    }


async def _latest_template(session: Session, owner_id: UUID) -> ContractTemplate | None:
    return (
        await session.execute(
            select(ContractTemplate)
            .where(ContractTemplate.owner_id == owner_id)
            .order_by(ContractTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/settings/contract-template", response_model=TemplateOut)
async def get_template(session: Session, actor: CurrentActor) -> TemplateOut:
    if actor.role != "owner":
        from app.errors import Forbidden

        raise Forbidden("Only the owner manages the contract template")
    t = await _latest_template(session, actor.id)
    return TemplateOut(
        version=t.version if t else 0,
        body=t.body if t else DEFAULT_CONTRACT,
        is_default=t is None,
        placeholders=CONTRACT_PLACEHOLDERS,
    )


@router.put("/settings/contract-template", response_model=TemplateOut)
async def put_template(body: TemplateIn, session: Session, actor: CurrentActor) -> TemplateOut:
    from app.domain.policies import Resource

    authorize(actor, Action.TEMPLATE_MANAGE, Resource(owner_id=actor.id))
    sample = {k: "x" for k in CONTRACT_PLACEHOLDERS}
    render_contract_text(body.body, sample)  # validates syntax/placeholders; 422 on error
    prev = await _latest_template(session, actor.id)
    t = ContractTemplate(
        owner_id=actor.id, version=(prev.version if prev else 0) + 1, body=body.body
    )
    session.add(t)
    await session.flush()
    await audit(
        session,
        actor.id,
        "template.update",
        "contract_template",
        t.id,
        None,
        {"version": t.version},
    )
    return TemplateOut(
        version=t.version, body=t.body, is_default=False, placeholders=CONTRACT_PLACEHOLDERS
    )


@router.post("/leases/{lease_id}/contract", response_model=DocumentOut, status_code=201)
async def generate_contract(
    lease_id: UUID, session: Session, actor: CurrentActor, storage: StorageDep
) -> Document:
    """Render the owner's template for this lease into a new, versioned PDF."""
    lease, prop, res = await get_lease(session, lease_id)
    authorize(actor, Action.DOCUMENT_GENERATE, res)
    tmpl = await _latest_template(session, prop.owner_id)
    ctx = await _lease_context(session, lease)
    pdf = await render_contract_pdf(tmpl.body if tmpl else DEFAULT_CONTRACT, ctx)
    version = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(Document.version), 0)).where(
                    Document.kind == "contract", Document.ref_id == lease.id
                )
            )
            or 0
        )
        + 1
    )
    key = f"documents/contracts/{lease.id}/v{version}.pdf"
    await storage.put(key, pdf, PDF)
    doc = Document(
        kind="contract",
        ref_id=lease.id,
        lease_id=lease.id,
        version=version,
        storage_key=key,
        created_by=actor.id,
    )
    session.add(doc)
    await session.flush()
    await audit(
        session,
        actor.id,
        "document.contract",
        "lease",
        lease.id,
        None,
        {"version": version, "template_version": tmpl.version if tmpl else 0},
    )
    return doc


@router.get("/leases/{lease_id}/documents", response_model=list[DocumentOut])
async def list_documents(lease_id: UUID, session: Session, actor: CurrentActor) -> list[Document]:
    _, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.DOCUMENT_READ, res)
    return list(
        (
            await session.execute(
                select(Document)
                .where(Document.lease_id == lease_id)
                .order_by(Document.kind, Document.version.desc())
            )
        ).scalars()
    )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID, session: Session, actor: CurrentActor, storage: StorageDep
) -> Response:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFound("Document not found")
    _, _, res = await get_lease(session, doc.lease_id)
    authorize(actor, Action.DOCUMENT_READ, res)
    return Response(
        await storage.get(doc.storage_key),
        media_type=PDF,
        headers={"content-disposition": f'attachment; filename="{doc.kind}-v{doc.version}.pdf"'},
    )


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: UUID, session: Session, actor: CurrentActor, storage: StorageDep
) -> Response:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("Invoice not found")
    lease, _, res = await get_lease(session, inv.lease_id)
    authorize(actor, Action.INVOICE_READ, res)
    headers = {"content-disposition": f'attachment; filename="{inv.number}.pdf"'}
    key = f"documents/invoices/{inv.id}/v1.pdf"
    # issued invoices are immutable -> render once, then serve from storage
    if inv.status == "issued" and await storage.head(key) is not None:
        return Response(await storage.get(key), media_type=PDF, headers=headers)
    ctx = await _lease_context(session, lease)
    lines = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == inv.id)
                .order_by(InvoiceLine.sort)
            )
        )
        .scalars()
        .all()
    )
    paid = int(
        await session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.invoice_id == inv.id
            )
        )
        or 0
    )
    pdf = await render_invoice_pdf(
        {
            "invoice": inv,
            "lines": lines,
            "paid": paid,
            "tenant_name": ctx["tenant_name"],
            "property_name": ctx["property_name"],
            "unit_name": ctx["unit_name"],
            "address": ctx["address"],
        }
    )
    if inv.status == "issued":
        await storage.put(key, pdf, PDF)
        exists = await session.scalar(
            select(Document.id).where(Document.kind == "invoice", Document.ref_id == inv.id)
        )
        if exists is None:
            session.add(
                Document(
                    kind="invoice",
                    ref_id=inv.id,
                    lease_id=lease.id,
                    version=1,
                    storage_key=key,
                    created_by=actor.id,
                )
            )
    return Response(pdf, media_type=PDF, headers=headers)
