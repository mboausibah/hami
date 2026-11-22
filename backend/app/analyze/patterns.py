"""Behavior patterns, matched on *normalized* text (see ml/arabic.py: lowercased, alef/yaa/taa
marbuta unified, diacritics stripped, Western digits). Arabic patterns are therefore written in
normalized spelling (e.g. ايداع, عموله)."""
from __future__ import annotations

import re

from ml.arabic import LETTER_TABLE


def R(p: str) -> re.Pattern:
    """Compile a pattern after applying the same Arabic letter normalization as the text."""
    return re.compile(p.translate(LETTER_TABLE), re.I)


# --- money movement ---------------------------------------------------------------------------
DEPOSIT = R(
    r"\b(recharge|re-charge|top[\s-]?up|deposit|add funds|fund your account)\b"
    # Arabic "اشحن" alone also means "ship" (postal pages): only balance/account top-ups count.
    r"|اشحن (رصيد|حساب|محفظ)|ايداع|اودع|تعبئه الرصيد|اعاده الشحن|اضافه رصيد|شحن الرصيد|شحن الحساب"
)
UNLOCK = R(
    r"\b(unlock|to activate|activate (your )?(account|tasks|level)|upgrade (your )?(level|vip|account)|"
    r"higher (level|tasks|commission)|next level|vip ?\d|level \d|lv\.? ?\d|more tasks|bigger tasks|"
    r"premium tasks|to withdraw|before (you can )?withdraw)\b"
    r"|لفتح|فتح المهام|فتح المستوى|ترقيه|تفعيل الحساب|تفعيل المهام|المستوى \d|مستوى اعلى|مهام اكثر|قبل السحب|لتتمكن من السحب"
)
DEPOSIT_TO_UNLOCK = R(
    r"(recharge|deposit|top[\s-]?up|pay)\b.{0,60}\b(in order )?to (unlock|activate|upgrade|withdraw)\b"
    r"|(unlock|activate|upgrade)\b.{0,40}\b(by|after) (recharg|deposit|pay)"
    r"|(اشحن|ايداع|اودع|ادفع|شحن الرصيد).{0,40}(لفتح|لتفعيل|للترقيه|لتتمكن من السحب|للسحب)"
    r"|(لفتح|لتفعيل|للترقيه).{0,40}(اشحن|ايداع|اودع|ادفع|شحن الرصيد)"
)
ADVANCE_FEE = R(
    r"\b(registration|activation|processing|joining|onboarding|training|interview|guarantee|job|work permit)"
    r" (fee|deposit|charge)s?\b"
    r"|\bpay\b.{0,40}\b(before|to) (start|begin|get|receive|secure)\b.{0,30}\b(job|work|tasks|position|offer|salary)"
    r"|\bfee\b.{0,30}\b(to|before) (start|get|secure) (the |your )?(job|work|position)"
    r"|رسوم (التسجيل|تسجيل|التفعيل|تفعيل|المعالجه|الانضمام|التدريب|الضمان|الوظيفه)"
    r"|(ادفع|دفع).{0,40}(للحصول على|قبل بدء|لبدء) (الوظيفه|العمل|المهام)"
)
COMMISSION_TRANSFER = R(
    r"\b(receive|accept)\b.{0,40}\b(and|then) (transfer|forward|send|move)\b.{0,40}\b(money|funds|payments?)"
    r"|\b(transfer|move|process)\b.{0,30}\b(money|funds|payments)\b.{0,60}\b(commission|percentage|cut)\b"
    r"|\buse your (personal )?(bank )?account\b.{0,60}\b(commission|receive)\b"
    r"|\b(payment|money|financial) (processing|transfer) (agent|assistant|representative)\b"
    r"|(استلام|استقبال).{0,40}(وتحويل|ثم تحويل).{0,40}(الاموال|المبالغ|الدفعات)"
    r"|(تحويل|نقل) (الاموال|المبالغ).{0,60}(عموله|نسبه)"
    r"|حسابك (البنكي|الشخصي).{0,60}(عموله|استلام)"
)
COMMISSION_RATE = R(
    r"\bcommission\b.{0,25}\d+(\.\d+)?\s?%|\d+(\.\d+)?\s?%.{0,20}\bcommission\b|\bcommission rate\b"
    r"|\b(profit|return|income|rebate)\b.{0,15}\d+(\.\d+)?\s?%.{0,15}\b(per|each|daily|a day|every)\b"
    r"|عموله.{0,25}\d+(\.\d+)?\s?%|\d+(\.\d+)?\s?%.{0,20}عموله|نسبه العموله|العموله اليوميه"
)
VIP = R(r"\bvip ?\d{1,2}\b|\bv\d{1,2}\b(?= ?(level|member))|\blevel ?\d{1,2}\b|\blv\.? ?\d{1,2}\b|المستوى ?\d{1,2}|مستوى ?\d{1,2}")
INVITATION = R(
    r"\b(invitation|invite|referral|referrer|promo|recommend(ation)?) ?code\b|\binvite friends\b|\bmy team\b"
    r"|رمز الدعوه|كود الدعوه|رمز الاحاله|كود الاحاله|ادع اصدقاءك|دعوه الاصدقاء|رمز التوصيه"
)
WITHDRAWAL = R(
    r"\bwithdraw(al|als)?\b.{0,60}\b(after|only|minimum|min\.|requires?|condition|complete|unlock|fee|tax|freeze|frozen)\b"
    r"|\b(minimum|min\.) withdrawal\b|\bwithdrawal (fee|tax|limit|threshold)\b"
    r"|السحب.{0,50}(بعد|فقط|الحد الادنى|يتطلب|شرط|اكمال|رسوم|ضريبه|تجميد)|الحد الادنى للسحب|رسوم السحب"
)
TASK_EARNING = R(
    r"\b(complete|finish|grab|submit) (\d+ )?(orders?|tasks?|missions?|ratings?)\b|\bdaily tasks?\b"
    r"|\bearn\b.{0,30}\b(per|each|every|a) (task|order|day|video|like|review)\b|\bpart[\s-]?time\b"
    r"|\bwork from (home|your phone)\b|\b(like|watch|rate) (videos|products|movies|dramas)\b|\bgrab order\b|\boptimi[sz]e (products|orders)\b"
    r"|مهام يوميه|اكمال المهام|انجاز المهام|عمل جزئي|دوام جزئي|العمل من المنزل|اربح.{0,20}(لكل|يوميا)|مشاهده الفيديوهات|تقييم المنتجات"
)
GAMBLING = R(
    r"\b(casino|slot games?|slot machines?|online slots|betting|sportsbook|jackpot|roulette|baccarat|poker|blackjack|lottery|bet now|place (a |your )?bet|free spins|lucky ?spin|spin (the )?wheel)\b"
    r"|كازينو|رهان|مراهنه|مراهنات|قمار|سلوتس|جاكبوت|روليت|يانصيب"
)
BONUS = R(r"\b(welcome|first deposit|deposit|signup|sign-up) bonus\b|\b\d{2,3}\s?% bonus\b|مكافاه (الايداع|الترحيب)|بونص")
INVESTMENT = R(
    r"\bguaranteed (returns?|profits?|income|earnings)\b|\b(daily|weekly) (profit|return|income|roi) of \d"
    r"|\d+(\.\d+)?\s?% (daily|per day|a day|weekly|per week)\b|\bdouble your (money|investment|deposit)\b"
    r"|\brisk[\s-]?free (investment|returns?|profit)\b|\b(roi|returns?) (up to )?\d{2,4}\s?%"
    r"|ارباح مضمونه|عائد (مضمون|يومي)|ربح يومي|ارباح يوميه|بدون مخاطره|ضاعف (اموالك|استثمارك)"
)
FAKE_SHOP = R(r"\b([7-9]\d)\s?% off\b|\bup to ([7-9]\d)\s?%\b|\bclearance sale\b|\bclosing down sale\b|خصم ([7-9]\d)\s?%|تخفيضات تصل الى ([7-9]\d)")
COMPANY_DETAILS = R(
    r"\b(about us|our company|trade licen[cs]e|commercial registration|registered office|head office|"
    r"company registration|vat (number|registration)|privacy policy|terms (and|&) conditions|careers)\b"
    r"|من نحن|رخصه تجاريه|السجل التجاري|المقر الرئيسي|سياسه الخصوصيه|الشروط والاحكام"
)
BLOCK_PAGE = R(
    r"\b(access denied|attention required|just a moment|verify you are human|checking your browser|"
    r"not available in your (region|country)|request blocked|forbidden|captcha)\b"
)
PARCEL_CONTEXT = R(r"\b(parcel|package|shipment|courier|customs|consignment|tracking number|redelivery)\b|طرد|شحنه|الجمارك|رقم التتبع|اعاده التوصيل")
PARCEL_FEE = R(
    # A demand to pay to get a held parcel released / redelivered (not general information about duties).
    r"\bpay\b.{0,40}\bto (release|receive|redeliver|reschedule)\b.{0,25}\b(parcel|package|shipment|order)"
    r"|\b(parcel|package|shipment)\b.{0,40}\b(on hold|held|suspended|pending|could not be delivered)\b.{0,60}\b(pay|fee|charge)\b"
    r"|ادفع.{0,30}(لاستلام|لتحرير|لاعاده توصيل) (الطرد|الشحنه)|(الطرد|الشحنه).{0,30}(معلق|محجوز).{0,40}(ادفع|رسوم)"
)

