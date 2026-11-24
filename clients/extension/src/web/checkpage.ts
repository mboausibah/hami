/** Public check page served by the Hami API at "/": paste a link (and optionally the business name from a listing),
 * get the same result card the extension shows. No login, no watches, no browsing data: only what is typed here is
 * sent, to this server. Built by extension/build.mjs into backend/app/web/static/check.js. */
import { HamiApi, HamiApiError, dirOf, t, type Lang, type ScanResult } from "@hami/shared";
import { CARD_CSS, renderCard } from "../lib/card";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
let lang: Lang = (localStorage.getItem("hami-lang") as Lang | null) === "ar" ? "ar" : "en";
let last: ScanResult | null = null;

function deviceId(): string {
  let id = sessionStorage.getItem("hami-device");
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem("hami-device", id);
  }
  return id;
}

const api = new HamiApi(location.origin, deviceId());

function applyLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = dirOf(lang);
  document.querySelectorAll<HTMLElement>("[data-en]").forEach((e) => {
    const v = e.dataset[lang];
    if (v !== undefined) e.textContent = v;
  });
  document.querySelectorAll<HTMLInputElement>("[data-ph-en]").forEach((e) => {
    e.placeholder = (lang === "ar" ? e.dataset.phAr : e.dataset.phEn) ?? "";
  });
  $("lang-btn").textContent = lang === "ar" ? "English" : "العربية";
  if (last) show(last);
}

function show(r: ScanResult): void {
  last = r;
  renderCard($("result"), r, { lang, resolve: (p) => api.resolve(p) });
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function check(force = false): Promise<void> {
  const url = $<HTMLInputElement>("url").value.trim();
  const name = $<HTMLInputElement>("listing").value.trim();
  const status = $("status");
  if (!url) {
    status.hidden = false;
    status.className = "status err";
    status.textContent = lang === "ar" ? "الصق رابطًا أولًا." : "Paste a link first.";
    return;
  }
  const btn = $<HTMLButtonElement>("check-btn");
  btn.disabled = true;
  status.hidden = false;
  status.className = "status";
  status.textContent = t("checking", lang);
  try {
    const r = await api.scan(url, { sourceType: name ? "search" : "manual", listingName: name || null, lang, force });
    status.hidden = true;
    show(r);
  } catch (e) {
    status.className = "status err";
    const err = e as HamiApiError;
    status.textContent = err.status === 429 ? t("rateLimited", lang)
      : err.status === 400 ? `${lang === "ar" ? "لا يمكن فحص هذا الرابط" : "This link cannot be checked"}: ${err.message}`
      : `${t("serverError", lang)} (${err.message})`;
  } finally {
    btn.disabled = false;
  }
}

function init(): void {
  const s = document.createElement("style");
  s.textContent = CARD_CSS;
  document.head.append(s);
  $("lang-btn").addEventListener("click", () => {
    lang = lang === "ar" ? "en" : "ar";
    localStorage.setItem("hami-lang", lang);
    applyLang();
  });
  $("check-form").addEventListener("submit", (e) => {
    e.preventDefault();
    void check();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-example]").forEach((b) =>
    b.addEventListener("click", () => {
      $<HTMLInputElement>("url").value = b.dataset.example ?? "";
      $<HTMLInputElement>("listing").value = b.dataset.listing ?? "";
      void check();
    }),
  );
  const q = new URLSearchParams(location.search).get("url");
  if (q) $<HTMLInputElement>("url").value = q;
  applyLang();
}

init();
