"""Bilingual (en/ar) user-facing text for tiers, clues, guidance and limitations."""
from __future__ import annotations

TIER_LABEL = {
    "high_risk": {"en": "High risk", "ar": "خطر مرتفع"},
    "caution": {"en": "Caution", "ar": "تنبيه"},
    "no_strong_signals": {"en": "No strong signals", "ar": "لا توجد مؤشرات قوية"},
    "insufficient_evidence": {"en": "Insufficient evidence", "ar": "أدلة غير كافية"},
}

TIER_HEADLINE = {
    "high_risk": {"en": "This page shows strong signs of fraud. Do not pay or share your details.",
                  "ar": "تظهر هذه الصفحة مؤشرات قوية على الاحتيال. لا تدفع ولا تشارك بياناتك."},
    "caution": {"en": "Be careful. Some things on this page looked unusual.",
                "ar": "كن حذرًا. بعض ما في هذه الصفحة بدا غير معتاد."},
    "no_strong_signals": {"en": "Nothing strong was found. This is not a guarantee that the site is safe.",
                          "ar": "لم نجد مؤشرات قوية. هذا ليس ضمانًا بأن الموقع آمن."},
    "insufficient_evidence": {"en": "We could not check this page properly. Treat payment requests with care.",
                              "ar": "لم نتمكن من فحص هذه الصفحة بشكل كافٍ. تعامل بحذر مع أي طلب للدفع."},
}

# Headline overrides when a specific behavior drives a High-risk result.
BEHAVIOR_HEADLINE = {
    "deposit_to_unlock": {"en": "This job page asks for money to unlock work. Do not pay. Verify the employer through an official channel.",
                          "ar": "هذه الصفحة تطلب دفع مبلغ لفتح المهام المدفوعة. لا تدفع. تحقق من جهة العمل عبر قناة رسمية."},
    "advance_fee": {"en": "This page asks for a fee before work or a job is given. Genuine employers do not ask for payment. Do not pay.",
                    "ar": "تطلب هذه الصفحة رسومًا قبل منح العمل أو الوظيفة. أصحاب العمل الحقيقيون لا يطلبون الدفع. لا تدفع."},
    "commission_transfer": {"en": "This page offers a commission for moving money through your account. This is how money mules are recruited. Do not take part.",
                            "ar": "تعرض هذه الصفحة عمولة مقابل تحويل أموال عبر حسابك. هكذا يتم تجنيد الوسطاء الماليين. لا تشارك."},
    "gambling_deposit": {"en": "This page asks for deposits for gambling or betting. Do not deposit money.",
                         "ar": "تطلب هذه الصفحة إيداعات للمراهنة أو القمار. لا تودع أي أموال."},
    "investment_promise": {"en": "This page promises guaranteed or very high returns. Do not invest.",
                           "ar": "تعد هذه الصفحة بأرباح مضمونة أو مرتفعة جدًا. لا تستثمر."},
    "credential_request": {"en": "This page asks for card details, one-time codes or banking passwords. Do not enter them.",
                           "ar": "تطلب هذه الصفحة بيانات البطاقة أو رموز التحقق أو كلمات مرور البنك. لا تدخلها."},
}