# Negation cue shortly before a behavior match ("we never ask you to pay to receive tasks").
NEGATION = R(r"\b(never|not|no|don'?t|doesn'?t|won'?t|will not|without|free of charge|nor)\b|لا |لن |ابدا|ليس |دون |بدون |مجانا")
NEGATION_WINDOW = 32

SIGNIN = R(r"\b(sign in|log in|login|password|username)\b|تسجيل الدخول|كلمه المرور|اسم المستخدم")

# --- form fields --------------------------------------------------------------------------------
FIELD_CARD = R(r"card ?(number|no|num)|cardnumber|cc-?number|ccnum|credit ?card|debit ?card|رقم البطاقه|بطاقه الائتمان")
FIELD_CVV = R(r"\b(cvv2?|cvc2?|csc|cid)\b|security code|card ?code|رمز (الامان|cvv)")
FIELD_OTP = R(r"\botp\b|one[\s-]?time (password|code|pin)|verification code|sms code|auth(entication)? code|رمز التحقق|رمز التاكيد|كلمه المرور لمره واحده")
FIELD_BANK_PW = R(r"(online|internet|net|mobile) ?banking (password|pin)|\batm ?pin\b|\bcard ?pin\b|\bpin ?code\b|كلمه (مرور|سر) (البنك|المصرف)|الرقم السري")
FIELD_EXPIRY = R(r"expir(y|ation)|exp ?date|mm ?/ ?yy|تاريخ الانتهاء")

