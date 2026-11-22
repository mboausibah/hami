"""Synthetic corpus generator (fictional brands only).

Writes Arabic, English and mixed pages to testsites/corpus/<kit>/<n>.html plus labels.csv:
- fraudulent kits: task scams (several templates), advance-fee recruitment, money-mule commission,
  gambling deposits, guaranteed-return investment, fake shop, card/OTP phishing
- legitimate look-alikes: recruitment agencies, careers pages, gig platforms (referral codes,
  withdrawals), delivery jobs (earn per order), shops (discounts), banks (deposits, OTP warnings),
  regulated brokers, loyalty programs (VIP/levels)
- inconclusive: thin, parked or ambiguous pages (never used for training)

Deterministic (seeded) so judges can reproduce training without our private data:
    python testsites/generator/generate.py
"""
from __future__ import annotations

import csv
import html
import random
import shutil
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "corpus"
SEED = 20261122

SYL = ["nova", "zen", "orbi", "luma", "vexa", "kora", "tali", "miro", "sera", "dano", "quil", "faro", "bexi",
       "rila", "toma", "yuvo", "pexa", "hali", "suna", "gavo", "nexi", "olan", "ziva", "cora"]
SUFFIX = ["mart", "mall", "hub", "go", "ly", "ora", "ix", "verse", "works", "link", "point", "zone"]
AR_BRANDS = ["نوفا", "زينا", "لومار", "كورال", "تاليا", "ميرا", "سيرين", "دانة", "فارو", "رايا", "هالة", "سنا"]
CITIES_EN = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain", "Ras Al Khaimah"]
CITIES_AR = ["دبي", "أبوظبي", "الشارقة", "عجمان", "العين", "رأس الخيمة"]


def brand(r: random.Random) -> str:
    return (r.choice(SYL) + r.choice(SUFFIX)).capitalize()


def ar_digits(n: int | str) -> str:
    return str(n).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def maybe_ar_digits(r: random.Random, n: int | str) -> str:
    return ar_digits(n) if r.random() < 0.5 else str(n)


def page(title: str, body: str, lang: str, css_prefix: str, r: random.Random) -> str:
    direction = "rtl" if lang == "ar" else "ltr"
    return (f'<!doctype html><html lang="{lang}" dir="{direction}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
            f'<style>.{css_prefix}-wrap{{max-width:960px;margin:auto;font-family:sans-serif}}</style></head>'
            f'<body><div class="{css_prefix}-wrap">{body}</div></body></html>')


def p(text: str, cls: str = "") -> str:
    return f'<p class="{cls}">{html.escape(text)}</p>' if cls else f"<p>{html.escape(text)}</p>"


def table(rows: list[list[str]], cls: str) -> str:
    out = [f'<table class="{cls}">']
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def form(fields: list[tuple[str, str, str]], cls: str, button: str) -> str:
    out = [f'<form class="{cls}" onsubmit="return false">']
    for name, ftype, label in fields:
        out.append(f'<label for="{name}">{html.escape(label)}</label><input id="{name}" name="{name}" type="{ftype}" '
                   f'placeholder="{html.escape(label)}">')
    out.append(f'<button type="button">{html.escape(button)}</button></form>')
    return "".join(out)


def wa(r: random.Random) -> str:
    return f'<a class="cs" href="https://wa.me/9715{r.randint(10000000, 99999999)}">WhatsApp</a>'


def tg(r: random.Random) -> str:
    return f'<a class="cs" href="https://t.me/{r.choice(SYL)}_support{r.randint(1, 99)}">Telegram</a>'


