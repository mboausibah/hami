/** On-device redaction before anything leaves the browser (mirrors the backend sanitizer). */
const EMAIL = /[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}/g;
const INTL_PHONE = /(?<![\w/])(?:\+|00)\d[\d\s\-().]{6,18}\d(?!\w)/g;
const UAE_MOBILE = /(?<![\w.])0?5[024568][\s-]?\d{3}[\s-]?\d{4}(?!\w)/g;
const ARABIC_DIGITS = /[٠-٩۰-۹]/g;

export function redactText(text: string): string {
  const western = text.replace(ARABIC_DIGITS, (d) => String((d.charCodeAt(0) & 0xf) % 10));
  let out = western.replace(EMAIL, "[email]");
  out = out.replace(INTL_PHONE, (m) => ((m.match(/\d/g) || []).length >= 8 ? "[phone]" : m));
  return out.replace(UAE_MOBILE, "[phone]");
}

/** URL without query string, fragment or credentials (http/https/ws/wss only). */
export function stripUrl(url: string): string | null {
  try {
    const u = new URL(url);
    if (!["http:", "https:", "ws:", "wss:"].includes(u.protocol)) return null;
    return `${u.protocol}//${u.host}${u.pathname}`;
  } catch {
    return null;
  }
}