# --- currency amounts ---------------------------------------------------------------------------
NUM = r"(\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
CURRENCY_WORDS = {
    "AED": r"aed|dhs?\.?|dirhams?|درهم|دراهم|د\.ا\.?|د\.ا",
    "USD": r"usd|us\$|\$|dollars?|دولار",
    "USDT": r"usdt|tether",
    "SAR": r"sar|riyals?|ريال",
    "EUR": r"eur|€|euros?|يورو",
    "INR": r"inr|₹|rupees?",
}
AMOUNT_RES = []
for _code, _cw in CURRENCY_WORDS.items():
    AMOUNT_RES.append((_code, R(rf"(?:(?<![a-z])(?:{_cw}))\s?{NUM}")))
    AMOUNT_RES.append((_code, R(rf"{NUM}\s?(?:(?:{_cw}))(?![a-z])")))

MESSAGING_HOST_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?(wa\.me|api\.whatsapp\.com|chat\.whatsapp\.com|t\.me|telegram\.me|telegram\.dog|line\.me|"
    r"viber\.click|m\.me)\b[^\s\"'<>]*|whatsapp://send[^\s\"'<>]*|tg://resolve[^\s\"'<>]*",
    re.I,
)
SCAM_HOST_TLDS = {"shop", "vip", "buzz", "top", "xyz", "online", "store", "quest", "space", "cc", "icu", "click",
                  "cyou", "sbs", "cfd", "bond", "club", "site", "live", "work", "fun", "pro", "win", "bet"}
BRANDLIKE_LABEL_RE = re.compile(r"^[a-z]{3,}-?(vip|gl|mall|shop|global|uae|ae|task|order)\d*$|^(vip|svip)\d+$")
