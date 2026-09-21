/* Risk scale helpers — WRI Aqueduct 0–5 ordinal scale, WSM palette. */

export const RISK_COLORS = ["#2171B5", "#6BAED6", "#FED976", "#FD8D3C", "#BD0026"];
export const NO_DATA_COLOR = "#3A4356";

export function riskColor(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return NO_DATA_COLOR;
  const i = Math.min(4, Math.max(0, Math.floor(score)));
  return RISK_COLORS[i];
}

export function classify(score: number | null | undefined): string | null {
  if (score === null || score === undefined) return null;
  if (score >= 4) return "Extremely High";
  if (score >= 3) return "High";
  if (score >= 2) return "Medium-High";
  if (score >= 1) return "Low-Medium";
  return "Low";
}

/** The 13 Aqueduct indicators, in WSM display order. */
export const INDICATORS: { code: string; label: string }[] = [
  { code: "bws", label: "Water stress" },
  { code: "bwd", label: "Water depletion" },
  { code: "iav", label: "Interannual variability" },
  { code: "sev", label: "Seasonal variability" },
  { code: "gtd", label: "Groundwater decline" },
  { code: "rfr", label: "Riverine flood" },
  { code: "cfr", label: "Coastal flood" },
  { code: "drr", label: "Drought risk" },
  { code: "ucw", label: "Untreated wastewater" },
  { code: "cep", label: "Coastal eutrophication" },
  { code: "udw", label: "Unimproved drinking water" },
  { code: "usa", label: "Unimproved sanitation" },
  { code: "rri", label: "Reg. & reputational" },
];

/** Map layers (S-01 layer selector). `prop` reads the normalized basin props. */
export const LAYERS: { id: string; label: string; prop: string }[] = [
  { id: "overall", label: "Overall Risk", prop: "overall" },
  { id: "bws", label: "Water Stress", prop: "bws" },
  { id: "bwd", label: "Depletion", prop: "bwd" },
  { id: "flood", label: "Flood", prop: "flood" }, // MAX(rfr, cfr), precomputed at load
  { id: "drr", label: "Drought", prop: "drr" },
  { id: "ucw", label: "Quality", prop: "ucw" },
  { id: "wash", label: "WASH", prop: "wash" }, // AVG(udw, usa), precomputed at load
];

export const CONFIDENCE_COLORS: Record<string, string> = {
  computed: "var(--chip-computed)",
  proxy: "var(--chip-proxy)",
  regional: "var(--chip-regional)",
  "no-data": "var(--chip-nodata)",
};
