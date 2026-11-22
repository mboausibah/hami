/** Every Google page selector lives here, each with fallbacks. Google changes its markup often:
 * when all selectors fail, the content scripts do nothing and the toolbar / right-click checks
 * still work. */

export const SEARCH = {
  /** Areas that contain organic results and ads. */
  areas: ["#search", "#rso", "#tads", "#tadsb", "#bottomads", "#botstuff", "div[role='main']"],
  /** Organic result title links: an anchor wrapping an <h3>. */
  organicLink: ["a[href]:has(> h3)", "a[href]:has(h3)", "a[jsname][href] h3"],
  /** Sponsored result links. */
  adLink: ["[data-text-ad] a[data-pcu]", "[data-text-ad] a[href]", "#tads a[data-rw]", "#tads a[href]:has([role='heading'])"],
  /** Element after which the shield is inserted inside a result. */
  titleOf: ["h3", "[role='heading']", "div[aria-level='3']"],
};

export const MAPS = {
  businessName: ["h1.DUwDvf", "div[role='main'] h1", "h1.fontHeadlineLarge", "[data-listing-name] .listing-name", "h1"],
  website: [
    "a[data-item-id='authority']",
    "a[aria-label^='Website']",
    "a[aria-label^='الموقع']",
    "a[data-tooltip='Open website']",
  ],
  panel: ["div[role='main']", "[data-listing-name]", "body"],
};

export function first<T extends Element = Element>(selectors: string[], root: ParentNode = document): T | null {
  for (const s of selectors) {
    try {
      const found = root.querySelector<T>(s);
      if (found) return found;
    } catch {
      /* selector unsupported in this browser version */
    }
  }
  return null;
}

export function all<T extends Element = Element>(selectors: string[], root: ParentNode = document): T[] {
  const out = new Set<T>();
  for (const s of selectors) {
    try {
      root.querySelectorAll<T>(s).forEach((e) => out.add(e));
    } catch {
      /* ignore */
    }
  }
  return [...out];
}

/** Destination URL of a Google result/ad link (unwraps /url?q= and ad redirect links). */
export function destinationOf(a: HTMLAnchorElement): string | null {
  const pcu = a.getAttribute("data-pcu");
  if (pcu) return pcu.split(",")[0] ?? null;
  try {
    const u = new URL(a.href, location.href);
    if (/(^|\.)google\.[a-z.]+$/.test(u.hostname) || u.hostname.endsWith("googleadservices.com")) {
      return u.searchParams.get("adurl") || u.searchParams.get("q") || u.searchParams.get("url");
    }
    return u.protocol.startsWith("http") ? u.href : null;
  } catch {
    return null;
  }
}