CLUE_TEXT = {
    "deposit_to_unlock": {"en": "Asks for a deposit or recharge to unlock tasks, levels or withdrawals{amount}.",
                          "ar": "تطلب إيداعًا أو شحن رصيد لفتح المهام أو المستويات أو السحب{amount}."},
    "advance_fee": {"en": "Asks for a fee before work or a job is released{amount}.",
                    "ar": "تطلب رسومًا قبل منح العمل أو الوظيفة{amount}."},
    "commission_transfer": {"en": "Offers a commission for receiving and moving money through your account.",
                            "ar": "تعرض عمولة مقابل استلام الأموال وتحويلها عبر حسابك."},
    "credential_request": {"en": "Has a form asking for card details, one-time codes or banking passwords.",
                           "ar": "تحتوي على نموذج يطلب بيانات البطاقة أو رموز التحقق أو كلمات مرور البنك."},
    "gambling_deposit": {"en": "Asks for deposits for betting or casino games.",
                         "ar": "تطلب إيداعات للمراهنة أو ألعاب الكازينو."},
    "investment_promise": {"en": "Promises guaranteed or unusually high returns.",
                           "ar": "تعد بأرباح مضمونة أو مرتفعة بشكل غير معتاد."},
    "identity_mismatch": {"en": "The listing name ({listing}) does not match the name the website claims ({claimed}).",
                          "ar": "اسم الإدراج ({listing}) لا يطابق الاسم الذي يدّعيه الموقع ({claimed})."},
    "reviewed_case_exact_host": {"en": "A Hami reviewer has already confirmed this site as fraudulent.",
                                 "ar": "أكد أحد مراجعي حامي سابقًا أن هذا الموقع احتيالي."},
    "reviewed_case_link": {"en": "This site is connected to a reviewed fraud case ({relation}).",
                           "ar": "هذا الموقع مرتبط بحالة احتيال تمت مراجعتها ({relation})."},
    "vip_table": {"en": "Shows a VIP or level table, typical of task-scam portals.",
                  "ar": "تعرض جدول مستويات أو VIP، وهو نمط شائع في مواقع احتيال المهام."},
    "withdrawal_condition": {"en": "Puts conditions on withdrawing your money.",
                             "ar": "تضع شروطًا على سحب أموالك."},
    "invitation_code": {"en": "Requires an invitation or referral code.",
                        "ar": "تطلب رمز دعوة أو إحالة."},
    "commission_rate": {"en": "Advertises commission or profit percentages per task or per day.",
                        "ar": "تعلن عن نسب عمولة أو أرباح لكل مهمة أو يوميًا."},
    "off_platform_contact": {"en": "The main contact is only a messaging-app link, with no company details.",
                             "ar": "وسيلة التواصل الوحيدة رابط تطبيق مراسلة، دون أي بيانات عن الشركة."},
    "task_earning": {"en": "Offers paid online tasks such as rating products, orders or videos.",
                     "ar": "تعرض مهام مدفوعة عبر الإنترنت مثل تقييم المنتجات أو الطلبات أو الفيديوهات."},
    "deposit_request": {"en": "Asks you to deposit or recharge money{amount}.",
                        "ar": "تطلب منك إيداع أو شحن مبلغ{amount}."},
    "unlock_condition": {"en": "Mentions unlocking tasks, levels or withdrawals.",
                         "ar": "تذكر فتح المهام أو المستويات أو السحب."},
    "gambling": {"en": "Contains betting or casino content.", "ar": "تحتوي على محتوى مراهنات أو كازينو."},
    "fake_shop_discount": {"en": "Advertises extreme discounts, common on fake shops.",
                           "ar": "تعلن عن تخفيضات مبالغ فيها، شائعة في المتاجر الوهمية."},
    "classifier_score": {"en": "The page's wording is similar to reviewed fraudulent pages.",
                         "ar": "صياغة الصفحة مشابهة لصفحات احتيالية تمت مراجعتها."},
}

RELATION_TEXT = {
    "registration_destination": {"en": "registration destination in captured JSON", "ar": "وجهة تسجيل في بيانات JSON الملتقطة"},
    "asset_host": {"en": "distinctive shared asset host", "ar": "مضيف ملفات مميز مشترك"},
    "same_template": {"en": "same page template", "ar": "نفس قالب الصفحة"},
    "same_payment_script": {"en": "same payment steps and amounts", "ar": "نفس خطوات الدفع والمبالغ"},
}