# ------------------------------------------------------------------------------------------------
# Fraudulent kits
# ------------------------------------------------------------------------------------------------
def task_scam(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r)
    amt = r.choice([100, 200, 300, 500, 800, 1000, 1500, 2000])
    levels = r.randint(3, 6)
    rows_en = [["Level", "Deposit", "Daily orders", "Commission"]] + [
        [f"VIP {i}", f"AED {amt * i}", str(20 + 10 * i), f"{0.4 * i:.1f}%"] for i in range(1, levels + 1)]
    rows_ar = [["المستوى", "الإيداع", "الطلبات اليومية", "العمولة"]] + [
        [f"VIP {maybe_ar_digits(r, i)}", f"{maybe_ar_digits(r, amt * i)} درهم", maybe_ar_digits(r, 20 + 10 * i),
         f"{0.4 * i:.1f}%"] for i in range(1, levels + 1)]
    tags = ["deposit_to_unlock"]
    task_en = r.choice(["rate products", "like videos", "complete hotel reviews", "grab orders", "optimize products",
                        "watch short dramas"])
    task_ar = r.choice(["تقييم المنتجات", "الإعجاب بالفيديوهات", "تقييم الفنادق", "خطف الطلبات", "مشاهدة المسلسلات القصيرة"])
    if lang == "en":
        parts = [f'<header class="{css}-top"><span class="{css}-logo">{b} VIP</span></header>',
                 f"<h1>{b} — part-time online jobs in {r.choice(CITIES_EN)}</h1>",
                 p(f"Work from your phone: {task_en} and earn AED {r.randint(150, 900)} per day."),
                 p(r.choice([f"Recharge AED {amt} to unlock paid tasks.",
                             f"Deposit AED {amt} to activate your account and unlock VIP tasks.",
                             f"Top up {amt} dirhams to upgrade your level and start earning.",
                             f"To withdraw your commission you must recharge AED {amt} first."])),
                 table(rows_en, f"{css}-vip"),
                 p(r.choice(["Withdrawal is available only after completing 40 orders.",
                             "Minimum withdrawal AED 100. Withdrawals require completing the current task set.",
                             "Withdrawals are frozen until your account balance is recharged."])),
                 form([("inviteCode", "text", "Invitation code"), ("phone", "tel", "Phone number")], f"{css}-reg",
                      "Join now"),
                 p("Customer service available 24/7:") + (wa(r) if r.random() < 0.7 else tg(r))]
        title = f"{b} VIP | Daily tasks"
    else:
        parts = [f'<header class="{css}-top"><span class="{css}-logo">{r.choice(AR_BRANDS)} VIP</span></header>',
                 f"<h1>وظائف بدوام جزئي من المنزل في {r.choice(CITIES_AR)}</h1>",
                 p(f"اعمل من هاتفك: {task_ar} واربح {maybe_ar_digits(r, r.randint(150, 900))} درهم يوميًا."),
                 p(r.choice([f"اشحن {maybe_ar_digits(r, amt)} درهم لفتح المهام المدفوعة.",
                             f"قم بإيداع {maybe_ar_digits(r, amt)} درهم لتفعيل حسابك وفتح مهام VIP.",
                             f"للترقية إلى المستوى التالي اشحن رصيدك بمبلغ {maybe_ar_digits(r, amt)} درهم.",
                             f"لتتمكن من السحب يجب شحن {maybe_ar_digits(r, amt)} درهم أولاً."])),
                 table(rows_ar, f"{css}-vip"),
                 p(r.choice(["السحب متاح فقط بعد إكمال ٤٠ مهمة.", "الحد الأدنى للسحب ١٠٠ درهم بعد إكمال المهام اليومية.",
                             "يتم تجميد السحب حتى إعادة شحن الرصيد."])),
                 form([("inviteCode", "text", "رمز الدعوة"), ("phone", "tel", "رقم الهاتف")], f"{css}-reg", "انضم الآن"),
                 p("خدمة العملاء على مدار الساعة:") + (wa(r) if r.random() < 0.7 else tg(r))]
        title = f"{r.choice(AR_BRANDS)} VIP | مهام يومية"
        if lang == "mixed":
            parts.insert(2, p(f"Earn daily commission with {b}. VIP members unlock more orders."))
    r.shuffle(parts[2:-1])
    if r.random() < 0.5:
        tags.append("off_platform_contact")
    if r.random() < 0.3:
        tags.append("brand_misuse")
    return page(title, "".join(parts), "ar" if lang != "en" else "en", css, r), tags


