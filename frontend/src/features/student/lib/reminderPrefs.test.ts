import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  ReminderPrefService, defaultPrefs, validatePref, maskedPreview, isValidTimezone,
  REMINDER_LEAD_MINUTES, type ReminderPref,
} from './reminderPrefs';

const now = '2026-07-19T04:30:00.000Z';
const STU = 'stu-1';
const base: ReminderPref = {
  sourceType: 'exam', channel: 'in_app', enabled: true, leadMinutes: 30,
  quietStartMin: 22 * 60, quietEndMin: 7 * 60, timezone: 'Asia/Kolkata',
};
function svc() { return new ReminderPrefService(new InMemoryKvStore()); }

describe('S19.2 reminder preferences (SAATHI-290/292)', () => {
  it('writes only the exact NyayOne reminder-preference namespace', () => {
    const store = new InMemoryKvStore();
    new ReminderPrefService(store).savePref(STU, STU, base, now);

    expect(store.get(`nyayone.student.reminder-prefs.v1.${STU}`)).not.toBeNull();
    expect(store.get(`ls-reminder-prefs-${STU}`)).toBeNull();
  });

  it('never reads or migrates a legacy private reminder namespace', () => {
    const store = new InMemoryKvStore();
    const service = new ReminderPrefService(store);
    const saved = service.savePref(STU, STU, base, now);
    expect(saved.ok).toBe(true);
    const currentKey = `nyayone.student.reminder-prefs.v1.${STU}`;
    store.set(`ls-reminder-prefs-${STU}`, store.get(currentKey));
    store.remove(currentKey);

    expect(new ReminderPrefService(store).read(STU, STU)).toBeNull();
    expect(store.get(currentKey)).toBeNull();
  });

  it('TC-290-01: new user gets safe defaults; returning user gets saved prefs', () => {
    const s = svc();
    const fresh = s.load(STU);
    expect(fresh.prefs.length).toBe(7); // one per calendar source
    expect(fresh.prefs.every((p) => p.channel === 'in_app' && p.enabled)).toBe(true);
    expect(fresh.updatedAt).toBe(''); // defaults are not yet persisted
    s.savePref(STU, STU, { ...base, sourceType: 'internship', leadMinutes: 60 }, now);
    const returning = s.load(STU);
    expect(returning.updatedAt).toBe(now);
    expect(returning.prefs.find((p) => p.sourceType === 'internship')!.leadMinutes).toBe(60);
  });

  it('TC-290-02: enable/disable a reminder type and persist after refresh', () => {
    const store = new InMemoryKvStore();
    new ReminderPrefService(store).savePref(STU, STU, { ...base, enabled: false }, now);
    // fresh service on the same store = reload/refresh
    const reloaded = new ReminderPrefService(store).read(STU, STU)!;
    expect(reloaded.prefs.find((p) => p.sourceType === 'exam' && p.channel === 'in_app')!.enabled).toBe(false);
  });

  it('TC-290-03: validate lead-time, quiet-hour and timezone boundaries', () => {
    expect(validatePref(base)).toBeNull();
    expect(validatePref({ ...base, leadMinutes: 45 })).toBe('lead_time'); // not an allowed lead
    expect(validatePref({ ...base, quietStartMin: 1440 })).toBe('quiet_range');
    expect(validatePref({ ...base, quietEndMin: -1 })).toBe('quiet_range');
    expect(validatePref({ ...base, timezone: 'Mars/Phobos' })).toBe('timezone');
    expect(validatePref({ ...base, channel: 'carrier_pigeon' as never })).toBe('channel');
    expect(validatePref({ ...base, sourceType: 'nope' as never })).toBe('source');
    expect(REMINDER_LEAD_MINUTES).toContain(30);
    expect(isValidTimezone('Asia/Kolkata')).toBe(true);
    expect(isValidTimezone('America/New_York')).toBe(true); // DST-capable zone
  });

  it('TC-290-04: repeated save is idempotent — no duplicate source+channel row', () => {
    const s = svc();
    s.savePref(STU, STU, base, now);
    s.savePref(STU, STU, { ...base, leadMinutes: 60 }, now);
    const state = s.read(STU, STU)!;
    const rows = state.prefs.filter((p) => p.sourceType === 'exam' && p.channel === 'in_app');
    expect(rows.length).toBe(1);
    expect(rows[0].leadMinutes).toBe(60); // last write wins, single row
  });

  it('TC-290-05: opt-out suppresses preview/scheduling eligibility', () => {
    const s = svc();
    const on = s.savePref(STU, STU, base, now);
    expect(on.ok && s.isPreviewEligible(on.state, 'exam', 'in_app')).toBe(true);
    const off = s.savePref(STU, STU, { ...base, enabled: false }, now);
    expect(off.ok && s.isPreviewEligible(off.state, 'exam', 'in_app')).toBe(false);
  });

  it('TC-290-06: previews expose no sensitive event detail or private identifier', () => {
    expect(maskedPreview({ title: 'Public AMA', privacyClassification: 'public' }, 'Community')).toBe('Community: Public AMA');
    const priv = maskedPreview({ title: 'Therapy session with Dr X', privacyClassification: 'personal' }, 'Clinical hours');
    expect(priv).not.toContain('Therapy');
    expect(priv).not.toContain('Dr X');
    const restricted = maskedPreview({ title: 'Harassment report follow-up', privacyClassification: 'restricted' }, 'Internships');
    expect(restricted).not.toContain('Harassment');
    expect(restricted).toBe('Internships: You have an upcoming item');
  });

  it('TC-290-07: cross-user read/write is refused without leaking existence', () => {
    const s = svc();
    s.savePref(STU, STU, base, now);
    expect(s.read(STU, 'stu-2')).toBeNull(); // attacker read → null, not the data
    const w = s.savePref(STU, 'stu-2', base, now); // attacker write
    expect(w).toEqual({ ok: false, reason: 'forbidden' });
  });

  it('defaults cover every source type once', () => {
    const d = defaultPrefs();
    expect(new Set(d.map((p) => p.sourceType)).size).toBe(7);
  });
});
