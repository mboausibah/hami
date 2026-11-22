// ../shared/src/config.ts
var e = "http://localhost:8000";
function t(e) {
	let t = e.trim().replace(/\/+$/, "");
	if (!/^https?:\/\//i.test(t)) throw Error("Server URL must start with http:// or https://");
	return t;
}
// ../shared/src/api.ts
var n = class extends Error {
	status;
	constructor(e, t) {
		super(e), this.status = t, this.name = "HamiApiError";
	}
}, r = class {
	deviceId;
	timeoutMs;
	baseUrl;
	constructor(e, n, r = 75e3) {
		this.deviceId = n, this.timeoutMs = r, this.baseUrl = t(e);
	}
	resolve(e) {
		return /^https?:\/\//i.test(e) ? e : this.baseUrl + e;
	}
	async request(e, t, r, i = this.timeoutMs) {
		let a = new AbortController(), o = setTimeout(() => a.abort(), i);
		try {
			let i = await fetch(this.baseUrl + t, {
				method: e,
				headers: {
					"Content-Type": "application/json",
					"X-Device-Id": this.deviceId
				},
				body: r === void 0 ? void 0 : JSON.stringify(r),
				signal: a.signal
			});
			if (!i.ok) {
				let e = i.statusText;
				try {
					let t = await i.json();
					t.detail && (e = typeof t.detail == "string" ? t.detail : JSON.stringify(t.detail));
				} catch {}
				throw new n(e, i.status);
			}
			return await i.json();
		} catch (e) {
			throw e instanceof n ? e : e.name === "AbortError" ? new n("timeout", 0) : new n(e.message || "network error", 0);
		} finally {
			clearTimeout(o);
		}
	}
	scan(e, t = {}) {
		return this.request("POST", "/scans", {
			url: e,
			source_type: t.sourceType ?? "extension",
			listing_name: t.listingName || null,
			lang: t.lang ?? "en",
			device_id: this.deviceId,
			force: t.force ?? !1
		});
	}
	getScan(e, t) {
		return this.request("GET", `/scans/${e}?k=${encodeURIComponent(t)}`);
	}
	lookupHosts(e) {
		return this.request("POST", "/lookup/hosts", { hosts: e.slice(0, 60) }, 15e3);
	}
	watch(e, t) {
		return this.request("POST", "/watches", {
			scan_id: e,
			device_id: this.deviceId,
			k: t
		});
	}
	unwatch(e) {
		return this.request("DELETE", `/watches/${encodeURIComponent(e)}?device_id=${encodeURIComponent(this.deviceId)}`);
	}
	watches() {
		return this.request("GET", `/watches?device_id=${encodeURIComponent(this.deviceId)}`, void 0, 15e3);
	}
	alerts() {
		return this.request("GET", `/alerts?device_id=${encodeURIComponent(this.deviceId)}`, void 0, 15e3);
	}
	highRiskHosts() {
		return this.request("GET", "/indicators/high-risk-hosts", void 0, 15e3);
	}
	health() {
		return this.request("GET", "/health", void 0, 8e3);
	}
}, i = /^[A-Za-z0-9-]{8,64}$/;
function a() {
	return globalThis.crypto.randomUUID();
}
function o(e) {
	return typeof e == "string" && i.test(e);
}
async function s(e, t) {
	let n = await e();
	if (o(n)) return n;
	let r = a();
	return await t(r), r;
}
// ../shared/src/strings.ts
var c = {
	appName: {
		en: "Hami",
		ar: "حامي"
	},
	tagline: {
		en: "Check links before you pay",
		ar: "افحص الروابط قبل أن تدفع"
	},
	checkThisPage: {
		en: "Check this page",
		ar: "افحص هذه الصفحة"
	},
	checkThisLink: {
		en: "Check this link with Hami",
		ar: "افحص هذا الرابط مع حامي"
	},
	checkNow: {
		en: "Check now",
		ar: "افحص الآن"
	},
	checking: {
		en: "Checking… this takes up to 20 seconds",
		ar: "جارٍ الفحص… قد يستغرق حتى ٢٠ ثانية"
	},
	recheck: {
		en: "Check again (live)",
		ar: "افحص مجددًا (مباشر)"
	},
	cannotCheckPage: {
		en: "This page can't be checked (only http and https pages).",
		ar: "لا يمكن فحص هذه الصفحة (فقط صفحات http و https)."
	},
	listingNameLabel: {
		en: "Business name shown in the listing (optional)",
		ar: "اسم النشاط كما يظهر في الإدراج (اختياري)"
	},
	listingNameHelp: {
		en: "From Google Maps or a search result. Hami compares it with the name the site claims.",
		ar: "من خرائط Google أو نتيجة البحث. يقارنه حامي بالاسم الذي يدّعيه الموقع."
	},
	clues: {
		en: "Why",
		ar: "السبب"
	},
	originalText: {
		en: "Seen on the page",
		ar: "كما ظهر في الصفحة"
	},
	whatToDo: {
		en: "What to do now",
		ar: "ماذا تفعل الآن"
	},
	notChecked: {
		en: "What Hami could not check",
		ar: "ما لم يتمكن حامي من فحصه"
	},
	liveCapture: {
		en: "Live check",
		ar: "فحص مباشر"
	},
	storedCapture: {
		en: "Stored capture",
		ar: "نسخة محفوظة"
	},
	capturedAt: {
		en: "Captured",
		ar: "وقت الالتقاط"
	},
	siteOffline: {
		en: "The site could not be reached now; this result is from the stored capture.",
		ar: "تعذر الوصول إلى الموقع الآن؛ هذه النتيجة من النسخة المحفوظة."
	},
	reviewedAs: {
		en: "Reviewed by Hami as",
		ar: "تمت مراجعته من حامي على أنه"
	},
	model: {
		en: "Model",
		ar: "النموذج"
	},
	watch: {
		en: "Watch for updates",
		ar: "تابع التحديثات"
	},
	watchHelp: {
		en: "If a reviewer later links a related site to this one, you'll see it in Updates. Uses a random device ID only.",
		ar: "إذا ربط أحد المراجعين لاحقًا موقعًا مرتبطًا بهذا الموقع، سيظهر لك في التحديثات. يُستخدم معرّف جهاز عشوائي فقط."
	},
	watching: {
		en: "Watching",
		ar: "قيد المتابعة"
	},
	updates: {
		en: "Updates",
		ar: "التحديثات"
	},
	check: {
		en: "Check",
		ar: "فحص"
	},
	noUpdates: {
		en: "No updates yet. Watch a checked site to get reviewer-approved updates here.",
		ar: "لا توجد تحديثات بعد. تابع موقعًا فحصته لتصلك هنا التحديثات التي يوافق عليها المراجعون."
	},
	watchedSites: {
		en: "Watched sites",
		ar: "المواقع المتابعة"
	},
	stopWatching: {
		en: "Stop watching",
		ar: "إيقاف المتابعة"
	},
	relatedSite: {
		en: "Related site",
		ar: "موقع مرتبط"
	},
	withdrawn: {
		en: "Withdrawn by a reviewer",
		ar: "سحبه أحد المراجعين"
	},
	newBadge: {
		en: "New",
		ar: "جديد"
	},
	report: {
		en: "Report scams through official police channels, e.g. Abu Dhabi Police Aman (8002626) or the eCrime platform.",
		ar: "أبلغ عن الاحتيال عبر القنوات الرسمية للشرطة، مثل خدمة أمان لشرطة أبوظبي (8002626) أو منصة الجرائم الإلكترونية."
	},
	serverError: {
		en: "Could not reach the Hami server",
		ar: "تعذر الاتصال بخادم حامي"
	},
	rateLimited: {
		en: "Too many checks right now. Please wait a minute.",
		ar: "عدد كبير من الفحوصات الآن. يرجى الانتظار دقيقة."
	},
	openOptions: {
		en: "Settings",
		ar: "الإعدادات"
	},
	openFullResult: {
		en: "Open full result",
		ar: "فتح النتيجة كاملة"
	},
	shieldUnknown: {
		en: "Hami has not checked this site yet",
		ar: "لم يفحص حامي هذا الموقع بعد"
	},
	shieldLocalHigh: {
		en: "On Hami's reviewer-confirmed high-risk list",
		ar: "ضمن قائمة حامي للمواقع عالية الخطورة المؤكدة"
	},
	shieldKnown: {
		en: "What Hami knows about this site",
		ar: "ما يعرفه حامي عن هذا الموقع"
	},
	checkBusinessWebsite: {
		en: "Check this business website with Hami",
		ar: "افحص موقع هذا النشاط مع حامي"
	},
	listing: {
		en: "Listing",
		ar: "الإدراج"
	},
	bannerTitle: {
		en: "Hami warning: reviewer-confirmed high-risk site",
		ar: "تحذير حامي: موقع عالي الخطورة مؤكد من المراجعين"
	},
	bannerBody: {
		en: "A Hami reviewer confirmed this site as fraudulent. Do not pay, deposit or share card details, codes or passwords.",
		ar: "أكد أحد مراجعي حامي أن هذا الموقع احتيالي. لا تدفع ولا تودع ولا تشارك بيانات البطاقة أو الرموز أو كلمات المرور."
	},
	bannerLocal: {
		en: "Checked on your device against the local list. Nothing was sent to the server.",
		ar: "تم الفحص على جهازك مقابل القائمة المحلية. لم يُرسل أي شيء إلى الخادم."
	},
	autoCheckTitle: {
		en: "Hami auto-check",
		ar: "الفحص التلقائي من حامي"
	},
	dismiss: {
		en: "Dismiss",
		ar: "إخفاء"
	},
	optionsTitle: {
		en: "Hami settings",
		ar: "إعدادات حامي"
	},
	serverUrl: {
		en: "Server URL",
		ar: "عنوان الخادم"
	},
	serverUrlHelp: {
		en: "The Hami API this extension talks to.",
		ar: "واجهة حامي التي يتصل بها هذا الامتداد."
	},
	language: {
		en: "Language",
		ar: "اللغة"
	},
	searchChecks: {
		en: "Check search results",
		ar: "فحص نتائج البحث"
	},
	searchChecksHelp: {
		en: "Sends only the hostnames of Google Search results (never your query or full URLs) to the Hami server to show what it already knows. Off by default.",
		ar: "يرسل فقط أسماء نطاقات نتائج بحث Google (وليس عبارة البحث أو الروابط كاملة) إلى خادم حامي لعرض ما يعرفه. معطل افتراضيًا."
	},
	localList: {
		en: "Mark results and pages from the local high-risk list",
		ar: "تمييز النتائج والصفحات من القائمة المحلية عالية الخطورة"
	},
	localListHelp: {
		en: "Uses the reviewer-confirmed list stored on this device. No server call per page. On by default.",
		ar: "يستخدم القائمة المؤكدة من المراجعين والمخزنة على هذا الجهاز. لا اتصال بالخادم لكل صفحة. مفعل افتراضيًا."
	},
	autoCheck: {
		en: "Auto-check job and task pages",
		ar: "فحص صفحات الوظائف والمهام تلقائيًا"
	},
	autoCheckHelp: {
		en: "When a page looks like a job or task offer, sends its address to the Hami server for a check. This shares those page addresses. Off by default.",
		ar: "عندما تبدو الصفحة كعرض وظيفة أو مهام، يرسل عنوانها إلى خادم حامي لفحصها. هذا يعني مشاركة عناوين تلك الصفحات. معطل افتراضيًا."
	},
	privacyNote: {
		en: "Hami never sends your browsing history or search queries. Checks are sent only when you ask, or for job-like pages if you turn on auto-check.",
		ar: "لا يرسل حامي سجل تصفحك أو عبارات البحث. تُرسل الفحوصات فقط عندما تطلب ذلك، أو لصفحات الوظائف إذا فعّلت الفحص التلقائي."
	},
	save: {
		en: "Save",
		ar: "حفظ"
	},
	saved: {
		en: "Saved",
		ar: "تم الحفظ"
	},
	testConnection: {
		en: "Test connection",
		ar: "اختبار الاتصال"
	},
	connected: {
		en: "Connected",
		ar: "متصل"
	},
	listSynced: {
		en: "High-risk list on this device",
		ar: "القائمة عالية الخطورة على هذا الجهاز"
	},
	syncNow: {
		en: "Sync now",
		ar: "مزامنة الآن"
	},
	hosts: {
		en: "sites",
		ar: "مواقع"
	},
	version: {
		en: "version",
		ar: "الإصدار"
	}
};
function l(e, t) {
	return c[e][t];
}
function u(e) {
	return e && e.toLowerCase().startsWith("ar") ? "ar" : "en";
}
// ../shared/src/url.ts
function d(e) {
	try {
		let t = new URL(e);
		return t.protocol !== "http:" && t.protocol !== "https:" ? null : t.hostname.toLowerCase().replace(/\.$/, "");
	} catch {
		return null;
	}
}
// src/lib/settings.ts
var f = {
	serverUrl: e,
	lang: u(typeof navigator < "u" ? navigator.language : "en"),
	checkSearchResults: !1,
	localList: !0,
	autoCheck: !1
};
async function p() {
	let e = await chrome.storage.sync.get(f);
	return {
		...f,
		...e
	};
}
function m() {
	return s(async () => (await chrome.storage.local.get("deviceId")).deviceId ?? null, async (e) => chrome.storage.local.set({ deviceId: e }));
}
async function h() {
	let { highRisk: e } = await chrome.storage.local.get("highRisk");
	return e ?? {
		version: 0,
		hosts: [],
		syncedAt: null
	};
}
async function g() {
	let { watches: e } = await chrome.storage.local.get("watches");
	return e ?? {};
}
async function _(e) {
	await chrome.storage.local.set({ watches: e });
}
// src/background.ts
var v = "hami-check-link", y = "hami-sync";
async function b() {
	let [e, t] = await Promise.all([p(), m()]);
	return new r(e.serverUrl, t);
}
async function x() {
	let e = await p();
	await chrome.contextMenus.removeAll(), chrome.contextMenus.create({
		id: v,
		title: l("checkThisLink", e.lang),
		contexts: ["link"]
	});
}
async function S() {
	try {
		let e = await (await b()).highRiskHosts(), t = {
			version: e.version,
			hosts: e.hosts,
			syncedAt: (/* @__PURE__ */ new Date()).toISOString(),
			error: null
		};
		return await chrome.storage.local.set({ highRisk: t }), t;
	} catch (e) {
		let t = {
			...await h(),
			error: e.message
		};
		return await chrome.storage.local.set({ highRisk: t }), t;
	}
}
async function C() {
	return (await chrome.storage.local.get("seenAlerts")).seenAlerts ?? [];
}
function w(e) {
	return `${e.alert_id}:${e.withdrawn ? "w" : "a"}`;
}
async function T() {
	let e = await b(), [{ alerts: t }, { watches: n }] = await Promise.all([e.alerts(), e.watches()]), r = new Set(await C()), i = t.filter((e) => !r.has(w(e))).map((e) => e.alert_id);
	return await chrome.storage.local.set({ alertsCache: t }), await chrome.action.setBadgeBackgroundColor({ color: "#b42318" }), await chrome.action.setBadgeText({ text: i.length ? String(i.length) : "" }), {
		alerts: t,
		unseen: i,
		watches: n
	};
}
async function E() {
	await S();
	try {
		await T();
	} catch {}
}
function D(e) {
	return e instanceof n ? {
		ok: !1,
		error: e.message,
		status: e.status
	} : {
		ok: !1,
		error: e.message ?? String(e)
	};
}
async function O(e, t) {
	let n = `result:${t}`;
	await chrome.storage.session.set({ [n]: {
		at: Date.now(),
		result: e
	} });
}
var k = /* @__PURE__ */ new Set();
async function A(e) {
	let t = await p();
	switch (e.type) {
		case "scan": {
			let n = await (await b()).scan(e.url, {
				sourceType: e.sourceType ?? "extension",
				listingName: e.listingName,
				lang: t.lang,
				force: e.force
			});
			return await O(n, e.url), {
				ok: !0,
				data: n
			};
		}
		case "autoCheck": {
			if (!t.autoCheck) return {
				ok: !1,
				error: "auto-check disabled"
			};
			let n = d(e.url);
			if (!n || k.has(n)) return {
				ok: !1,
				error: "already checked"
			};
			k.add(n);
			let r = await (await b()).scan(e.url, {
				sourceType: "extension",
				lang: t.lang
			});
			return await O(r, e.url), {
				ok: !0,
				data: r
			};
		}
		case "getScan": return {
			ok: !0,
			data: await (await b()).getScan(e.scanId, e.key)
		};
		case "lookup": {
			if (!t.checkSearchResults) return {
				ok: !0,
				data: {}
			};
			let n = [...new Set(e.hosts.map((e) => e.toLowerCase()))].slice(0, 60), { results: r } = await (await b()).lookupHosts(n);
			return {
				ok: !0,
				data: r
			};
		}
		case "watch": {
			let t = await (await b()).watch(e.scanId, e.key), n = await g();
			return n[String(e.scanId)] = {
				watchId: t.watch_id,
				key: e.key,
				host: e.host
			}, await _(n), {
				ok: !0,
				data: t
			};
		}
		case "unwatch": {
			let t = await g(), n = t[String(e.scanId)];
			return n && await (await b()).unwatch(n.watchId).catch(() => void 0), delete t[String(e.scanId)], await _(t), {
				ok: !0,
				data: !0
			};
		}
		case "alerts": return {
			ok: !0,
			data: await T()
		};
		case "markAlertsSeen": {
			let e = (await chrome.storage.local.get("alertsCache")).alertsCache ?? [], t = new Set(await C());
			return e.forEach((e) => t.add(w(e))), await chrome.storage.local.set({ seenAlerts: [...t].slice(-500) }), await chrome.action.setBadgeText({ text: "" }), {
				ok: !0,
				data: !0
			};
		}
		case "syncNow": return await x(), {
			ok: !0,
			data: await S()
		};
		case "openResult": return await chrome.tabs.create({ url: chrome.runtime.getURL(`result/result.html?scan=${e.scanId}&k=${encodeURIComponent(e.key)}`) }), {
			ok: !0,
			data: !0
		};
	}
}
chrome.runtime.onMessage.addListener((e, t, n) => (A(e).then(n, (e) => n(D(e))), !0)), chrome.runtime.onInstalled.addListener(async () => {
	await m(), await x(), await chrome.alarms.create(y, {
		periodInMinutes: 30,
		delayInMinutes: .1
	}), await E();
}), chrome.runtime.onStartup.addListener(async () => {
	await x(), await E();
}), chrome.alarms.onAlarm.addListener((e) => {
	e.name === y && E();
}), chrome.storage.onChanged.addListener((e, t) => {
	t === "sync" && (e.lang || e.serverUrl) && (x(), e.serverUrl && E());
}), chrome.contextMenus.onClicked.addListener(async (e) => {
	e.menuItemId === v && e.linkUrl && await chrome.tabs.create({ url: chrome.runtime.getURL(`result/result.html?url=${encodeURIComponent(e.linkUrl)}&source=extension`) });
});
