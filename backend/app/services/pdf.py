"""PDF rendering: Jinja2 (sandboxed for owner-editable text) + WeasyPrint."""

import asyncio
import html
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from weasyprint import HTML

from app.errors import Unprocessable

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
DISCLAIMER = "Namuna hujjat — yuridik maslahat emas. / Sample document, not legal advice."

_semaphore = asyncio.Semaphore(1)  # WeasyPrint is memory hungry: render one PDF at a time

DEFAULT_CONTRACT = """IJARA SHARTNOMASI (NAMUNA)

Sana: {{ today }}

Ijaraga beruvchi: {{ owner_name }}
Ijarachi: {{ tenant_name }}

1. Shartnoma predmeti: «{{ property_name }}», {{ address }}, "{{ unit_name }}" xonadon/bino.
2. Muddat: {{ start_date }} dan {{ end_date }} gacha.
3. Oylik ijara haqi: {{ monthly_rent }} so'm. Hisob-kitob kuni: har oyning {{ billing_day }}-sanasi.
   To'lov muddati: hisob-faktura sanasidan {{ due_days }} kun ichida.
4. Kafolat puli (depozit): {{ deposit }} so'm.
5. Kommunal xizmatlar hisoblagich ko'rsatkichlari bo'yicha, amaldagi tarifda alohida to'lanadi.
6. Tomonlar o'z majburiyatlarini bajarishga rozilik bildiradilar.

Ijaraga beruvchi: ____________        Ijarachi: ____________
"""


def _fetch_blocked(url: str, *args: Any, **kwargs: Any) -> Any:
    raise ValueError(f"External resources are disabled in PDFs: {url}")


def fmt_money(minor: int) -> str:
    """12345600 -> '123 456' (so'm); keeps tiyin only when non-zero."""
    sign = "-" if minor < 0 else ""
    som, tiyin = divmod(abs(minor), 100)
    s = f"{som:,}".replace(",", " ")
    return f"{sign}{s}" + (f".{tiyin:02d}" if tiyin else "")


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)
_env.filters["money"] = fmt_money
_env.filters["date"] = fmt_date


def _html_to_pdf(markup: str) -> bytes:
    return bytes(HTML(string=markup, url_fetcher=_fetch_blocked).write_pdf())


async def html_to_pdf(markup: str) -> bytes:
    async with _semaphore:
        return await asyncio.to_thread(_html_to_pdf, markup)


async def render_invoice_pdf(ctx: dict[str, Any]) -> bytes:
    markup = _env.get_template("invoice.html").render(**ctx, disclaimer=DISCLAIMER)
    return await html_to_pdf(markup)


_sandbox = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def render_contract_text(body: str, ctx: dict[str, Any]) -> str:
    """Render owner-editable template text (placeholders like {{ tenant_name }}) in a sandbox."""
    try:
        return _sandbox.from_string(body).render(**ctx)
    except TemplateError as exc:
        raise Unprocessable(f"Template error: {exc}", code="template_error") from exc


async def render_contract_pdf(body: str, ctx: dict[str, Any]) -> bytes:
    text = render_contract_text(body, ctx)
    markup = _env.get_template("contract.html").render(
        text=html.escape(text), disclaimer=DISCLAIMER, title=ctx.get("tenant_name", "")
    )
    return await html_to_pdf(markup)


CONTRACT_PLACEHOLDERS = [
    "today",
    "owner_name",
    "tenant_name",
    "property_name",
    "address",
    "unit_name",
    "start_date",
    "end_date",
    "monthly_rent",
    "deposit",
    "billing_day",
    "due_days",
]