def advance_fee(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r) + " Recruitment"
    fee = r.choice([250, 350, 500, 750, 1200])
    if lang == "en":
        job = r.choice(["housemaid", "driver", "nanny", "warehouse helper", "hotel receptionist", "cleaner"])
        body = "".join([
            f'<div class="{css}-hdr">{b}</div>', f"<h1>Urgent hiring: {job} jobs in {r.choice(CITIES_EN)}</h1>",
            p(f"Salary AED {r.randint(2500, 6000)} plus accommodation. Visa guaranteed within 7 days."),
            p(r.choice([f"Pay the registration fee of AED {fee} to secure your position.",
                        f"A refundable processing fee of AED {fee} is required before the interview.",
                        f"Candidates must pay AED {fee} training fee before starting the job.",
                        f"Pay AED {fee} to get the job offer letter today."])),
            p("Send the receipt on WhatsApp to confirm your slot. Limited seats."), wa(r),
            form([("fullname", "text", "Full name"), ("passport", "text", "Passport number")], f"{css}-apply", "Apply")])
        title = f"{b} | Jobs in UAE"
    else:
        job = r.choice(["عاملة منزلية", "سائق", "مربية", "عامل مستودع", "موظف استقبال"])
        body = "".join([
            f'<div class="{css}-hdr">{r.choice(AR_BRANDS)} للتوظيف</div>', f"<h1>مطلوب {job} فورًا في {r.choice(CITIES_AR)}</h1>",
            p(f"راتب {maybe_ar_digits(r, r.randint(2500, 6000))} درهم مع السكن. تأشيرة مضمونة خلال ٧ أيام."),
            p(r.choice([f"ادفع رسوم التسجيل {maybe_ar_digits(r, fee)} درهم لحجز الوظيفة.",
                        f"رسوم المعالجة {maybe_ar_digits(r, fee)} درهم مطلوبة قبل المقابلة.",
                        f"يجب دفع رسوم التدريب {maybe_ar_digits(r, fee)} درهم قبل بدء العمل."])),
            p("أرسل الإيصال عبر واتساب لتأكيد مقعدك. المقاعد محدودة."), wa(r)])
        title = f"{r.choice(AR_BRANDS)} للتوظيف"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["advance_fee", "off_platform_contact"]


def money_mule(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r) + " Payments"
    pct = r.choice([3, 5, 8, 10])
    if lang == "en":
        body = "".join([
            f"<h1>{b}: remote payment processing assistant</h1>",
            p(f"Receive customer payments into your personal bank account and transfer the funds to our partners. "
              f"Keep {pct}% commission on every transfer."),
            p("No experience needed. Work 1-2 hours a day from home. Weekly bonus for fast transfers."),
            p(r.choice(["Use your own account to receive and forward payments.",
                        "Money transfer agent wanted: move funds and earn a commission on each payment."])),
            tg(r), form([("name", "text", "Name"), ("bank", "text", "Bank name")], f"{css}-f", "Start")])
        title = f"{b} | Remote job"
    else:
        body = "".join([
            f"<h1>{r.choice(AR_BRANDS)}: مساعد معالجة مدفوعات عن بعد</h1>",
            p(f"استلام دفعات العملاء على حسابك البنكي ثم تحويل الأموال إلى شركائنا مع عمولة {maybe_ar_digits(r, pct)}% على كل تحويل."),
            p("لا حاجة للخبرة. ساعة إلى ساعتين يوميًا من المنزل."), tg(r)])
        title = "وظيفة عن بعد"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["commission_transfer", "off_platform_contact"]


def gambling(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r) + " Casino"
    bonus = r.choice([100, 150, 200, 300])
    if lang == "en":
        body = "".join([f'<div class="{css}-logo">{b}</div>', f"<h1>Play slots and live casino in AED</h1>",
                        p(f"First deposit bonus {bonus}%! Deposit AED {r.choice([50, 100, 200])} and get free spins."),
                        p("Instant withdrawals. Sports betting, roulette, baccarat and jackpot games."),
                        form([("user", "text", "Username"), ("pw", "password", "Password")], f"{css}-l", "Deposit now"), wa(r)])
        title = f"{b} | Bet now"
    else:
        body = "".join([f'<div class="{css}-logo">{r.choice(AR_BRANDS)} كازينو</div>', "<h1>العب السلوتس والكازينو المباشر بالدرهم</h1>",
                        p(f"مكافأة الإيداع الأول {maybe_ar_digits(r, bonus)}%! أودع {maybe_ar_digits(r, 100)} درهم واحصل على لفات مجانية."),
                        p("سحب فوري. مراهنات رياضية وروليت وجاكبوت."), wa(r)])
        title = "كازينو | راهن الآن"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["gambling_deposit"]


