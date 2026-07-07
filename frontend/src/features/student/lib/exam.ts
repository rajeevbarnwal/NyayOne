/**
 * Exam-track selection + source-versioned syllabus logic (SAATHI-147 · S11).
 * Guardrail: no official exam/legal claim without visible source metadata;
 * every content surface carries a source version + sample label. Analytics are
 * educational feedback only (no rank/selection guarantee). Pure + testable.
 */

export type ExamTrack = 'CLAT' | 'AIBE' | 'Judiciary';
export type Persona = 'clat' | 'graduate' | 'judiciary' | 'law_ug';

/** Persona-aware ordering of tracks (the active track is first). */
export function orderTracks(persona: Persona): ExamTrack[] {
  switch (persona) {
    case 'clat':
      return ['CLAT', 'Judiciary', 'AIBE'];
    case 'graduate':
      return ['AIBE', 'Judiciary', 'CLAT'];
    case 'judiciary':
      return ['Judiciary', 'AIBE', 'CLAT'];
    case 'law_ug':
    default:
      return ['Judiciary', 'AIBE', 'CLAT'];
  }
}

export interface SourceMeta {
  readonly version: string;
  readonly pattern: string;
  readonly verifyPrompt: string;
}

export const SOURCE_VERSION = 'v2026.1';
export const VERIFY_PROMPT = 'verify current notification';

/** Load-bearing source pill copy (must render on every exam content surface). */
export function sourcePillText(version: string = SOURCE_VERSION): string {
  return `SOURCE-VERSIONED · ${version} · ${VERIFY_PROMPT}`;
}

export const SYLLABUS: Record<ExamTrack, SourceMeta> = {
  CLAT: { version: SOURCE_VERSION, pattern: 'CLAT 2026 · consortium pattern', verifyPrompt: VERIFY_PROMPT },
  AIBE: { version: SOURCE_VERSION, pattern: 'AIBE XIX · BCI pattern', verifyPrompt: VERIFY_PROMPT },
  Judiciary: { version: SOURCE_VERSION, pattern: 'Judiciary (Karnataka) 2026', verifyPrompt: VERIFY_PROMPT },
};

/** Mandatory sample labels — no official claim may render without one of these. */
export const SAMPLE_ITEMS_LABEL = 'Sample items · not a real paper';
export const SAMPLE_LAW_LABEL = 'Sample — illustrative, not verified law';
export const ESTIMATED_PERCENTILE_LABEL = 'Estimated percentile from sample cohort';

export interface SyllabusStatus {
  readonly track: ExamTrack;
  readonly meta: SourceMeta;
  readonly sourceLabel: string;
}
export function syllabusFor(track: ExamTrack): SyllabusStatus {
  return { track, meta: SYLLABUS[track], sourceLabel: sourcePillText(SYLLABUS[track].version) };
}

/** True only when a content surface has both a source version and a sample label. */
export function hasVisibleSourceMetadata(s: { sourceVersion?: string; sampleLabel?: string }): boolean {
  return Boolean(s.sourceVersion) && Boolean(s.sampleLabel);
}

export const TRACK_NOTE_ASPIRANT =
  'CLAT is your primary track as a pre-law aspirant. Judiciary & AIBE become relevant after you enrol.';
export const TRACK_NOTE_ENROLLED = 'Syllabi vary and are source-versioned. CLAT is the R1 pilot for the Aspirant segment.';
