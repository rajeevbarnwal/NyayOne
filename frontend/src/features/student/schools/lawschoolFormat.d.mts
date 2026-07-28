/** Types for lawschoolFormat.mjs (shared FE/scripts formatting — SAATHI-118/120/121 F2/F4). */
export interface CompareRowDef { readonly key: string; readonly label: string }
export interface CompareFormatInput {
  state: string;
  institutionType: string;
  accreditation: string;
  entranceExam: string;
  feesMin: number;
  feesMax: number;
  nirfRank: number | null;
  programmes: Array<{ degree: string; durationYears: number }>;
  facts: Record<string, string>;
}
export declare const REFERENCE_VERIFIED_DATE: string;
export declare const INSTITUTION_TYPE_LABELS: Record<string, string>;
export declare const FACT_LABELS: Record<string, string>;
export declare const COMPARE_ROWS: readonly CompareRowDef[];
export declare const REFERENCE_RESPONSIBLE_COPY: string;
export declare function inrAmount(n: number): string;
export declare function feesInrBand(feesMin: number, feesMax: number): string;
export declare function lakhAmount(n: number): string;
export declare function feesLakhBand(feesMin: number, feesMax: number): string;
export declare function institutionTypeLabel(t: string): string;
export declare function nirfText(rank: number | null): string;
export declare function programmesText(progs: Array<{ degree: string; durationYears: number }>): string;
export declare function compareRowValue(key: string, s: CompareFormatInput): string;
export declare function verifiedText(isoDate?: string): string;
export declare function referenceSourceFoot(): string;

export declare const APPROVED_SHORT_HANDLES: Readonly<Record<string, string>>;
export declare function shortHandle(name: string): string;
export declare function monogramText(name: string): string;
export declare const S28_FACT_KEY_ORDER: readonly string[];
export declare function factSourceLine(retrievedAtIso?: string | null): string;
export declare const REGIONS: readonly string[];
export declare const REGION_STATES: Readonly<Record<string, readonly string[]>>;
export declare function regionOfState(state: string): string;
