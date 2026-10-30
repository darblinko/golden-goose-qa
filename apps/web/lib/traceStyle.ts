export type KindGroup =
  | "records"
  | "documents"
  | "design"
  | "supplier"
  | "person"
  | "revision";

/** Legend order. Colours live in globals.css as --trace-<group>. */
export const KIND_GROUPS: { group: KindGroup; label: string }[] = [
  { group: "records", label: "Records" },
  { group: "documents", label: "Procedures and documents" },
  { group: "design", label: "Design" },
  { group: "supplier", label: "Supplier" },
  { group: "person", label: "Person" },
  { group: "revision", label: "Revision" },
];

const RECORD_KINDS = new Set([
  "capa",
  "ncr",
  "complaint",
  "mdr",
  "emdr",
  "dhr",
  "dhr_scanned",
  "internal_audit",
  "management_review",
  "verification_report",
]);

const DESIGN_KINDS = new Set(["requirement", "design_output", "fmea_row"]);

const KIND_NAMES: Record<string, string> = {
  capa: "CAPA",
  ncr: "NCR",
  mdr: "MDR",
  emdr: "eMDR",
  sop: "SOP",
  wi: "Work instruction",
  dhr: "DHR",
  dhr_scanned: "DHR (scanned)",
  dfmea: "DFMEA",
  pfmea: "PFMEA",
  fmea_row: "FMEA row",
};

export function kindGroup(kind: string): KindGroup {
  if (RECORD_KINDS.has(kind)) return "records";
  if (DESIGN_KINDS.has(kind)) return "design";
  if (kind === "supplier" || kind === "person" || kind === "revision") {
    return kind;
  }
  return "documents";
}

export function kindName(kind: string): string {
  const known = KIND_NAMES[kind];
  if (known) return known;
  const words = kind.replace(/_/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : "Record";
}

export function truncateKey(key: string, max = 22): string {
  return key.length > max ? `${key.slice(0, max - 3)}...` : key;
}

/** Radius and label metrics per ring. Hop 0 is the anchor. */
export function nodeMetrics(hop: number): {
  radius: number;
  fontSize: number;
  fontWeight: number;
} {
  if (hop === 0) return { radius: 15, fontSize: 14, fontWeight: 700 };
  if (hop === 1) return { radius: 8, fontSize: 12.5, fontWeight: 600 };
  return { radius: 6, fontSize: 11.5, fontWeight: 500 };
}

export const BADGE_FONT_SIZE = 10;
export const BADGE_PAD_X = 4;
export const BADGE_GAP = 5;
