import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProfileSetupFrame } from './ProfileScreens';

const source = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('NYAY-58 S-11 Revision L presentation', () => {
  it('renders the third-step shell with the approved heading and real identity', () => {
    const markup = renderToStaticMarkup(createElement(MemoryRouter, null,
      createElement(ProfileSetupFrame, {
        step: 3, firstName: 'Synthetic', middleName: null, lastName: 'Student',
        children: createElement('select', { id: 'preserved-goal-control' }),
      })));
    expect(markup).toContain('data-screen="S-11"');
    expect(markup).toContain('aria-labelledby="S-11-title"');
    expect(markup).toContain('id="S-11-title"');
    expect(markup).toContain('What are you here for?');
    expect(markup).toContain('Profile · step 3 of 3');
    expect(markup.match(/class="is-current"/gu)).toHaveLength(3);
    expect(markup).toContain('v321-profile__heading-icon--interests');
    expect(markup).toContain('Your Profile · Synthetic Student');
    expect(markup).toContain('id="preserved-goal-control"');
    expect(markup).not.toMatch(/Aditi|Nair|data-screen="S-10"/u);
  });

  it('keeps selection and completion server-backed rather than copying prototype defaults', () => {
    const text = source('src/features/student/profile/ProfileScreens.tsx');
    const form = text.slice(text.indexOf('export function ProfileStep3'), text.indexOf('export function ProfileDone'));
    expect(form).toContain('<ProfileSetupFrame step={3}');
    expect(form).toContain('Practice Interests');
    expect(form).toContain('Pick any. These tune your matches and are easy to change later.');
    expect(form).toContain('className="v321-profile__interest"');
    expect(form).toContain('aria-pressed={interests.includes(interest)}');
    expect(form).toContain('setInterests(values.interests)');
    expect(form).toContain('setGoal(values.goals[0]');
    expect(form).toContain('options={GOALS}');
    expect(form).toContain('expectedProfileVersion: hydratedVersion');
    expect(form).toContain('goals: [goal]');
    expect(form).toContain('profileSaveDestination');
    expect(form).toContain("persist('exit')");
    expect(form).toContain("persist('done')");
    expect(form).toContain('Save and exit');
    expect(form).toContain('Finish setup');
    expect(form).toContain('<Progress projection={query.data} />');
    expect(form).toContain('<ProfileConflictReview');
    expect(form).toContain('<ReauthDraftRestored');
    expect(form).toContain('<ErrorSummary');
    expect(form.match(/disabled=\{save\.isPending \|\| Boolean\(conflictReview\.conflict\)\}/gu)).toHaveLength(2);
    expect(form).not.toMatch(/useState\(\['Constitutional'|Internships|Moot Court|Judiciary Prep/u);
  });

  it('scopes the interest chip, font and label geometry to S-11', () => {
    const css = source('src/styles/student-option321.css');
    for (const selector of [
      ".v321-profile[data-screen='S-11'] .v321-profile__interest",
      ".v321-profile[data-screen='S-11'] .v321-profile__interest[aria-pressed='true']",
      ".v321-profile[data-screen='S-11'] .v321-profile__interest-label",
      ".ls-v34-content .v321-profile[data-screen='S-11'] :is(h1, h2)",
    ]) expect(css).toContain(selector);
    const chip = css.slice(css.indexOf(".v321-profile[data-screen='S-11'] .v321-profile__interest {")).split('}')[0];
    expect(chip).toContain('min-height: 44px');
    expect(chip).toContain('border-radius: 22px');
    expect(chip).toContain('padding: 0 14px');
  });

  it('lets only S-11 own its new shell without wrapping it in the legacy navigation', () => {
    const text = source('src/components/shell/AppShell.tsx');
    expect(text).toContain("if (location.pathname === '/s-11')");
    const rule = text.slice(text.indexOf("if (location.pathname === '/s-11')")).split('}')[0];
    expect(rule).toContain('<main className="ls-v34-content" id="main-content">');
    expect(text.indexOf("if (location.pathname === '/s-11')")).toBeLessThan(text.indexOf('<V34ContinuationShell'));
  });

  it('matches the Revision L normal interest-label baseline without changing S-10 labels', () => {
    const css = source('src/styles/student-option321.css');
    const selector = ".v321-profile[data-screen='S-11'] .v321-profile__interest-label {";
    const rule = css.slice(css.indexOf(selector)).split('}')[0];
    expect(rule).toContain('line-height: normal');
    expect(source('src/features/student/profile/ProfileScreens.tsx')).toContain('<span aria-hidden="true"><span className="v321-profile__label-icon"><ProfileSetupIcon name="spark" /></span></span>Practice Interests');
  });

  it('preserves the Revision L 20px icon wrapper and centered 18px drawing for the interest label', () => {
    const css = source('src/styles/student-option321.css');
    const selector = ".v321-profile[data-screen='S-11'] .v321-profile__label-icon {";
    expect(css).toContain(selector);
    const rule = css.slice(css.indexOf(selector)).split('}')[0];
    for (const declaration of ['display: inline-flex', 'width: 20px', 'height: 20px', 'align-items: center', 'justify-content: center']) expect(rule).toContain(declaration);
  });

  it('uses the prototype 1.55 line height only for S-11 desktop guidance', () => {
    const css = source('src/styles/student-option321.css');
    const selector = ".v321-profile[data-screen='S-11'] .v321-profile__card p";
    expect(css).toContain(selector);
    expect(css.slice(css.indexOf(selector)).split('}')[0]).toContain('line-height: 1.55');
  });
});