def investment(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r) + " Capital"
    d = r.choice([2, 3, 5, 8])
    if lang == "en":
        body = "".join([f"<h1>{b} — AI trading with guaranteed returns</h1>",
                        p(f"Earn {d}% daily profit on your deposit. Guaranteed profits, risk-free."),
                        table([["Plan", "Deposit", "Daily return"], ["Silver", "AED 1,000", f"{d}%"],
                               ["Gold", "AED 5,000", f"{d + 1}%"]], f"{css}-plans"),
                        p("Double your money in 30 days. Withdraw anytime after 15 days."), tg(r)])
        title = f"{b} | Invest"
    else:
        body = "".join([f"<h1>{r.choice(AR_BRANDS)} — تداول بالذكاء الاصطناعي بأرباح مضمونة</h1>",
                        p(f"اربح {maybe_ar_digits(r, d)}% أرباح يومية على إيداعك. أرباح مضمونة وبدون مخاطرة."),
                        p("ضاعف أموالك خلال ٣٠ يومًا."), tg(r)])
        title = "استثمار مضمون"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["investment_promise"]


def fake_shop(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r)
    off = r.choice([70, 75, 80, 85, 90])
    items = r.sample(["smartphone", "sneakers", "perfume", "handbag", "headphones", "smartwatch", "air fryer"], 3)
    if lang == "en":
        body = "".join([f'<div class="{css}-nav">{b} Outlet</div>', f"<h1>Closing down sale — up to {off}% off</h1>",
                        "".join(f'<div class="{css}-card">{html.escape(it.title())} — AED {r.randint(29, 99)} '
                                f'<s>AED {r.randint(400, 1200)}</s> {off}% off</div>' for it in items),
                        p("Only 3 left! Payment by bank transfer only. No returns."), wa(r)])
        title = f"{b} Outlet | {off}% off"
    else:
        body = "".join([f'<div class="{css}-nav">{r.choice(AR_BRANDS)} أوتلت</div>', f"<h1>تخفيضات تصل الى {maybe_ar_digits(r, off)}% لفترة محدودة</h1>",
                        p(f"خصم {off}% على العطور والهواتف. الدفع بالتحويل البنكي فقط."), wa(r)])
        title = "تخفيضات"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["fake_shop"]


def phishing(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r) + " Bank"
    if lang == "en":
        body = "".join([f'<div class="{css}-brand">{b}</div>', "<h1>Your account has been suspended</h1>",
                        p("Verify your card to receive your refund of AED " + str(r.randint(200, 2500)) + " within 24 hours."),
                        form([("cardnumber", "text", "Card number"), ("exp", "text", "Expiry MM/YY"), ("cvv", "password", "CVV"),
                              ("otp", "text", "One-time password (OTP)")], f"{css}-verify", "Verify")])
        title = f"{b} | Verification"
    else:
        body = "".join([f'<div class="{css}-brand">{r.choice(AR_BRANDS)} بنك</div>', "<h1>تم تعليق حسابك</h1>",
                        p("قم بتأكيد بطاقتك لاستلام المبلغ المسترد خلال ٢٤ ساعة."),
                        form([("cardnumber", "text", "رقم البطاقة"), ("cvv", "password", "CVV"), ("otp", "text", "رمز التحقق")],
                             f"{css}-verify", "تأكيد")])
        title = "تأكيد الحساب"
    return page(title, body, "ar" if lang != "en" else "en", css, r), ["credential_request", "brand_misuse"]


# ------------------------------------------------------------------------------------------------
# Legitimate look-alikes
# ------------------------------------------------------------------------------------------------
def company_footer(r: random.Random, name: str, lang: str) -> str:
    if lang == "en":
        return (f"<footer>{html.escape(name)} LLC · Trade licence {r.randint(100000, 999999)} · "
                f"Head office {r.choice(CITIES_EN)} · <a href='/privacy'>Privacy policy</a> · "
                f"<a href='/terms'>Terms and conditions</a> · © 2026 {html.escape(name)}. All rights reserved.</footer>")
    return (f"<footer>{html.escape(name)} ذ.م.م · رخصة تجارية {ar_digits(r.randint(100000, 999999))} · المقر الرئيسي "
            f"{r.choice(CITIES_AR)} · سياسة الخصوصية · الشروط والأحكام · © ٢٠٢٦ جميع الحقوق محفوظة.</footer>")


def nav(css: str, items: list[str]) -> str:
    return f'<nav class="{css}-nav">' + "".join(f'<a href="/{i.lower().replace(" ", "-")}">{html.escape(i)}</a>' for i in items) + "</nav>"


