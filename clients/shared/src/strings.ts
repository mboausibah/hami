import type { Lang } from "./types";

/** All user-facing client strings, Arabic and English. */
export const STRINGS = {
  appName: { en: "Hami", ar: "حامي" },
  tagline: { en: "Check links before you pay", ar: "افحص الروابط قبل أن تدفع" },
  checkThisPage: { en: "Check this page", ar: "افحص هذه الصفحة" },
  checkThisLink: { en: "Check this link with Hami", ar: "افحص هذا الرابط مع حامي" },
  checkNow: { en: "Check now", ar: "افحص الآن" },
  checking: { en: "Checking… this takes up to 20 seconds", ar: "جارٍ الفحص… قد يستغرق حتى ٢٠ ثانية" },
  recheck: { en: "Check again (live)", ar: "افحص مجددًا (مباشر)" },
  cannotCheckPage: { en: "This page can't be checked (only http and https pages).", ar: "لا يمكن فحص هذه الصفحة (فقط صفحات http و https)." },
  listingNameLabel: { en: "Business name shown in the listing (optional)", ar: "اسم النشاط كما يظهر في الإدراج (اختياري)" },
  listingNameHelp: {
    en: "From Google Maps or a search result. Hami compares it with the name the site claims.",
    ar: "من خرائط Google أو نتيجة البحث. يقارنه حامي بالاسم الذي يدّعيه الموقع.",
  },
  clues: { en: "Why", ar: "السبب" },
  originalText: { en: "Seen on the page", ar: "كما ظهر في الصفحة" },
  whatToDo: { en: "What to do now", ar: "ماذا تفعل الآن" },
  notChecked: { en: "What Hami could not check", ar: "ما لم يتمكن حامي من فحصه" },
  liveCapture: { en: "Live check", ar: "فحص مباشر" },
  storedCapture: { en: "Stored capture", ar: "نسخة محفوظة" },
  capturedAt: { en: "Captured", ar: "وقت الالتقاط" },
  siteOffline: {
    en: "The site could not be reached now; this result is from the stored capture.",
    ar: "تعذر الوصول إلى الموقع الآن؛ هذه النتيجة من النسخة المحفوظة.",
  },
  reviewedAs: { en: "Reviewed by Hami as", ar: "تمت مراجعته من حامي على أنه" },
  model: { en: "Model", ar: "النموذج" },
  watch: { en: "Watch for updates", ar: "تابع التحديثات" },
  watchHelp: {
    en: "If a reviewer later links a related site to this one, you'll see it in Updates. Uses a random device ID only.",
    ar: "إذا ربط أحد المراجعين لاحقًا موقعًا مرتبطًا بهذا الموقع، سيظهر لك في التحديثات. يُستخدم معرّف جهاز عشوائي فقط.",
  },
  watching: { en: "Watching", ar: "قيد المتابعة" },
  updates: { en: "Updates", ar: "التحديثات" },
  check: { en: "Check", ar: "فحص" },
  noUpdates: { en: "No updates yet. Watch a checked site to get reviewer-approved updates here.", ar: "لا توجد تحديثات بعد. تابع موقعًا فحصته لتصلك هنا التحديثات التي يوافق عليها المراجعون." },
  watchedSites: { en: "Watched sites", ar: "المواقع المتابعة" },
  stopWatching: { en: "Stop watching", ar: "إيقاف المتابعة" },
  relatedSite: { en: "Related site", ar: "موقع مرتبط" },
  withdrawn: { en: "Withdrawn by a reviewer", ar: "سحبه أحد المراجعين" },
  newBadge: { en: "New", ar: "جديد" },
  report: {
    en: "Report scams through official police channels, e.g. Abu Dhabi Police Aman (8002626) or the eCrime platform.",
    ar: "أبلغ عن الاحتيال عبر القنوات الرسمية للشرطة، مثل خدمة أمان لشرطة أبوظبي (8002626) أو منصة الجرائم الإلكترونية.",
  },
  serverError: { en: "Could not reach the Hami server", ar: "تعذر الاتصال بخادم حامي" },
  rateLimited: { en: "Too many checks right now. Please wait a minute.", ar: "عدد كبير من الفحوصات الآن. يرجى الانتظار دقيقة." },
  openOptions: { en: "Settings", ar: "الإعدادات" },
  openFullResult: { en: "Open full result", ar: "فتح النتيجة كاملة" },
  // Search / Maps / banner
  shieldUnknown: { en: "Hami has not checked this site yet", ar: "لم يفحص حامي هذا الموقع بعد" },
  shieldLocalHigh: { en: "On Hami's reviewer-confirmed high-risk list", ar: "ضمن قائمة حامي للمواقع عالية الخطورة المؤكدة" },
  shieldKnown: { en: "What Hami knows about this site", ar: "ما يعرفه حامي عن هذا الموقع" },
  checkBusinessWebsite: { en: "Check this business website with Hami", ar: "افحص موقع هذا النشاط مع حامي" },
  listing: { en: "Listing", ar: "الإدراج" },
  bannerTitle: { en: "Hami warning: reviewer-confirmed high-risk site", ar: "تحذير حامي: موقع عالي الخطورة مؤكد من المراجعين" },
  bannerBody: {
    en: "A Hami reviewer confirmed this site as fraudulent. Do not pay, deposit or share card details, codes or passwords.",
    ar: "أكد أحد مراجعي حامي أن هذا الموقع احتيالي. لا تدفع ولا تودع ولا تشارك بيانات البطاقة أو الرموز أو كلمات المرور.",
  },
  bannerLocal: { en: "Checked on your device against the local list. Nothing was sent to the server.", ar: "تم الفحص على جهازك مقابل القائمة المحلية. لم يُرسل أي شيء إلى الخادم." },
  autoCheckTitle: { en: "Hami auto-check", ar: "الفحص التلقائي من حامي" },
  dismiss: { en: "Dismiss", ar: "إخفاء" },
  // Options
  optionsTitle: { en: "Hami settings", ar: "إعدادات حامي" },
  serverUrl: { en: "Server URL", ar: "عنوان الخادم" },
  serverUrlHelp: { en: "The Hami API this extension talks to.", ar: "واجهة حامي التي يتصل بها هذا الامتداد." },
  language: { en: "Language", ar: "اللغة" },
  searchChecks: { en: "Check search results", ar: "فحص نتائج البحث" },
  searchChecksHelp: {
    en: "Sends only the hostnames of Google Search results (never your query or full URLs) to the Hami server to show what it already knows. Off by default.",
    ar: "يرسل فقط أسماء نطاقات نتائج بحث Google (وليس عبارة البحث أو الروابط كاملة) إلى خادم حامي لعرض ما يعرفه. معطل افتراضيًا.",
  },
  localList: { en: "Mark results and pages from the local high-risk list", ar: "تمييز النتائج والصفحات من القائمة المحلية عالية الخطورة" },
  localListHelp: {
    en: "Uses the reviewer-confirmed list stored on this device. No server call per page. On by default.",
    ar: "يستخدم القائمة المؤكدة من المراجعين والمخزنة على هذا الجهاز. لا اتصال بالخادم لكل صفحة. مفعل افتراضيًا.",
  },
  autoCheck: { en: "Check unfamiliar pages automatically", ar: "افحص الصفحات غير المألوفة تلقائيًا" },
  autoCheckHelp: {
    en: "Needs your consent (shown once). Well-known, banking, government, e-mail and health sites are skipped on your device. For other pages the address is sent for a check, and after 10 seconds without activity a list of loaded files and servers (no query strings) plus the visible text. No cookies, form values or page contents from your browser.",
    ar: "يتطلب موافقتك (تظهر مرة واحدة). يتم تخطي المواقع المعروفة ومواقع البنوك والحكومة والبريد والصحة على جهازك. للصفحات الأخرى يُرسل العنوان للفحص، وبعد ١٠ ثوانٍ دون نشاط قائمة بالملفات والخوادم المحمّلة (دون معاملات الاستعلام) مع النص الظاهر. لا تُرسل ملفات تعريف الارتباط أو قيم النماذج أو محتوى الصفحات من متصفحك.",
  },
  privacyNote: {
    en: "Hami never sends your browsing history or search queries. Checks are sent only when you ask, or for job-like pages if you turn on auto-check.",
    ar: "لا يرسل حامي سجل تصفحك أو عبارات البحث. تُرسل الفحوصات فقط عندما تطلب ذلك، أو لصفحات الوظائف إذا فعّلت الفحص التلقائي.",
  },
  save: { en: "Save", ar: "حفظ" },
  saved: { en: "Saved", ar: "تم الحفظ" },
  testConnection: { en: "Test connection", ar: "اختبار الاتصال" },
  connected: { en: "Connected", ar: "متصل" },
  listSynced: { en: "High-risk list on this device", ar: "القائمة عالية الخطورة على هذا الجهاز" },
  syncNow: { en: "Sync now", ar: "مزامنة الآن" },
  hosts: { en: "sites", ar: "مواقع" },
  version: { en: "version", ar: "الإصدار" },
} as const satisfies Record<string, { en: string; ar: string }>;

export type StringKey = keyof typeof STRINGS;

export function t(key: StringKey, lang: Lang): string {
  return STRINGS[key][lang];
}

export function dirOf(lang: Lang): "rtl" | "ltr" {
  return lang === "ar" ? "rtl" : "ltr";
}

export function defaultLang(locale: string | undefined): Lang {
  return locale && locale.toLowerCase().startsWith("ar") ? "ar" : "en";
}
