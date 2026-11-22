/** Small in-page widgets (shields, popovers, panels) rendered in shadow DOM. */
import { TIERS, UNKNOWN_STYLE, dirOf, t, type Lang, type ScanResult, type Tier } from "@hami/shared";
import { CARD_CSS, renderCard } from "../lib/card";
import { send } from "../lib/messages";

export const WIDGET_CSS = `${CARD_CSS}
:host{all:initial}
.w{font:13px/1.4 system-ui,-apple-system,"Segoe UI","Noto Sans Arabic",Tahoma,sans-serif;color:#16202a}
.shield{display:inline-flex;align-items:center;gap:4px;border:0;border-radius:999px;padding:1px 7px 1px 5px;cursor:pointer;
  font:600 11px/18px system-ui,sans-serif;color:#fff;vertical-align:middle;margin-inline-start:6px}
.shield svg{width:12px;height:12px;fill:currentColor}
.pop{position:absolute;z-index:2147483646;width:320px;background:#fff;border:1px solid #d9dee5;border-radius:10px;
  box-shadow:0 8px 24px rgba(0,0,0,.18);padding:10px;margin-top:4px}
.btn{background:#0b5d4b;color:#fff;border:0;border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit;font-weight:600}
.muted{color:#5b6876;font-size:12px}
a.full{color:#0b5d4b;font-size:12px;cursor:pointer;text-decoration:underline}
`;

const SHIELD_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3z"/></svg>';

export function colorFor(tier: Tier | null): { color: string; label: (l: Lang) => string } {
  if (!tier) return { color: UNKNOWN_STYLE.color, label: () => "Hami" };
  return { color: TIERS[tier].color, label: (l) => TIERS[tier].label[l] };
}

export function shieldButton(tier: Tier | null, lang: Lang): HTMLButtonElement {
  const b = document.createElement("button");
  b.className = "shield";
  b.type = "button";
  setShield(b, tier, lang);
  return b;
}

export function setShield(b: HTMLButtonElement, tier: Tier | null, lang: Lang, title?: string): void {
  const c = colorFor(tier);
  b.style.background = c.color;
  b.innerHTML = SHIELD_SVG;
  b.append(document.createTextNode(c.label(lang)));
  b.title = title ?? (tier ? c.label(lang) : t("shieldUnknown", lang));
  b.dataset.tier = tier ?? "";
}

/** Run a full scan from a content script and render a compact result into `box`. */
export async function checkInto(box: HTMLElement, url: string, lang: Lang, sourceType: "search" | "maps" | "extension",
                                listingName: string | null, onResult?: (r: ScanResult) => void): Promise<void> {
  box.replaceChildren();
  const p = document.createElement("div");
  p.className = "muted";
  p.textContent = t("checking", lang);
  box.append(p);
  const res = await send<ScanResult>({ type: "scan", url, sourceType, listingName });
  box.replaceChildren();
  if (!res.ok) {
    const e = document.createElement("div");
    e.className = "muted";
    e.textContent = res.status === 429 ? t("rateLimited", lang) : `${t("serverError", lang)} (${res.error})`;
    box.append(e);
    return;
  }
  const r = res.data;
  const holder = document.createElement("div");
  renderCard(holder, r, { lang, compact: true, resolve: (x) => x });
  const full = document.createElement("a");
  full.className = "full";
  full.textContent = t("openFullResult", lang);
  full.addEventListener("click", (ev) => {
    ev.preventDefault();
    void send({ type: "openResult", scanId: r.scan_id, key: r.access_key });
  });
  box.append(holder, full);
  onResult?.(r);
}

export function dirFor(lang: Lang): "rtl" | "ltr" {
  return dirOf(lang);
}
