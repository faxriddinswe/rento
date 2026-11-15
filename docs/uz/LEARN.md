# Rento — o'rganish qo'llanmasi (intervyuga tayyorgarlik)

## 1–2-bosqich: skelet va ma'lumotlar modeli
**Nima qurildi:** FastAPI, PostgreSQL, Alembic, MinIO; jadvallar va cheklovlar.
**Nega:** qoidalarni (ijaralar kesishmasligi, hisob daftari o'zgarmasligi, faktura jami = qatorlar yig'indisi) ilova kodiga emas, bazaning o'ziga yuklash — xato kod ham ularni buza olmaydi.
**Savollar:** (1) *Ijaralar kesishmasligini qanday kafolatladingiz?* — `btree_gist` bilan EXCLUDE constraint, `daterange` bo'yicha. (2) *Nega pul BIGINT?* — float xato beradi; tiyin butun son, yig'indi aniq. (3) *Ledger nega append-only?* — audit va tuzatish teskari yozuv bilan; trigger UPDATE/DELETE ni taqiqlaydi.
## 3-bosqich: Auth va RBAC
**Qanday:** JWT access + aylanuvchi refresh (qayta ishlatilsa butun oila bekor), argon2, imzolangan bir martalik taklif havolasi, `can(actor, action, resource)` yagona funksiya.
**Savollar:** (1) *Refresh reuse detection nima?* — eski token qayta kelsa o'g'irlik belgisi, oila bekor qilinadi. (2) *RBAC nega bitta funksiya?* — tekshiruv tarqalib ketmaydi, matritsa testi bilan qamrab olinadi. (3) *Ijarachi boshqaning ma'lumotini ko'rmasligini qanday isbotladingiz?* — har endpoint uchun izolyatsiya testlari.
## 4–5-bosqich: obyektlar va ko'rsatkichlar
**Qanday:** tarif tarixi (yopilgan oraliqlar), presigned POST orqali rasm to'g'ridan MinIO'ga, server `HEAD` bilan tekshiradi, kalit ijarachi prefiksida bo'lishi shart.
**Savollar:** (1) *Presigned PUT o'rniga POST nega?* — POST policy hajm va turni saqlash tomonida majburlaydi. (2) *Ko'rsatkich kichik bo'lsa?* — rad etiladi; egasi "almashtirilgan hisoblagich" bazasini kiritadi. (3) *Rasm kalitini soxtalashtirish?* — prefiks tekshiruvi.
## 6-bosqich: hisob-kitob yadrosi
**Qanday:** sof funksiya `build_invoice` (DB yo'q), hypothesis bilan xossalar testi; ARQ kron kunlik; `UNIQUE(lease_id, period_start)` + qator qulfi = idempotent.
**Savollar:** (1) *Idempotentlik qanday?* — unique cheklov, qulf, qayta ishga tushirish dublikat yaratmaydi. (2) *Tarif o'zgarsa?* — iste'mol keyingi ko'rsatkich sanasidagi tarif bilan (D005). (3) *Ko'rsatkich kelmasa?* — "kutilmoqda" nol qator, keyingi fakturada tuzatish qatori; chiqarilgan faktura o'zgarmaydi.
## 7-bosqich: to'lovlar va daftar
**Qanday:** FIFO taqsimlash (sof funksiya + xossa testlari), ortiqcha to'lov kreditga aylanadi, teskari yozuvlar.
**Savollar:** (1) *FIFO nima?* — eng eski faktura birinchi yopiladi. (2) *To'lov bekor qilinsa?* — teskari yozuv va manfiy taqsimot, kredit qayta taqsimlanadi. (3) *Balans qayerda?* — saqlanmaydi, daftardan hisoblanadi.
## 8-bosqich: PDF va Telegram
**Qanday:** Jinja2 sandbox + WeasyPrint (tashqi URL bloklangan); outbox pattern (dedupe_key unique).
**Savollar:** (1) *Shablon xavfsizligi?* — sandbox, natija HTML-escape, URL fetcher bloklangan. (2) *Nega outbox?* — tranzaksiya bekor bo'lsa xabar ketmaydi, takror yuborilmaydi. (3) *Telegram ulash?* — imzolangan deep link `/start <token>`.
## 9-bosqich: Frontend
Next.js App Router, TanStack Query, OpenAPI'dan generatsiya qilingan tiplar, mobil-birinchi; token localStorage'da (XSS savdosi — kamchilik sifatida ayting). **Savol:** *Nega rewrites?* — bitta origin, CORS yo'q.
## 10–11: Xavfsizlik, zaxira, deploy
Audit jurnali `owner_id` bo'yicha; pg_dump + tiklash sinalgan; deploy skripti tayyor, lekin serverga qo'llanmagan (BLOCKERS).
