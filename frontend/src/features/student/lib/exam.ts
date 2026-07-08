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

/* -------------------------------------------------------------------------- */
/* Timed mocks, result, review, analytics + diagnostic/revision (S11.2/3/5)    */
/* S-56 mock runner · S-57 result · S-58 review · S-59 analytics               */
/* -------------------------------------------------------------------------- */

/** Extra sample/guardrail labels (educational-only; no official/rank claim). */
export const SAMPLE_SCORING_LABEL = 'sample scoring';
export const EXPLANATION_SAMPLE_LABEL = 'explanation is sample';
export const VERIFY_CITATION_LABEL = 'verify citation';
export const SAMPLE_COHORT_LABEL = 'sample cohort data';
/** Educational-only analytics disclaimer — never a rank/selection/pass claim. */
export const ANALYTICS_DISCLAIMER =
  'Analytics are educational feedback from sample cohort data — not official scoring, rank, or selection prediction.';
export const AIBE_PRACTICE_NOTE =
  'AIBE readiness is practice support only, not eligibility or pass certification. Verify the current official AIBE syllabus.';

export interface MockQuestion {
  readonly id: string;
  readonly section: string;
  readonly prompt: string;
  readonly options: readonly string[];
  readonly correctIndex: number;
  readonly explanation: string;
  /** citation | sample — drives the per-explanation guardrail chip. */
  readonly explanationKind: 'citation' | 'sample';
}

/** Sample mock — clearly not a real paper (guardrail). */
export const SAMPLE_MOCK: readonly MockQuestion[] = [
  {
    id: 'q12',
    section: 'Legal Reasoning',
    prompt: 'Which standard did Maneka Gandhi read into "procedure established by law" under Article 21?',
    options: ['Any procedure enacted by legislature', 'Just, fair and reasonable procedure', 'Procedure approved by the executive'],
    correctIndex: 1,
    explanation: 'Maneka Gandhi read a just, fair and reasonable standard into Article 21.',
    explanationKind: 'sample',
  },
  {
    id: 'q13',
    section: 'Legal Reasoning',
    prompt: 'Anticipatory bail under s.438 CrPC is best described as…',
    options: ['Mandatory on arrest', 'Discretionary and wide', 'Available only post-charge'],
    correctIndex: 1,
    explanation: 'Anticipatory bail is discretionary and wide. See Sushila Aggarwal (2020).',
    explanationKind: 'citation',
  },
];

export const MOCK_TOTAL = 100;

export interface MockResult {
  readonly score: number;
  readonly total: number;
  readonly estimatedPercentile: number;
  readonly sections: ReadonlyArray<{ section: string; accuracyPct: number; weak: boolean }>;
}

/** Evaluate selected answers against the sample mock (0-based indices). */
export function evaluateAnswers(answers: Record<string, number>, bank: readonly MockQuestion[] = SAMPLE_MOCK): number {
  return bank.reduce((n, q) => (answers[q.id] === q.correctIndex ? n + 1 : n), 0);
}

/** Weak sections are those below the threshold (drives warn treatment). */
export const WEAK_SECTION_THRESHOLD = 70;
export function weakSections(
  sections: ReadonlyArray<{ section: string; accuracyPct: number }>
): string[] {
  return sections.filter((s) => s.accuracyPct < WEAK_SECTION_THRESHOLD).map((s) => s.section);
}

export const SAMPLE_RESULT: MockResult = {
  score: 78,
  total: MOCK_TOTAL,
  estimatedPercentile: 88.4,
  sections: [
    { section: 'Legal Reasoning', accuracyPct: 88, weak: false },
    { section: 'Reasoning', accuracyPct: 74, weak: false },
    { section: 'GK', accuracyPct: 61, weak: true },
  ],
};

export const ANALYTICS_SECTIONS: ReadonlyArray<{ section: string; accuracyPct: number; weak: boolean }> = [
  { section: 'Legal Reasoning', accuracyPct: 88, weak: false },
  { section: 'Reasoning', accuracyPct: 81, weak: false },
  { section: 'English', accuracyPct: 76, weak: false },
  { section: 'GK & Current Affairs', accuracyPct: 64, weak: true },
];

/** Revision queue: weakest sections first (educational feedback only). */
export function revisionQueue(
  sections: ReadonlyArray<{ section: string; accuracyPct: number }> = ANALYTICS_SECTIONS
): string[] {
  return [...sections].sort((a, b) => a.accuracyPct - b.accuracyPct).map((s) => s.section);
}

/** AIBE subject map (source-versioned; sample distribution, not official). */
export const AIBE_SUBJECTS: ReadonlyArray<{ subject: string; items: number }> = [
  { subject: 'Constitutional Law', items: 10 },
  { subject: 'Criminal Law (IPC/BNS)', items: 8 },
  { subject: 'Civil Procedure & Limitation', items: 8 },
  { subject: 'Professional Ethics', items: 7 },
];
