"""Registration / login walls, referenced routes, brand-bait assets and domain shape.

Evidence that is visible WITHOUT signing in, read from what the site already delivered (rendered HTML, its own
HTML/JS/JSON bodies, the files it loaded) or, when the server's capture was blocked, from the page as rendered in
the user's own browser (sent by the extension as structure only: paths without queries, field descriptors without
values, image file names). Nothing here navigates, calls an API or submits anything.

Scam-type agnostic: route vocabulary, invite-gated registration, a second "security/fund" password, phone-only
sign-up, missing company identity, brand-bait logos and throw-away domains are shared by task, deposit, gambling and
investment kits. No domain, kit or invite code is hardcoded.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from app.urls import hostname, registrable_domain
from ml.arabic import normalize_arabic

MAX_PATHS, MAX_IMAGES, MAX_FIELDS = 600, 200, 60

# ---- routes ---------------------------------------------------------------------------------------------------
# Paths referenced in delivered HTML/JS: "/index/ctrl/recharge", absolute same-site URLs, uni-app "pages/..." routes.
PATH_RE = re.compile(r"""(?:(?<=["'`(=,\s])|^)(/[A-Za-z][A-Za-z0-9_\-]*(?:/[A-Za-z0-9_\-.%]+){1,8})""")
PAGES_RE = re.compile(r"""["'`]/?((?:pages|views)/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+){0,4})["'`]""")
ABS_RE = re.compile(r"""https?://([A-Za-z0-9.\-]+)(/[A-Za-z0-9_\-./%]{2,200})""")
HASH_ROUTE_RE = re.compile(r"""#/((?:[A-Za-z0-9_\-]+/){0,5}[A-Za-z0-9_\-]+)""")
SKIP_PATH = re.compile(r"^/(cdn-cgi|node_modules|wp-includes|wp-json|_next/static/chunks/webpack)\b|\.(css|map|woff2?|ttf|eot)$", re.I)

ROUTE_GROUPS: dict[str, re.Pattern] = {
    "recharge": re.compile(r"^(recharge\w*|deposit\w*|topup|top_up|chongzhi|chong_zhi|addfunds?|add_funds?)$"),
    "withdraw": re.compile(r"^(withdraw\w*|tixian|ti_xian|cashout|cash_out)$"),
    "task_orders": re.compile(r"^(rot_order|rotorder|grab\w*|qiangdan|qiang_dan|do_order|submit_order|order_task|"
                              r"task|tasks|mission|missions|rob_order|match_order|auto_order|taskhall|task_hall)$"),
    "bind_bank": re.compile(r"^(bind_bank|bindbank|bind_card|bindcard|bank_card|bankcard|add_bank|addbank|"
                            r"bind_wallet|bind_usdt|bind_address|wallet_address)$"),
    "invite": re.compile(r"^(invite\w*|invitation|referral|tuiguang|spread|my_team|myteam)$"),
    "vip": re.compile(r"^(vip\d*|svip\d*|vip_level|viplevel|upgrade_vip|vipupgrade)$"),
    "crypto": re.compile(r"^(usdt|trc20|erc20|trx|btc|crypto|bit)$"),
    "security_password": re.compile(r"^(pwd2|set_pwd2|edit_pwd2|paypwd|pay_pwd|safe_pwd|safepwd|fund_pwd|trade_pwd|"
                                    r"tradepwd|password2|pay_password|paypassword|fund_password|trade_password)(\.html)?$"),
    "finance": re.compile(r"^(caiwu|yuebao|lixibao|licai|yeb)$"),
}
ROUTE_LABEL = {
    "recharge": ("recharge", "الشحن"), "withdraw": ("withdrawal", "السحب"), "task_orders": ("rotation-order", "طلبات المهام"),
    "bind_bank": ("bind-bank", "ربط الحساب البنكي"), "invite": ("invite", "الدعوة"), "vip": ("VIP-level", "مستويات VIP"),
    "crypto": ("crypto-deposit", "الإيداع بالعملات المشفرة"), "security_password": ("security-password", "كلمة مرور الأمان"),
    "finance": ("wealth-product", "منتجات الأرباح"),
}

# ---- registration wall ----------------------------------------------------------------------------------------
INVITE_PATH_RE = re.compile(r"/(invite_?code|invitecode|invitation_?code|invite|inv_?code|recommend_?code|share_?code|"
                            r"reg_?code)/[A-Za-z0-9]{4,16}(\.html?)?(/|$)", re.I)
INVITE_QUERY_RE = re.compile(r"[?&#](invite_?code|invitecode|invitation_?code|invite|inv_?code|reg_?code)=[A-Za-z0-9]{4,16}", re.I)
INVITE_FIELD_RE = re.compile(r"invite|invitation|referr|recommend|promo(tion)? ?code|邀请|推荐|رمز الدعوه|كود الدعوه|رمز الاحاله|"
                             r"كود الاحاله|رمز التوصيه", re.I)
SECPW_RE = re.compile(r"(security|fund|funds|withdraw(al)?|transaction|trade|trading|payment|pay|safe|capital|money|"
                      r"second(ary)?) ?(password|pwd|pass ?word|pin|passcode)\b|\b(pwd2|password2|paypwd|paypass|tradepwd|"
                      r"safepwd|fundpwd)\b|资金密码|交易密码|支付密码|提现密码|安全密码|"
                      r"كلمه (المرور|السر) (الماليه|للسحب|السحب|للمعاملات|المعاملات|الامان|للامان|الدفع|للدفع)|"
                      r"رمز (السحب|المعاملات|الامان)", re.I)
CONFIRM_RE = re.compile(r"confirm|repeat|again|re-?enter|retype|verify|تاكيد|اعد|اعاده", re.I)
REGISTER_HINT_RE = re.compile(r"\b(register|registration|sign ?up|signup|create (an )?account|join now|open (an )?account|"
                              r"log ?in|login|sign ?in|signin)\b|تسجيل|انشاء حساب|سجل الان|دخول", re.I)
SCAM_REGISTER_ROUTE_RE = re.compile(r"/index/user/(register|reg|do_register|login|do_login)\b|/register/invite_?code/|"
                                    r"(^|/)(h5|wap|m)/#?/?pages/(register|login|reg)\b|#/pages/(register|login|reg)\b|"
                                    r"/index/login/(register|reg)\b", re.I)
H5_SHELL_RE = re.compile(r"<uni-app\b|\buni-app\b|__uniConfig|uni\.webview|/h5/static/js/(index|chunk-vendors)|"
                         r"\bdcloud\b", re.I)
IDENTITY_LINK_RE = re.compile(r"terms|privacy|about|contact|legal|imprint|company|careers|الشروط|الخصوصيه|من نحن|اتصل",
                              re.I)
COUNTRY_CODE_RE = re.compile(r"(?<!\d)\+\s?(971|966|974|965|973|968|20|91|92|62|63|60|84|86|880|234|1|44)(?!\d)")

# ---- brand bait -----------------------------------------------------------------------------------------------
# Marketplaces and household brands whose logos task-scam kits show to look like an "official partner".
BAIT_BRANDS = {
    "alibaba", "aliexpress", "amazon", "shein", "noon", "walmart", "lazada", "shopify", "bukalapak", "tokopedia",
    "shopee", "ebay", "temu", "taobao", "tmall", "flipkart", "zalando", "ikea", "carrefour", "lulu", "namshi",
    "talabat", "careem", "jumia", "rakuten", "costco", "target", "bestbuy", "etsy", "wayfair", "sephora", "nike",
    "adidas", "booking", "agoda", "airbnb", "expedia", "tripadvisor", "netflix", "tiktok", "tiktokshop", "jd",
    "emirates", "etihad", "adnoc", "dubizzle",
}

# ---- domain shape ---------------------------------------------------------------------------------------------
ABUSED_TLDS = {"xyz", "top", "shop", "vip", "cc", "icu", "buzz", "cyou", "sbs", "cfd", "bond", "click", "lol", "monster",
               "rest", "quest", "mom", "life", "work", "fun", "win", "bet", "xin", "tk", "ml", "ga", "cf", "gq"}
VOWELS = set("aeiou")


@dataclass
class WallSignals:
    paths: list[str] = field(default_factory=list)          # same-site paths referenced or loaded (no queries)
    path_sources: dict[str, int] = field(default_factory=dict)
    route_groups: dict[str, str] = field(default_factory=dict)   # group -> example path
    route_strength: str | None = None                       # task | money | None
    images: list[str] = field(default_factory=list)
    brand_bait: list[str] = field(default_factory=list)
    registration_wall: bool = False
    invite_gated: str | None = None                         # url | field | None
    security_password: str | None = None                    # field | text | route | None
    phone_only: bool = False
    country_code: str | None = None
    company_identity: bool = True
    scam_register_route: bool = False
    h5_shell: bool = False
    random_label: bool = False
    abused_tld: str | None = None
    bot_challenge: bool = False
    from_user_browser: bool = False
    cert_age_days: int | None = None                        # set by the pipeline (certificate transparency)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["paths"] = self.paths[:80]
        d["images"] = self.images[:40]
        return d


def _tokens(path: str) -> list[str]:
    out = []
    for seg in re.split(r"[/.?#]+", path.lower()):
        if not seg:
            continue
        out.append(seg)
        out.extend(t for t in re.split(r"[-]+", seg) if t and t != seg)
    return out


def _norm_path(p: str) -> str | None:
    p = unquote(p.split("?")[0].split("#")[0]).strip()
    if not p.startswith("/") or len(p) > 200 or p.startswith("//") or SKIP_PATH.search(p):
        return None
    return re.sub(r"/{2,}", "/", p)


def paths_from_text(text: str, site: str) -> set[str]:
    out: set[str] = set()
    for m in PATH_RE.findall(text):
        n = _norm_path(m)
        if n:
            out.add(n)
    for m in PAGES_RE.findall(text):
        out.add("/" + m)
    for m in HASH_ROUTE_RE.findall(text):
        out.add("/#/" + m)
    for h, p in ABS_RE.findall(text):
        if registrable_domain(h.lower()) == site:
            n = _norm_path(p)
            if n:
                out.add(n)
    return out


def classify_routes(paths: list[str]) -> tuple[dict[str, str], str | None]:
    groups: dict[str, str] = {}
    for p in paths:
        toks = _tokens(p)
        for g, rx in ROUTE_GROUPS.items():
            if g in groups:
                continue
            if g == "crypto" and "bit" in toks and "pay" not in toks:
                if not any(rx.match(t) for t in toks if t != "bit"):
                    continue
            if any(rx.match(t) for t in toks):
                groups[g] = p
    strength = None
    if "recharge" in groups and len(groups) >= 3:
        strength = "task" if "task_orders" in groups else "money"
    return groups, strength


def brand_bait(images: list[str], page_site: str) -> list[str]:
    own = set(re.split(r"[^a-z0-9]+", page_site.lower()))
    found: list[str] = []
    for name in images:
        base = re.sub(r"\.(png|jpe?g|gif|webp|svg|avif)$", "", name.rsplit("/", 1)[-1], flags=re.I)
        toks = set(re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", base).lower()))
        for b in BAIT_BRANDS & toks:
            if b not in own and b not in found:
                found.append(b)
    return found


def domain_shape(host: str) -> tuple[bool, str | None]:
    """(random-looking registrable label, abused TLD or None)."""
    site = registrable_domain(host)
    if not site or "." not in site:
        return False, None
    label, tld = site.split(".", 1)[0], site.rsplit(".", 1)[-1]
    letters = [c for c in label if c.isalpha()]
    digits = sum(c.isdigit() for c in label)
    random_label = False
    if len(label) >= 6 and letters:
        mixed = digits >= 2 and len(letters) >= 3 and re.search(r"[a-z]\d|\d[a-z]", label)
        vowel_ratio = sum(c in VOWELS for c in letters) / len(letters)
        cons_run = max((len(m) for m in re.findall(r"[bcdfghjklmnpqrstvwxz]+", label)), default=0)
        counts = {c: label.count(c) for c in set(label)}
        entropy = -sum(n / len(label) * math.log2(n / len(label)) for n in counts.values())
        random_label = bool(mixed) or (len(letters) >= 7 and vowel_ratio < 0.2) or (cons_run >= 5 and entropy > 2.8)
    return random_label, (tld if tld in ABUSED_TLDS else None)


@dataclass
class FieldDesc:
    type: str = ""
    hint: str = ""             # name/id/placeholder/label, normalized
    required: bool = False
    readonly: bool = False
    has_value: bool = False


def fields_from_soup(soup: Any) -> list[FieldDesc]:
    labels = {lab.get("for"): lab.get_text(" ", strip=True) for lab in soup.find_all("label") if lab.get("for")}
    out = []
    for el in soup.find_all(["input", "select", "textarea"]):
        t = (el.get("type") or el.name or "text").lower()
        if t in ("submit", "button", "image", "reset", "file"):
            continue
        hint = " ".join(filter(None, [el.get("name"), el.get("id"), el.get("placeholder"), el.get("aria-label"),
                                      el.get("title"), labels.get(el.get("id"))]))
        out.append(FieldDesc(type=t, hint=normalize_arabic(hint)[:120], required=el.has_attr("required"),
                             readonly=el.has_attr("readonly") or el.has_attr("disabled"),
                             has_value=bool((el.get("value") or "").strip()) and t not in ("checkbox", "radio")))
    return out[:MAX_FIELDS]


def fields_from_client(items: list[dict[str, Any]]) -> list[FieldDesc]:
    out = []
    for f in items[:MAX_FIELDS]:
        hint = " ".join(str(f.get(k) or "")[:80] for k in ("name", "placeholder", "label", "autocomplete"))
        out.append(FieldDesc(type=str(f.get("type") or "text")[:20].lower(), hint=normalize_arabic(hint)[:160],
                             required=bool(f.get("required")), readonly=bool(f.get("readonly")),
                             has_value=bool(f.get("has_value"))))
    return out


def analyze_wall(page_url: str, soups: list[Any], htmls: list[str], har: dict | None, lines: list[str],
                 company_details: bool, client: dict[str, Any] | None, bot_challenge: bool) -> WallSignals:
    host = hostname(page_url)
    site = registrable_domain(host)
    w = WallSignals(bot_challenge=bot_challenge)
    paths: dict[str, None] = {}
    sources = {"capture": 0, "user_browser": 0}

    def add(p: str, src: str) -> None:
        if p not in paths and len(paths) < MAX_PATHS:
            paths[p] = None
            sources[src] += 1

    # 1. the scanned URL itself (registration routes and invite codes live in the path)
    u = urlsplit(page_url)
    own = _norm_path(u.path)
    if own:
        add(own, "capture")
    # 2. rendered HTML of every capture step + same-site bodies the browser received (HTML, JS, JSON)
    for html in htmls:
        for p in paths_from_text(html, site):
            add(p, "capture")
    images: list[str] = []
    for e in (har or {}).get("log", {}).get("entries", []) or []:
        url = e.get("request", {}).get("url", "")
        eh = hostname(url)
        if registrable_domain(eh) != site:
            continue
        up = urlsplit(url)
        if "/cdn-cgi/" in up.path:
            continue
        n = _norm_path(up.path)
        c = e.get("response", {}).get("content", {}) or {}
        mime = c.get("mimeType", "") or ""
        if n and e.get("request", {}).get("method", "GET") == "GET":
            add(n, "capture")
        if "image" in mime or re.search(r"\.(png|jpe?g|gif|webp|svg|avif)$", up.path, re.I):
            images.append(up.path.rsplit("/", 1)[-1])
        t = c.get("text")
        if isinstance(t, str) and (any(x in mime for x in ("html", "javascript", "json", "ecmascript"))
                                   or up.path.endswith((".js", ".mjs", ".json", ".html", ".htm"))):
            for p in paths_from_text(t[:2_000_000], site):
                add(p, "capture")
    for soup in soups:
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or "").split("?")[0]
            if src and not src.startswith("data:"):
                images.append(src.rsplit("/", 1)[-1])
    # 3. the page as rendered in the user's browser (extension; structure only)
    fields: list[FieldDesc] = []
    for soup in soups[:1]:
        fields.extend(fields_from_soup(soup))
    client_identity = False
    if client:
        w.from_user_browser = True
        for p in client.get("paths", [])[:MAX_PATHS]:
            n = _norm_path(str(p)) if str(p).startswith("/") else None
            if n:
                add(n, "user_browser")
        images.extend(str(i).rsplit("/", 1)[-1][:120] for i in client.get("images", [])[:MAX_IMAGES])
        fields.extend(fields_from_client(client.get("fields", [])))
        client_identity = bool(client.get("identity_links"))
        if client.get("h5_shell"):
            w.h5_shell = True
    w.paths = list(paths)
    w.path_sources = {k: v for k, v in sources.items() if v}
    w.route_groups, w.route_strength = classify_routes(w.paths)
    w.images = list(dict.fromkeys(i for i in images if i))[:MAX_IMAGES]
    w.brand_bait = brand_bait(w.images, site)

    # Registration / login wall
    text = "\n".join(lines)
    norm_text = normalize_arabic(text)
    title = ""
    if soups and soups[0].title and soups[0].title.string:
        title = soups[0].title.string
    if client and client.get("title"):
        title = f"{title} {client.get('title')}"
    pw_fields = [f for f in fields if f.type == "password"]
    words = len(re.findall(r"\w+", text))
    # A wall is a page that is mostly a sign-up / login form (a login box on a content-rich homepage is not).
    w.registration_wall = words < 300 and (bool(pw_fields) or bool(REGISTER_HINT_RE.search(f"{u.path} {title}")) or bool(
        SCAM_REGISTER_ROUTE_RE.search(u.path + ("#" + u.fragment if u.fragment else ""))))

    if INVITE_PATH_RE.search(u.path) or INVITE_QUERY_RE.search(page_url):
        w.invite_gated = "url"
    elif any(INVITE_FIELD_RE.search(f.hint) and (f.required or f.readonly or f.has_value) for f in fields):
        w.invite_gated = "field"

    if any(SECPW_RE.search(f.hint) and not CONFIRM_RE.search(f.hint) for f in fields):
        w.security_password = "field"
    elif len(pw_fields) >= 2 and sum(1 for f in pw_fields if not CONFIRM_RE.search(f.hint)) >= 2:
        w.security_password = "field"
    elif SECPW_RE.search(norm_text):
        w.security_password = "text"
    elif "security_password" in w.route_groups:
        w.security_password = "route"

    has_phone = any(f.type == "tel" or re.search(r"phone|mobile|tel\b|هاتف|جوال|موبايل|手机", f.hint) for f in fields)
    has_email = any(f.type == "email" or re.search(r"e-?mail|بريد|邮箱", f.hint) for f in fields)
    cc = COUNTRY_CODE_RE.search(text) or COUNTRY_CODE_RE.search(" ".join(f.hint for f in fields))
    w.country_code = ("+" + cc.group(1)) if cc else None
    w.phone_only = has_phone and not has_email and w.registration_wall

    html_identity = any(IDENTITY_LINK_RE.search((a.get("href") or "") + " " + a.get_text(" ", strip=True))
                        for soup in soups for a in soup.find_all("a"))
    # A bot-challenge page's own footer links (e.g. the challenge provider's privacy link) say nothing about the site.
    server_identity = (company_details or html_identity) and not bot_challenge
    w.company_identity = bool(server_identity or client_identity)

    w.scam_register_route = bool(SCAM_REGISTER_ROUTE_RE.search(u.path + ("#" + u.fragment if u.fragment else "")))
    w.h5_shell = w.h5_shell or any(H5_SHELL_RE.search(h[:400_000]) for h in htmls)
    w.random_label, w.abused_tld = domain_shape(host)
    return w


def wall_counts(w: dict[str, Any]) -> dict[str, Any]:
    """Which registration / route / domain signals are present (used by the tier rules and the clues)."""
    age = w.get("cert_age_days")
    no_identity = w.get("registration_wall") and not w.get("company_identity")
    sig = {
        "invite_gated": bool(w.get("invite_gated")),
        "security_password": bool(w.get("security_password")),
        "scam_register_route": bool(w.get("scam_register_route")),
        "no_company_identity": bool(no_identity),
        "phone_only": bool(w.get("phone_only") and no_identity),
        "h5_shell": bool(w.get("h5_shell") and (w.get("invite_gated") or w.get("security_password"))),
        "route_vocab": w.get("route_strength") in ("task", "money"),
        "brand_bait": len(w.get("brand_bait") or []) >= 2 or (len(w.get("brand_bait") or []) == 1 and w.get("registration_wall")),
        "young_domain": age is not None and age < 90,
        "domain_shape": bool(w.get("random_label") or w.get("abused_tld")),
    }
    return sig
