/** Hostname helpers used by the clients (no network). */

export function hostOf(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }
}

export function normalizeHost(host: string): string {
  return host.toLowerCase().replace(/\.$/, "").replace(/^www\./, "");
}

/** True if `host` is `listed` or a subdomain of it. */
export function hostMatches(host: string, listed: string): boolean {
  const h = normalizeHost(host);
  const l = normalizeHost(listed);
  return h === l || h.endsWith("." + l);
}

export function isCheckableUrl(url: string | undefined | null): url is string {
  return !!url && /^https?:\/\//i.test(url);
}

/** First http(s) URL inside shared text (WhatsApp/SMS messages). */
export function firstUrl(text: string): string | null {
  const m = text.match(/https?:\/\/[^\s<>"']+/i);
  return m ? m[0].replace(/[),.;!?]+$/, "") : null;
}
