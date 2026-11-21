const euro = new Intl.NumberFormat("fr-BE", { style: "currency", currency: "EUR" });

export function formatPrice(value: number | null | undefined): string {
  return value == null ? "—" : euro.format(value);
}

/** 0.42 -> "−58 %" ; 1.08 -> "+8 %" */
export function formatDelta(ratio: number | null | undefined): string | null {
  if (ratio == null) return null;
  const pct = Math.round((ratio - 1) * 100);
  return `${pct > 0 ? "+" : pct < 0 ? "−" : "±"}${Math.abs(pct)} %`;
}

export const PLATFORM_LABEL: Record<string, string> = {
  vinted: "Vinted",
  leboncoin: "Leboncoin",
  "2ememain": "2ememain",
};
