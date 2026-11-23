/** Bilingual result card (tier, up to 3 clues with screenshots, what to do, what couldn't be checked,
 * live/stored label, watch toggle). Used by the popup, the full result page and in-page overlays. */
import { STRINGS, dirOf, t, tierStyle, type Lang, type ScanResult, type StringKey } from "@hami/shared";

export const CARD_CSS = `
.hami-card{font:14px/1.45 system-ui,-apple-system,"Segoe UI","Noto Sans Arabic",Tahoma,sans-serif;color:#16202a;background:#fff}
.hami-card *{box-sizing:border-box}
.hami-tier{display:flex;gap:10px;align-items:flex-start;padding:12px;border-radius:10px;margin-bottom:10px}
.hami-icon{flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:800;font-size:16px}
.hami-label{font-weight:800;font-size:15px}.hami-headline{margin-top:2px}
.hami-sec{margin:10px 0}.hami-sec h4{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:#5b6876}
.hami-clue{display:flex;gap:8px;padding:8px;border:1px solid #e5e9ef;border-radius:8px;margin-bottom:6px}
.hami-clue img{flex:none;width:64px;height:44px;object-fit:cover;object-position:top;border-radius:4px;border:1px solid #e5e9ef;cursor:zoom-in}
.hami-excerpt{color:#5b6876;font-size:12px;margin-top:3px}
.hami-card ul{margin:0;padding-inline-start:18px}.hami-card li{margin:2px 0}
.hami-meta{color:#5b6876;font-size:12px;display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:8px}
.hami-pill{display:inline-block;padding:1px 8px;border-radius:999px;background:#eef1f4;font-size:12px}
.hami-warn{background:#fff4d6;border-radius:8px;padding:6px 8px;font-size:12px;margin:6px 0}
.hami-watch{display:flex;gap:8px;align-items:flex-start;padding:8px;border:1px dashed #cfd6df;border-radius:8px;margin-top:10px}
.hami-watch input{margin-top:3px}.hami-help{color:#5b6876;font-size:12px}
.hami-report{font-size:12px;color:#5b6876;margin-top:8px}
details.hami-nc summary{cursor:pointer;color:#5b6876;font-size:12px}
`;

export interface CardOptions {
  lang: Lang;
  resolve: (path: string) => string;
  compact?: boolean;
  watching?: boolean;
  onWatchToggle?: (on: boolean) => Promise<boolean>;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function fmtTime(iso: string | null, lang: Lang): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(lang === "ar" ? "ar-AE" : "en-AE", { dateStyle: "medium", timeStyle: "short" });
}

export function renderCard(container: HTMLElement, r: ScanResult, opts: CardOptions): void {
  const { lang } = opts;
  container.replaceChildren();
  const card = el("div", "hami-card");
  card.dir = dirOf(lang);
  card.lang = lang;
  const style = tierStyle(r.tier);
  if (!style) {
    card.append(el("p", undefined, t("serverError", lang)));
    container.append(card);
    return;
  }

  const head = el("div", "hami-tier");
  head.style.background = style.background;
  const icon = el("div", "hami-icon", style.icon);
  icon.style.background = style.color;
  const words = el("div");
  const label = el("div", "hami-label", r.tier_label?.[lang] ?? style.label[lang]);
  label.style.color = style.color;
  words.append(label, el("div", "hami-headline", r.headline?.[lang] ?? style.headline[lang]));
  head.append(icon, words);
  card.append(head);

  if (r.capture_mode === "stored" && r.live_failure) card.append(el("div", "hami-warn", t("siteOffline", lang)));

  if (r.clues.length) {
    const sec = el("div", "hami-sec");
    sec.append(el("h4", undefined, t("clues", lang)));
    for (const c of r.clues.slice(0, 3)) {
      const row = el("div", "hami-clue");
      if (c.screenshot_url && !opts.compact) {
        const img = el("img");
        img.src = opts.resolve(c.screenshot_url);
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("click", () => window.open(opts.resolve(c.screenshot_url!), "_blank", "noopener"));
        row.append(img);
      }
      const txt = el("div");
      txt.append(el("div", undefined, c.text[lang]));
      if (c.excerpt) {
        const ex = el("div", "hami-excerpt");
        const q = el("bdi", undefined, `“${c.excerpt}”`);
        q.dir = "auto";
        ex.append(`${t("originalText", lang)}: `, q);
        txt.append(ex);
      }
      row.append(txt);
      sec.append(row);
    }
    card.append(sec);
  }

  if (r.what_to_do && !opts.compact) {
    const sec = el("div", "hami-sec");
    sec.append(el("h4", undefined, t("whatToDo", lang)));
    const ul = el("ul");
    for (const s of r.what_to_do[lang]) ul.append(el("li", undefined, s));
    sec.append(ul);
    card.append(sec);
  }

  if (r.not_checked && r.not_checked[lang].length && !opts.compact) {
    const det = el("details", "hami-nc");
    det.append(el("summary", undefined, t("notChecked", lang)));
    const ul = el("ul");
    for (const s of r.not_checked[lang]) ul.append(el("li", undefined, s));
    det.append(ul);
    card.append(det);
  }

  const meta = el("div", "hami-meta");
  meta.append(el("span", "hami-pill", r.capture_mode === "live" ? t("liveCapture", lang) : t("storedCapture", lang)));
  if (r.captured_at) meta.append(el("span", undefined, `${t("capturedAt", lang)}: ${fmtTime(r.captured_at, lang)}`));
  const h = el("bdi", undefined, r.host);
  h.dir = "ltr";
  meta.append(h);
  if (r.review) {
    const key = `label_${r.review.label}` as StringKey;
    const label = key in STRINGS ? t(key, lang) : r.review.label;
    meta.append(el("span", undefined, `${t("reviewedAs", lang)}: ${label}`));
  }
  if (r.model_version && !opts.compact) meta.append(el("span", undefined, `${t("model", lang)}: ${r.model_version}`));
  card.append(meta);

  if (opts.onWatchToggle && !opts.compact) {
    const w = el("label", "hami-watch");
    const box = el("input");
    box.type = "checkbox";
    box.checked = !!opts.watching;
    const words2 = el("div");
    words2.append(el("strong", undefined, t("watch", lang)), el("div", "hami-help", t("watchHelp", lang)));
    w.append(box, words2);
    box.addEventListener("change", async () => {
      box.disabled = true;
      const ok = await opts.onWatchToggle!(box.checked);
      if (!ok) box.checked = !box.checked;
      box.disabled = false;
    });
    card.append(w);
  }

  if ((r.tier === "high_risk" || r.tier === "caution") && !opts.compact) card.append(el("div", "hami-report", t("report", lang)));
  container.append(card);
}

/** Shadow-DOM host for in-page overlays, isolated from the page's CSS. */
export function shadowHost(id: string): { host: HTMLElement; root: ShadowRoot } {
  document.getElementById(id)?.remove();
  const host = document.createElement("div");
  host.id = id;
  host.style.all = "initial";
  const root = host.attachShadow({ mode: "open" });
  return { host, root };
}
