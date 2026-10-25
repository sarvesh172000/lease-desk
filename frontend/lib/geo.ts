/**
 * Public geography only: which region a store's city belongs to, for
 * grouping the portfolio when the API gives no region. Never money, never a
 * lease fact. Unknown cities fall back to "Other".
 */

export type RegionId = "REG-BAY" | "REG-SOCAL" | "REG-DESERT" | "OTHER";

const CITY_REGION: Record<string, RegionId> = {
  "daly city": "REG-BAY",
  serramonte: "REG-BAY",
  "san mateo": "REG-BAY",
  bayview: "REG-BAY",
  "san francisco": "REG-BAY",
  oakland: "REG-BAY",
  berkeley: "REG-BAY",
  "san jose": "REG-BAY",
  "redwood city": "REG-BAY",
  "palo alto": "REG-BAY",
  fremont: "REG-BAY",
  "walnut creek": "REG-BAY",
  "los angeles": "REG-SOCAL",
  "san diego": "REG-SOCAL",
  irvine: "REG-SOCAL",
  "long beach": "REG-SOCAL",
  pasadena: "REG-SOCAL",
  anaheim: "REG-SOCAL",
  "santa monica": "REG-SOCAL",
  "palm springs": "REG-DESERT",
  "palm desert": "REG-DESERT",
  "las vegas": "REG-DESERT",
  henderson: "REG-DESERT",
  phoenix: "REG-DESERT",
  scottsdale: "REG-DESERT",
  tucson: "REG-DESERT",
};

/** "Northbay Coffee — Daly City — Suite 210" → "REG-BAY"; nothing recognisable → "OTHER". */
export function regionOfLocation(location: string | null | undefined): RegionId {
  if (!location) return "OTHER";
  const l = location.toLowerCase();
  for (const [city, region] of Object.entries(CITY_REGION)) if (l.includes(city)) return region;
  return "OTHER";
}

/** The order regions are shown in. */
export const REGION_ORDER: RegionId[] = ["REG-BAY", "REG-SOCAL", "REG-DESERT", "OTHER"];
