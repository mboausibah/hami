/** Structure of the page as rendered in this browser, computed on the device. Used when the user checks a page
 * (Hami button) or when a consented automatic check runs, never on sites the pre-filter skips. It lets Hami see
 * pages that block its server-side capture (bot challenges) without the server getting past those checks.
 *
 * Sent: same-site paths referenced by the page (no query strings, no fragments except #/app routes), image file
 * names, form-field descriptors (type, name, placeholder, label, required/readonly; NEVER values - for password
 * fields not even whether they are filled), a redacted title and visible text, and two booleans. Read from the DOM
 * and inline scripts only: nothing is fetched, clicked or submitted. */
import { redactText, type PageSignals } from "@hami/shared";

const MAX_PATHS = 600;
const MAX_IMAGES = 200;
const MAX_FIELDS = 60;
const MAX_SCRIPT_CHARS = 2_000_000;
const PATH_RE = /["'`(=,\s](\/[A-Za-z][A-Za-z0-9_-]*(?:\/[A-Za-z0-9_.%-]+){1,8})/g;
const PAGES_RE = /["'`]\/?((?:pages|views)\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+){0,4})["'`]/g;
const IDENTITY_RE = /terms|privacy|about|contact|legal|imprint|company|الشروط|الخصوصية|من نحن|اتصل/i;

function baseDomain(host: string): string {
  const parts = host.toLowerCase().split(".");
  // Approximation for the device; the server re-checks with the Public Suffix List.
  const twoLevel = parts.length > 2 && /^(co|com|net|org|gov|ac|edu)$/.test(parts[parts.length - 2]);
  return parts.slice(twoLevel ? -3 : -2).join(".");
}

function sameSite(u: URL, site: string): boolean {
  const h = u.hostname.toLowerCase();
  return h === site || h.endsWith(`.${site}`);
}

function cleanPath(p: string): string | null {
  const path = p.split("?")[0].split("#")[0];
  if (!path.startsWith("/") || path.startsWith("//") || path.length > 200 || /^\/cdn-cgi\//.test(path)) return null;
  return path;
}

function fileName(src: string): string | null {
  const clean = src.split("?")[0].split("#")[0];
  if (!clean || clean.startsWith("data:")) return null;
  const name = clean.split("/").pop() ?? "";
  return name ? name.slice(0, 120) : null;
}

export function collectPageSignals(doc: Document = document, loc: Location = location): PageSignals {
  const site = baseDomain(loc.hostname);
  const paths = new Set<string>();
  const add = (p: string | null): void => {
    if (p && paths.size < MAX_PATHS) paths.add(p);
  };
  add(cleanPath(loc.pathname));
  if (loc.hash.startsWith("#/")) add(`/#/${loc.hash.slice(2).split("?")[0]}`);
  for (const el of Array.from(doc.querySelectorAll("[href],[src],[action],[data-url],[data-href],[data-src]")).slice(0, 4000)) {
    for (const attr of ["href", "src", "action", "data-url", "data-href", "data-src"]) {
      const v = el.getAttribute(attr);
      if (!v || v.startsWith("javascript:") || v.startsWith("mailto:") || v.startsWith("tel:")) continue;
      try {
        const u = new URL(v, loc.href);
        if (!sameSite(u, site)) continue;
        add(cleanPath(u.pathname));
        if (u.hash.startsWith("#/")) add(`/#/${u.hash.slice(2).split("?")[0]}`);
      } catch {
        /* not a URL */
      }
    }
  }
  let budget = MAX_SCRIPT_CHARS;
  const scriptTexts: string[] = [];
  for (const s of Array.from(doc.querySelectorAll("script:not([src])"))) {
    const t = (s.textContent ?? "").slice(0, budget);
    budget -= t.length;
    scriptTexts.push(t);
    if (budget <= 0) break;
  }
  for (const el of Array.from(doc.querySelectorAll("[onclick]")).slice(0, 500)) scriptTexts.push(el.getAttribute("onclick") ?? "");
  for (const text of scriptTexts) {
    for (const m of text.matchAll(PATH_RE)) add(cleanPath(m[1]));
    for (const m of text.matchAll(PAGES_RE)) add(`/${m[1]}`);
  }

  const images = new Set<string>();
  for (const img of Array.from(doc.images).slice(0, 500)) {
    const n = fileName(img.currentSrc || img.src);
    if (n && images.size < MAX_IMAGES) images.add(n);
  }
  for (const e of performance.getEntriesByType("resource") as PerformanceResourceTiming[]) {
    if (images.size >= MAX_IMAGES) break;
    if (e.initiatorType === "img" || e.initiatorType === "css" || /\.(png|jpe?g|gif|webp|svg|avif)(\?|$)/i.test(e.name)) {
      const n = fileName(e.name);
      if (n) images.add(n);
    }
  }

  const labels = new Map<string, string>();
  for (const l of Array.from(doc.querySelectorAll("label[for]"))) labels.set(l.getAttribute("for") ?? "", (l.textContent ?? "").trim());
  const fields: PageSignals["fields"] = [];
  for (const el of Array.from(doc.querySelectorAll("input,select,textarea"))) {
    if (fields.length >= MAX_FIELDS) break;
    const input = el as HTMLInputElement;
    const type = (input.getAttribute("type") ?? el.tagName).toLowerCase();
    if (["submit", "button", "image", "reset", "file"].includes(type)) continue;
    const label = input.getAttribute("aria-label") ?? labels.get(input.id) ?? "";
    fields.push({
      type: type.slice(0, 20),
      name: redactText(input.getAttribute("name") ?? input.id ?? "").slice(0, 80),
      placeholder: redactText(input.getAttribute("placeholder") ?? "").slice(0, 80),
      label: redactText(label).slice(0, 80),
      autocomplete: (input.getAttribute("autocomplete") ?? "").slice(0, 40),
      required: input.hasAttribute("required"),
      readonly: input.hasAttribute("readonly") || input.hasAttribute("disabled"),
      // Only whether a non-secret field arrived pre-filled (e.g. an invite code); never the value itself.
      has_value: type !== "password" && type !== "checkbox" && type !== "radio" && (input.getAttribute("value") ?? "").trim() !== "",
    });
  }

  const identityLinks = Array.from(doc.querySelectorAll("a")).slice(0, 2000)
    .some((a) => IDENTITY_RE.test(`${a.getAttribute("href") ?? ""} ${a.textContent ?? ""}`));
  const h5Shell = !!doc.querySelector("uni-app, uni-page, uni-page-body") ||
    scriptTexts.some((t) => /__uniConfig|uni-app/.test(t.slice(0, 200_000)));
  const text = redactText((doc.body?.innerText ?? "").replace(/\n{3,}/g, "\n\n")).slice(0, 8000);

  return {
    page_url: `${loc.origin}${loc.pathname}`,
    title: redactText(doc.title ?? "").slice(0, 200),
    lang: (doc.documentElement.getAttribute("lang") ?? "").slice(0, 8),
    text,
    paths: Array.from(paths),
    images: Array.from(images),
    fields,
    identity_links: identityLinks,
    h5_shell: h5Shell,
  };
}
