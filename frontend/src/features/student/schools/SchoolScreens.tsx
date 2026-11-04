import { S27SearchScreen } from './S27SearchScreen';
import { S28DetailScreen } from './S28DetailScreen';
import { S29ComparisonScreen } from './S29ComparisonScreen';
import { S30SavedSchools } from './S30SavedSchools';
import type { LawSchoolSummary } from '../lib/lawSchoolsApi';
import { feesLakhBand, verifiedText } from './lawschoolFormat.mjs';

// Retained legacy pure contracts; S-30 now renders only server-supplied summaries.
export function stableUniqueSchoolIds(ids: string[]): string[] {
  return [...new Set(ids)];
}

/** One canonical S-27/S-30 detail destination preserving the search return context. */
export function lawSchoolDetailPath(id: string, returnContext: string): string {
  return `/s-28?id=${encodeURIComponent(id)}${returnContext ? `&ret=${encodeURIComponent(returnContext)}` : ''}`;
}

/** Frozen S-30 contract: state (not city) + unchanged fee/sample/verification copy. */
export function schoolListMetaline(s: LawSchoolSummary): string {
  return `${s.state.toUpperCase()} · ${feesLakhBand(s.feesMin, s.feesMax).toUpperCase()} (SAMPLE) · ${verifiedText().toUpperCase()}`;
}

interface TrayEntry {
  id: string;
  name: string;
}

let compareTray: TrayEntry[] = [];

function readCompareTray(): TrayEntry[] {
  return compareTray;
}

function writeCompareTray(entries: TrayEntry[]): TrayEntry[] {
  compareTray = entries;
  return entries;
}


export function SchoolSearch(){return <S27SearchScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;}
export function SchoolDetail(){return <S28DetailScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;}
export function SchoolCompare(){return <S29ComparisonScreen readSelection={readCompareTray} writeSelection={writeCompareTray}/>;}
export function SchoolSavedFollowed(){return <S30SavedSchools writeSelection={writeCompareTray}/>;}
