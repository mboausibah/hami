import type { Bilingual, Tier } from "./types";

export interface TierStyle {
  color: string; // foreground / accent
  background: string;
  icon: string; // short symbol, rendered in a coloured badge
  label: Bilingual;
  headline: Bilingual;
}

export const TIERS: Record<Tier, TierStyle> = {
  high_risk: {
    color: "#b42318",
    background: "#fde8e7",
    icon: "!",
    label: { en: "High risk", ar: "خطر مرتفع" },
    headline: {
      en: "This page shows strong signs of fraud. Do not pay or share your details.",
      ar: "تظهر هذه الصفحة مؤشرات قوية على الاحتيال. لا تدفع ولا تشارك بياناتك.",
    },
  },
  caution: {
    color: "#9a6700",
    background: "#fff4d6",
    icon: "?",
    label: { en: "Caution", ar: "تنبيه" },
    headline: { en: "Be careful. Some things on this page looked unusual.", ar: "كن حذرًا. بعض ما في هذه الصفحة بدا غير معتاد." },
  },
  no_strong_signals: {
    color: "#1a7f37",
    background: "#e6f4ea",
    icon: "✓",
    label: { en: "No strong signals", ar: "لا توجد مؤشرات قوية" },
    headline: {
      en: "Nothing strong was found. This is not a guarantee that the site is safe.",
      ar: "لم نجد مؤشرات قوية. هذا ليس ضمانًا بأن الموقع آمن.",
    },
  },
  insufficient_evidence: {
    color: "#475467",
    background: "#eef1f4",
    icon: "…",
    label: { en: "Insufficient evidence", ar: "أدلة غير كافية" },
    headline: {
      en: "We could not check this page properly. Treat payment requests with care.",
      ar: "لم نتمكن من فحص هذه الصفحة بشكل كافٍ. تعامل بحذر مع أي طلب للدفع.",
    },
  },
};

export const UNKNOWN_STYLE = { color: "#667085", background: "#f2f4f7", icon: "•" };

export function tierStyle(tier: Tier | null | undefined): TierStyle | null {
  return tier ? TIERS[tier] : null;
}

/** Sort order for shields and lists (most severe first). */
export const TIER_RANK: Record<Tier, number> = { high_risk: 0, caution: 1, insufficient_evidence: 2, no_strong_signals: 3 };
