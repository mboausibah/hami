/** On-device HAR sanitizer for investigator mode: the same rules as the backend importer's strict mode.
 * Removes cookies, credential-like headers (by name or by value), token-like query parameters, request bodies,
 * WebSocket messages, e-mail addresses and phone numbers; drops response bodies of requests that carried
 * credentials unless they are static files. */
import { redactText } from "./redact";

const SENSITIVE_HEADER_NAME = /(auth|token|session|cookie|sign|secret|api[-_]?key|csrf|xsrf|jwt|credential|password|visitor[-_]?id|device[-_]?id|client[-_]?id|\bcid\b)/i;
const BEARER = /^\s*(bearer|basic|token|digest)\s+\S+|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/i;
const TOKEN_PARAM = /(token|auth|key|session|sess|sid|sig|signature|password|passwd|pwd|secret|jwt|access|refresh|otp|code|email|mail|phone|mobile|tel|ticket|nonce|state|credential|login|user|uid|account|invite)/i;
const STATIC_MIME = /(javascript|ecmascript|text\/css|font\/|woff|svg|image\/)/i;
const JWT = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g;
const SENSITIVE_JSON_KEY = /(token|secret|password|passwd|pwd|session|sid|auth|cookie|sign(ature)?|invite|invit|referr|refer_?code|promo_?code|share_?code|phone|mobile|tel|email|mail|whatsapp|telegram|uid|user_?id|member_?id|account|username|user_?name|nick|real_?name|full_?name|id_?card|passport|bank|card_?no|iban|balance|wallet|address|ip|device_?id|imei|otp|captcha|verify_?code)/i;

export interface HarHeader { name: string; value: string }
export interface HarEntry {
  startedDateTime: string;
  time: number;
  request: { method: string; url: string; headers: HarHeader[]; cookies: unknown[]; queryString: HarHeader[];
             postData?: { mimeType: string; text: string }; httpVersion?: string; headersSize?: number; bodySize?: number };
  response: { status: number; statusText?: string; headers: HarHeader[]; cookies: unknown[];
              content: { size?: number; mimeType: string; text?: string | null; encoding?: string; _hami_body?: string };
              redirectURL?: string; httpVersion?: string; headersSize?: number; bodySize?: number };
  _resourceType?: string;
  _webSocketMessages?: unknown[];
  [k: string]: unknown;
}
export interface Har { log: { version: string; creator: { name: string; version: string }; pages?: unknown[]; entries: HarEntry[] } }

export function isSensitiveHeader(name: string, value: string): boolean {
  return SENSITIVE_HEADER_NAME.test(name) || BEARER.test(value || "");
}

function cleanText(s: string): string {
  return redactText(s).replace(JWT, "[token]");
}

export function sanitizeUrl(url: string): string {
  try {
    const u = new URL(url);
    for (const k of [...u.searchParams.keys()]) if (TOKEN_PARAM.test(k)) u.searchParams.delete(k);
    u.hash = "";
    u.username = "";
    u.password = "";
    return cleanText(u.toString());
  } catch {
    return "[unparseable-url]";
  }
}

function redactJson(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(redactJson);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) out[k] = SENSITIVE_JSON_KEY.test(k) && (typeof x !== "object" || x === null) ? "[redacted]" : redactJson(x);
    return out;
  }
  return typeof v === "string" ? cleanText(v) : v;
}

export function sanitizeHar(har: Har, maxBodyBytes = 1_500_000): Har {
  const entries = har.log.entries.map((e): HarEntry => {
    const hadAuth = e.request.headers.some((h) => isSensitiveHeader(h.name, h.value)) || e.request.cookies.length > 0 ||
      e.request.queryString.some((q) => TOKEN_PARAM.test(q.name));
    const headers = (hs: HarHeader[]) => hs.filter((h) => !isSensitiveHeader(h.name, h.value))
      .map((h) => (/^(referer|location|origin)$/i.test(h.name) ? { name: h.name, value: sanitizeUrl(h.value) } : h));
    const content = { ...e.response.content };
    const mime = content.mimeType || "";
    if (content.text !== null && content.text !== undefined) {
      if (content.encoding === "base64" || !/(text\/|json|javascript|ecmascript|xml|svg)/i.test(mime)) {
        content.text = null;
        content._hami_body = "binary-dropped";
        delete content.encoding;
      } else if (hadAuth && !STATIC_MIME.test(mime)) {
        content.text = null;
        content._hami_body = "authenticated-response-dropped";
      } else if (content.text.length > maxBodyBytes) {
        content.text = null;
        content._hami_body = "oversize-dropped";
      } else if (/json/i.test(mime)) {
        try {
          content.text = JSON.stringify(redactJson(JSON.parse(content.text)));
        } catch {
          content.text = cleanText(content.text);
        }
      } else {
        content.text = cleanText(content.text);
      }
    }
    const { _webSocketMessages: _ws, ...rest } = e;
    void _ws;
    return {
      ...rest,
      request: {
        ...e.request, url: sanitizeUrl(e.request.url), headers: headers(e.request.headers), cookies: [],
        queryString: e.request.queryString.filter((q) => !TOKEN_PARAM.test(q.name)).map((q) => ({ name: q.name, value: cleanText(q.value) })),
        ...(e.request.postData ? { postData: { mimeType: e.request.postData.mimeType, text: "[removed by sanitizer]" } } : {}),
      },
      response: { ...e.response, headers: headers(e.response.headers), cookies: [], content,
                  ...(e.response.redirectURL ? { redirectURL: sanitizeUrl(e.response.redirectURL) } : {}) },
    };
  });
  return { log: { ...har.log, entries } };
}

/** SHA-256 hex of a string (Web Crypto; works in extension pages and the service worker). */
export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