WHAT_TO_DO = {
    "high_risk": {
        "en": ["Do not pay, deposit or share card details, codes or passwords.",
               "Verify the employer or business through an official channel, not the contacts on this page.",
               "Report it through official police channels (for example the Abu Dhabi Police Aman service or eCrime platform)."],
        "ar": ["لا تدفع ولا تودع ولا تشارك بيانات البطاقة أو الرموز أو كلمات المرور.",
               "تحقق من جهة العمل أو النشاط التجاري عبر قناة رسمية، وليس عبر وسائل التواصل في هذه الصفحة.",
               "أبلغ عنها عبر القنوات الرسمية للشرطة (مثل خدمة أمان لشرطة أبوظبي أو منصة الجرائم الإلكترونية)."],
    },
    "caution": {
        "en": ["Do not pay anything until you have verified who runs this site.",
               "Check the company's official website, trade licence or phone number from an independent source.",
               "Genuine employers never ask you to pay to get a job or unlock tasks."],
        "ar": ["لا تدفع أي مبلغ قبل التحقق من الجهة التي تدير هذا الموقع.",
               "تحقق من الموقع الرسمي للشركة أو رخصتها التجارية أو رقم هاتفها من مصدر مستقل.",
               "أصحاب العمل الحقيقيون لا يطلبون الدفع مقابل الوظيفة أو فتح المهام."],
    },
    "no_strong_signals": {
        "en": ["Stay careful if you are later asked to pay, deposit or move money.",
               "Check again with Hami if the site starts asking for money."],
        "ar": ["ابقَ حذرًا إذا طُلب منك لاحقًا الدفع أو الإيداع أو تحويل الأموال.",
               "افحص الموقع مجددًا عبر حامي إذا بدأ يطلب المال."],
    },
    "insufficient_evidence": {
        "en": ["Do not pay or share details on this site until you can verify it.",
               "Try again later, or verify the business through an official channel."],
        "ar": ["لا تدفع ولا تشارك بياناتك على هذا الموقع حتى تتمكن من التحقق منه.",
               "حاول مرة أخرى لاحقًا، أو تحقق من النشاط التجاري عبر قناة رسمية."],
    },
}

NOT_CHECKED = {
    "behind_signin": {"en": "Pages behind sign-in or registration (Hami never signs in or submits forms).",
                      "ar": "الصفحات التي تتطلب تسجيل الدخول أو التسجيل (حامي لا يسجل الدخول ولا يرسل النماذج)."},
    "payment_pages": {"en": "Payment pages and what happens after a deposit.",
                      "ar": "صفحات الدفع وما يحدث بعد الإيداع."},
    "operator": {"en": "Who operates the site.", "ar": "الجهة التي تدير الموقع."},
    "load_failed": {"en": "The page did not load, so its content could not be read.",
                    "ar": "لم يتم تحميل الصفحة، لذلك لم نتمكن من قراءة محتواها."},
    "thin_content": {"en": "The page showed too little content to judge.",
                     "ar": "عرضت الصفحة محتوى قليلًا جدًا لا يكفي للحكم."},
    "signin_wall": {"en": "The page requires signing in before showing its content.",
                    "ar": "تتطلب الصفحة تسجيل الدخول قبل عرض محتواها."},
    "cloaking": {"en": "The site may show different content to automated checks or visitors outside the UAE.",
                 "ar": "قد يعرض الموقع محتوى مختلفًا لأدوات الفحص الآلي أو للزوار من خارج الإمارات."},
    "no_model": {"en": "No trained model was available; only rule-based checks were applied.",
                 "ar": "لم يتوفر نموذج مدرب؛ تم تطبيق الفحوصات القائمة على القواعد فقط."},
    "stored_capture": {"en": "The site could not be reached now; this result uses a stored capture.",
                       "ar": "تعذر الوصول إلى الموقع الآن؛ تستند هذه النتيجة إلى نسخة محفوظة."},
    "identity_unclear": {"en": "Whether the listing name matches the site could not be confirmed.",
                         "ar": "لم نتمكن من التأكد من تطابق اسم الإدراج مع الموقع."},
}
