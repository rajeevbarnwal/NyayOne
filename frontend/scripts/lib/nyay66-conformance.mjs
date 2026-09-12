// Current tooling only: never writes or supersedes historical reference evidence.
export const SOURCE_SHA256 = '338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252';
export const VIEWS = ['s03', 's04', 's05', 's08', 's09', 's10a', 's10b', 's11', 's12', 's13', 's14', 's14p', 's15', 's16', 's17'];
export const VIEWPORTS = [
  { id: 'mobile390', width: 390, height: 844 },
  { id: 'desktop', width: 1440, height: 1024 },
];

export function coverage(theme = 'light') {
  return [...Array.from({ length: 17 }, (_, i) => `S-${String(i + 1).padStart(2, '0')}`), 'S-07-popup'].map(screen => {
    const views = screen === 'S-07-popup' ? ['s14p'] : screen === 'S-07' ? ['s14'] : screen === 'S-10' ? ['s10a', 's10b'] : VIEWS.filter(view => view === screen.toLowerCase().replace('-', ''));
    return { screen, views: theme === 'light' ? views : [], status: theme !== 'light' || !views.length ? 'DESIGN-GAP' : 'NOT-YET-MEASURED' };
  });
}

export function comparePixels(a, b) {
  if (a.width !== b.width || a.height !== b.height) throw Error('DIMENSION_MISMATCH');
  let sum = 0, mismatch = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    let changed = false;
    for (let c = 0; c < 3; c++) {
      const difference = Math.abs(a.data[i + c] - b.data[i + c]);
      sum += difference; changed ||= difference !== 0;
    }
    mismatch += Number(changed);
  }
  return { meanAbsDiff: sum / (a.width * a.height * 3), mismatchRatio: mismatch / (a.width * a.height) };
}

export function validateCalibration(report) {
  const errors = [];
  if (report?.sourceSha256 !== SOURCE_SHA256) errors.push('SOURCE_HASH_MISMATCH');
  if (!/^[a-f0-9]{40}$/.test(report?.head ?? '')) errors.push('INVALID_HEAD');
  if (report?.purpose !== 'REFERENCE_CALIBRATION_ONLY') errors.push('PURPOSE_MISMATCH');
  const expected = new Set(VIEWS.flatMap(view => VIEWPORTS.map(vp => `${view}:${vp.id}`)));
  const rows = Array.isArray(report?.rows) ? report.rows : [];
  if (rows.length !== expected.size) errors.push('INCOMPLETE_INVENTORY');
  for (const row of rows) {
    const key = `${row.view}:${row.viewport}`;
    if (!expected.delete(key)) errors.push('UNKNOWN_OR_DUPLICATE_PANEL');
    const vp = VIEWPORTS.find(value => value.id === row.viewport);
    if (!vp || row.dimensions?.[0] !== vp.width || row.dimensions?.[1] !== vp.height) errors.push('DIMENSION_MISMATCH');
    if (row.executed !== true || row.runtimeErrors !== 0 || row.blockedRequests !== 0) errors.push('CAPTURE_FAILED');
    if (!Array.isArray(row.sampleHashes) || row.sampleHashes.length !== 3 || row.sampleHashes.some(hash => !/^[a-f0-9]{64}$/.test(hash))) errors.push('INVALID_SAMPLE_HASHES');
    if (!Array.isArray(row.deltas) || row.deltas.length !== 2 || row.deltas.some(delta =>
      !Number.isFinite(delta.meanAbsDiff) || delta.meanAbsDiff < 0 || delta.meanAbsDiff > 255 ||
      !Number.isFinite(delta.mismatchRatio) || delta.mismatchRatio < 0 || delta.mismatchRatio > 1)) errors.push('INVALID_METRICS');
  }
  if (expected.size) errors.push('MISSING_PANEL');
  return errors;
}

// Pure verdict classifier; the eventual producer must validate the approval
// record and measured proof fields before calling it. No tolerance is active yet.
export function classifyObservation(row, policy) {
  if (policy.enforced && !policy.toleranceApproval) throw Error('TOLERANCE_APPROVAL_REQUIRED');
  if (row.reference === false) return { verdict: 'DESIGN-GAP', blocking: policy.enforced === true };
  if (!policy.toleranceApproval) return { verdict: 'CALIBRATION-PENDING', blocking: false };
  const pass = ['reference', 'executed', 'pixels', 'structure', 'accessibility'].every(key => row[key] === true);
  return { verdict: pass ? 'PARITY' : policy.enforced ? 'REGRESSION' : 'NONCONFORMANT', blocking: !pass && policy.enforced === true };
}
