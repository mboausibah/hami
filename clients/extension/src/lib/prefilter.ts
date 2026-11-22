/** On-device pre-filter for automatic checking. Runs in the background worker; nothing here talks to a server.
 *
 * Always skipped: sensitive categories (banking, government, e-mail, health, insurance, education portals, ...).
 * Skipped: well-known sites (Tranco top 10,000 + allowlist) unless a reviewer confirmed them as high risk.
 * Candidates: everything else, with reasons (unknown site, recently certificate-logged, kit indicator, page signals).
 */
import { hostMatches, normalizeHost } from "@hami/shared";
import wellKnownData from "../data/well_known.json";

const WELL_KNOWN = new Set<string>((wellKnownData as { domains: string[] }).domains);

/** Extra well-known sites not in the top 10,000 (UAE services people use daily). */
const ALLOWLIST = [
  "bayt.com", "naukrigulf.com", "gulftalent.com", "dubizzle.com", "propertyfinder.ae", "noon.com", "amazon.ae",
  "careem.com", "talabat.com", "deliveroo.ae", "carrefouruae.com", "sharafdg.com", "namshi.com", "luluhypermarket.com",
  "centrepointstores.com", "6thstreet.com", "aramex.com", "emiratespost.ae", "du.ae", "etisalat.ae", "eand.com",
  "emirates.com", "etihad.com", "adnoc.ae", "majidalfuttaim.com",
];

/** Sensitive categories: never checked automatically, whatever the user's settings. */
const SENSITIVE_HOST_RE = new RegExp(
  [
    "(^|\\.)gov(\\.[a-z]{2,3})?$", "(^|\\.)mil(\\.[a-z]{2})?$", "\\.gov\\.ae$", "\\.ac\\.ae$", "\\.edu(\\.[a-z]{2})?$",
    "(^|[.-])(bank|banking|ebank|netbank|onlinebank|mybank)([.-]|$)", "(^|[.-])(webmail|mail|email|inbox|outlook)([.-]|$)",
    "(^|[.-])(health|hospital|clinic|pharmacy|medical|medic|doctor|patient|lab|insurance)([.-]|$)",
  ].join("|"),
  "i",
);
const SENSITIVE_DOMAINS = [
  // e-mail and accounts
  "gmail.com", "mail.google.com", "accounts.google.com", "outlook.com", "live.com", "hotmail.com", "yahoo.com",
  "proton.me", "protonmail.com", "icloud.com", "zoho.com",
  // UAE banks and payments
  "emiratesnbd.com", "adcb.com", "bankfab.com", "mashreq.com", "dib.ae", "adib.ae", "rakbank.ae", "cbd.ae", "hsbc.ae",
  "citibank.ae", "enbd.com", "liv.me", "wio.io", "paypal.com", "stripe.com",
  // UAE government and health
  "u.ae", "mohre.gov.ae", "uaepass.ae", "icp.gov.ae", "dha.gov.ae", "doh.gov.ae", "seha.ae", "mohap.gov.ae",
  "adpolice.gov.ae", "dubaipolice.gov.ae",
];

export interface Lists {
  version: string;
  hosts: string[];
  domains: string[];
  recent_cert_domains: string[];
  kit_files: string[];
  syncedAt: string | null;
  error?: string | null;
}

export interface Classification {
  highRisk: boolean;
  skip: boolean;
  reason: "high_risk_list" | "sensitive" | "well_known" | "not_http" | "candidate";
  reasons: string[];
}

function inSet(host: string, set: Set<string> | string[]): boolean {
  const h = normalizeHost(host);
  const parts = h.split(".");
  for (let i = 0; i < parts.length - 1; i++) {
    const suffix = parts.slice(i).join(".");
    if (set instanceof Set ? set.has(suffix) : set.includes(suffix)) return true;
  }
  return false;
}

export function isSensitive(host: string): boolean {
  return SENSITIVE_HOST_RE.test(host) || inSet(host, SENSITIVE_DOMAINS);
}

export function isWellKnown(host: string): boolean {
  return inSet(host, WELL_KNOWN) || inSet(host, ALLOWLIST);
}

export function isHighRisk(host: string, lists: Pick<Lists, "hosts" | "domains">): boolean {
  return lists.hosts.some((h) => hostMatches(host, h)) || lists.domains.some((d) => hostMatches(host, d));
}

export function classify(url: string, lists: Lists, resourceNames: string[] = []): Classification {
  let host: string;
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return { highRisk: false, skip: true, reason: "not_http", reasons: [] };
    host = u.hostname.toLowerCase();
  } catch {
    return { highRisk: false, skip: true, reason: "not_http", reasons: [] };
  }
  if (isHighRisk(host, lists)) return { highRisk: true, skip: true, reason: "high_risk_list", reasons: [] };
  if (isSensitive(host)) return { highRisk: false, skip: true, reason: "sensitive", reasons: [] };
  if (isWellKnown(host)) return { highRisk: false, skip: true, reason: "well_known", reasons: [] };
  const reasons = ["unknown_site"];
  if (lists.recent_cert_domains.some((d) => hostMatches(host, d))) reasons.push("recent_certificate");
  if (resourceNames.length && lists.kit_files.length) {
    const kit = new Set(lists.kit_files);
    if (resourceNames.some((n) => kit.has(n))) reasons.push("kit_indicator");
  }
  return { highRisk: false, skip: false, reason: "candidate", reasons };
}