def legit_recruitment(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r) + " Manpower"
    if lang == "en":
        jobs = r.sample(["Part-time sales associate", "Warehouse supervisor", "Accountant", "Delivery rider",
                         "Customer service agent (part-time)", "Nurse", "Barista", "Data entry clerk"], 4)
        body = "".join([nav(css, ["Home", "Jobs", "About us", "Contact"]), f"<h1>{name}: licensed recruitment in the UAE</h1>",
                        p("We connect candidates with verified employers. We never charge candidates any fees. "
                          "Report anyone asking for payment in our name."),
                        "".join(f'<div class="{css}-job"><h3>{html.escape(j)}</h3>{p("Salary AED " + str(r.randint(3, 15)) + ",000 per month. " + r.choice(CITIES_EN) + ".")}</div>' for j in jobs),
                        p("Part-time and full-time roles. Commission-based sales roles include a fixed basic salary."),
                        p("Licensed by the Ministry of Human Resources and Emiratisation."), company_footer(r, name, "en")])
        title = f"{name} | Jobs in the UAE"
    else:
        body = "".join([nav(css, ["الرئيسية", "الوظائف", "من نحن", "اتصل بنا"]), f"<h1>{r.choice(AR_BRANDS)} لخدمات التوظيف المرخصة</h1>",
                        p("نربط الباحثين عن عمل بأصحاب عمل موثوقين. لا نطلب أي رسوم من المرشحين أبدًا."),
                        p("وظائف بدوام جزئي وكامل في المبيعات وخدمة العملاء والمحاسبة."),
                        p("مرخصة من وزارة الموارد البشرية والتوطين."), company_footer(r, name, "ar")])
        title = "خدمات التوظيف | وظائف في الإمارات"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_gig(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r)
    if lang == "en":
        body = "".join([nav(css, ["How it works", "Pricing", "Help", "Careers"]), f"<h1>{name} — freelance marketplace</h1>",
                        p("Find freelance projects in design, writing and data labelling. Get paid per task by verified clients."),
                        p("Invite friends with your referral code and both receive AED 20 credit after their first completed project."),
                        p("Withdraw your earnings to your UAE bank account. Payouts take 3-5 business days. "
                          "We never ask you to pay to receive tasks."),
                        p("Joining is free."), company_footer(r, name, "en")])
        title = f"{name} | Freelance work"
    else:
        body = "".join([nav(css, ["كيف يعمل", "الأسعار", "المساعدة"]), f"<h1>{r.choice(AR_BRANDS)} — منصة العمل الحر</h1>",
                        p("ابحث عن مشاريع حرة في التصميم والكتابة. احصل على أجرك لكل مهمة من عملاء موثقين."),
                        p("ادع أصدقاءك برمز الإحالة واحصل على رصيد ٢٠ درهم بعد أول مشروع مكتمل."),
                        p("اسحب أرباحك إلى حسابك البنكي. التسجيل مجاني ولا نطلب أي دفع للحصول على المهام."),
                        company_footer(r, name, "ar")])
        title = "منصة العمل الحر"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_delivery(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r) + " Delivery"
    if lang == "en":
        body = "".join([nav(css, ["Order", "Ride with us", "Restaurants", "About us"]), f"<h1>Become a {name} rider</h1>",
                        p(f"Earn per order plus tips. Flexible part-time hours in {r.choice(CITIES_EN)}."),
                        p("You need a valid UAE driving licence and a residence visa. We provide insurance and training free of charge."),
                        p("Weekly payouts to your bank account."), company_footer(r, name, "en")])
        title = f"{name} | Ride with us"
    else:
        body = "".join([nav(css, ["اطلب", "انضم كسائق", "المطاعم"]), f"<h1>انضم كسائق توصيل لدى {r.choice(AR_BRANDS)}</h1>",
                        p("اربح لكل طلب مع الإكراميات. ساعات عمل مرنة بدوام جزئي."),
                        p("نوفر التأمين والتدريب مجانًا. الدفع أسبوعيًا إلى حسابك البنكي."), company_footer(r, name, "ar")])
        title = "انضم كسائق"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_shop(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r)
    off = r.choice([10, 15, 20, 30, 40, 50])
    if lang == "en":
        items = r.sample(["Laptop", "Running shoes", "Coffee machine", "Abaya", "Smartphone case", "Desk lamp"], 3)
        body = "".join([nav(css, ["Electronics", "Fashion", "Home", "Deals", "Track order"]),
                        f"<h1>{name} — online shopping in the UAE</h1>", p(f"Weekend deals: up to {off}% off selected items."),
                        "".join(f'<div class="{css}-card">{html.escape(i)} AED {r.randint(49, 3999)}</div>' for i in items),
                        p("Pay by card, Apple Pay or cash on delivery. Free returns within 15 days."), company_footer(r, name, "en")])
        title = f"{name} | Shop online"
    else:
        body = "".join([nav(css, ["الإلكترونيات", "الأزياء", "المنزل", "العروض"]), f"<h1>{r.choice(AR_BRANDS)} — تسوق أونلاين في الإمارات</h1>",
                        p(f"عروض نهاية الأسبوع: خصم حتى {maybe_ar_digits(r, off)}% على منتجات مختارة."),
                        p("ادفع بالبطاقة أو نقدًا عند الاستلام. إرجاع مجاني خلال ١٥ يومًا."), company_footer(r, name, "ar")])
        title = "تسوق أونلاين"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_bank(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r) + " Bank"
    rate = r.choice(["3.25", "3.75", "4.10", "4.50"])
    if lang == "en":
        body = "".join([nav(css, ["Accounts", "Cards", "Loans", "Fixed deposits", "Contact"]), f"<h1>{name}</h1>",
                        p(f"Open a fixed deposit with rates up to {rate}% per annum. Terms and conditions apply."),
                        p("We will never ask for your OTP, PIN or password by phone, SMS or email."),
                        form([("username", "text", "Username"), ("password", "password", "Password")], f"{css}-login", "Log in"),
                        p("Regulated by the Central Bank of the UAE."), company_footer(r, name, "en")])
        title = f"{name} | Personal banking"
    else:
        body = "".join([nav(css, ["الحسابات", "البطاقات", "القروض", "الودائع"]), f"<h1>بنك {r.choice(AR_BRANDS)}</h1>",
                        p(f"افتح وديعة ثابتة بعائد يصل إلى {rate}% سنويًا. تطبق الشروط والأحكام."),
                        p("لن نطلب منك أبدًا رمز التحقق أو الرقم السري عبر الهاتف أو الرسائل."),
                        p("خاضع لرقابة مصرف الإمارات العربية المتحدة المركزي."), company_footer(r, name, "ar")])
        title = "الخدمات المصرفية"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_broker(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r) + " Invest"
    if lang == "en":
        body = "".join([nav(css, ["Markets", "Education", "Pricing", "About us"]), f"<h1>{name} — regulated investing app</h1>",
                        p("Invest in global stocks and ETFs from AED 100. Capital at risk: returns are not guaranteed "
                          "and past performance does not predict future results."),
                        p("Licensed by the financial services regulator."), company_footer(r, name, "en")])
        title = f"{name} | Invest"
    else:
        body = "".join([nav(css, ["الأسواق", "التعليم", "من نحن"]), f"<h1>{r.choice(AR_BRANDS)} للاستثمار المرخص</h1>",
                        p("استثمر في الأسهم العالمية. رأس المال معرض للخطر والعوائد غير مضمونة."), company_footer(r, name, "ar")])
        title = "استثمار مرخص"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def legit_loyalty(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    name = brand(r) + " Rewards"
    if lang == "en":
        body = "".join([nav(css, ["Earn", "Spend", "Tiers", "Help"]), f"<h1>{name} loyalty programme</h1>",
                        table([["Tier", "Points needed", "Benefits"], ["Level 1 Silver", "0", "Member prices"],
                               ["Level 2 Gold", "5,000", "Free delivery"], ["Level 3 VIP", "20,000", "Lounge access"]], f"{css}-tiers"),
                        p("Membership is free. Earn points on every purchase; no deposit is ever required."),
                        company_footer(r, name, "en")])
        title = f"{name} | Loyalty"
    else:
        body = "".join([nav(css, ["اكسب", "استبدل", "المستويات"]), f"<h1>برنامج ولاء {r.choice(AR_BRANDS)}</h1>",
                        table([["المستوى", "النقاط"], ["المستوى 1 فضي", "0"], ["المستوى 2 ذهبي", "5000"]], f"{css}-tiers"),
                        p("العضوية مجانية ولا يلزم أي إيداع."), company_footer(r, name, "ar")])
        title = "برنامج الولاء"
    return page(title, body, "ar" if lang != "en" else "en", css, r), []


def inconclusive(r: random.Random, lang: str, variant: int, css: str) -> tuple[str, list[str]]:
    b = brand(r)
    kind = variant % 4
    if kind == 0:
        body = f"<h1>{b}</h1>" + p("Coming soon.")
    elif kind == 1:
        body = f"<h1>{b}</h1>" + form([("u", "text", "Username"), ("p", "password", "Password")], f"{css}-l", "Login")
    elif kind == 2:
        body = f"<h1>{b} jobs</h1>" + p("Part-time work available. Contact us for details.") + wa(r)
    else:
        body = f"<h1>{r.choice(AR_BRANDS)}</h1>" + p("الموقع قيد الصيانة.")
    return page(b, body, "ar" if kind == 3 else "en", css, r), []


KITS = [
    # (kit_id, label, scam_type, fn, languages, n)
    ("syn_task01", "fraudulent", "task_scam", task_scam, ["en", "ar", "mixed"], 14),
    ("syn_task02", "fraudulent", "task_scam", task_scam, ["ar", "mixed"], 12),
    ("syn_task03", "fraudulent", "task_scam", task_scam, ["en"], 12),
    ("syn_task04", "fraudulent", "task_scam", task_scam, ["ar", "en"], 12),
    ("syn_task05", "fraudulent", "task_scam", task_scam, ["mixed", "en"], 10),
    ("syn_fee01", "fraudulent", "other", advance_fee, ["en", "ar"], 12),
    ("syn_fee02", "fraudulent", "other", advance_fee, ["ar"], 8),
    ("syn_mule01", "fraudulent", "other", money_mule, ["en", "ar"], 10),
    ("syn_gamb01", "fraudulent", "gambling_deposit", gambling, ["en", "ar"], 12),
    ("syn_inv01", "fraudulent", "investment", investment, ["en", "ar"], 12),
    ("syn_shop01", "fraudulent", "fake_shop", fake_shop, ["en", "ar"], 12),
    ("syn_phish01", "fraudulent", "phishing", phishing, ["en", "ar"], 12),
    ("syn_legit_recruit01", "legitimate", "", legit_recruitment, ["en", "ar"], 14),
    ("syn_legit_recruit02", "legitimate", "", legit_recruitment, ["en"], 10),
    ("syn_legit_gig01", "legitimate", "", legit_gig, ["en", "ar"], 12),
    ("syn_legit_gig02", "legitimate", "", legit_gig, ["en"], 8),
    ("syn_legit_delivery01", "legitimate", "", legit_delivery, ["en", "ar"], 12),
    ("syn_legit_shop01", "legitimate", "", legit_shop, ["en", "ar"], 14),
    ("syn_legit_shop02", "legitimate", "", legit_shop, ["ar", "en"], 10),
    ("syn_legit_bank01", "legitimate", "", legit_bank, ["en", "ar"], 12),
    ("syn_legit_broker01", "legitimate", "", legit_broker, ["en", "ar"], 10),
    ("syn_legit_loyalty01", "legitimate", "", legit_loyalty, ["en", "ar"], 10),
    ("syn_ambig01", "inconclusive", "", inconclusive, ["en"], 12),
]


def main() -> None:
    if OUT.exists():
        for child in OUT.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != ".gitkeep":
                child.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kit_id, label, scam_type, fn, langs, n in KITS:
        r = random.Random(f"{SEED}:{kit_id}")
        css = kit_id.replace("_", "")[:10] + str(r.randint(10, 99))
        (OUT / kit_id).mkdir(exist_ok=True)
        for i in range(n):
            lang = langs[i % len(langs)]
            html_text, tags = fn(r, lang, i, css)
            rel = f"{kit_id}/{i + 1:02d}.html"
            (OUT / rel).write_text(html_text, encoding="utf-8")
            page_lang = "ar" if lang == "ar" else ("mixed" if lang == "mixed" else "en")
            rows.append({"file": rel, "label": label, "scam_type": scam_type, "kit_id": kit_id, "lang": page_lang,
                         "behavior_tags": ";".join(dict.fromkeys(tags))})
    with (OUT / "labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "label", "scam_type", "kit_id", "lang", "behavior_tags"])
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    print(f"synthetic corpus: {len(rows)} pages in {len(KITS)} kits -> {OUT}  {counts}")


if __name__ == "__main__":
    main()
