import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  NYAYONE_LANGUAGE_OPTIONS,
  NYAYONE_PERSONA_OPTIONS,
  NyayOneAuthSelectors,
  createNyayOneSelectorState,
  getListboxKeyAction,
  getNyayOneSelectorActivation,
  getTriggerKeyAction,
  reduceNyayOneSelectorState,
} from './NyayOneAuthSelectors';

describe('NYAY-7 auth selector option contract', () => {
  it('keeps the approved persona choices, order, availability and selection exact', () => {
    expect(NYAYONE_PERSONA_OPTIONS).toEqual([
      { value: 'Lawyer', enabled: false, selected: false, status: 'Coming soon' },
      { value: 'Student', enabled: true, selected: true, status: 'Available' },
      { value: 'Customer', enabled: false, selected: false, status: 'Coming soon' },
      { value: 'University', enabled: false, selected: false, status: 'Coming soon' },
    ]);
  });

  it('keeps the approved language choices, order, availability and selection exact', () => {
    expect(NYAYONE_LANGUAGE_OPTIONS).toEqual([
      { value: 'English', enabled: true, selected: true, status: 'Available' },
      { value: 'हिन्दी', enabled: false, selected: false, status: 'Coming soon' },
      { value: 'ಕನ್ನಡ', enabled: false, selected: false, status: 'Coming soon' },
    ]);
  });

  it('renders labelled listboxes and the exact browser-contract attributes', () => {
    const html = renderToStaticMarkup(<NyayOneAuthSelectors />);

    expect(html).toContain('data-nyayone-persona-trigger=""');
    expect(html).toContain('data-nyayone-language-trigger=""');
    expect(html).toContain('aria-haspopup="listbox"');
    expect(html).toContain('aria-expanded="false"');
    expect(html.match(/role="listbox"/g)).toHaveLength(2);
    expect(html.match(/role="option"/g)).toHaveLength(7);
    expect(html).toContain('data-nyayone-persona-option="" data-nyayone-value="Lawyer"');
    expect(html).toContain('data-nyayone-persona-option="" data-nyayone-value="Student"');
    expect(html).toContain('data-nyayone-language-option="" data-nyayone-value="English"');
    expect(html).toContain('data-nyayone-language-option="" data-nyayone-value="हिन्दी"');
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain('Student');
    expect(html).toContain('English');
  });
});

describe('NYAY-7 auth selector state machine', () => {
  it('opens on the selected value, changes the active option, and closes the other selector', () => {
    const initial = createNyayOneSelectorState();
    const personaOpen = reduceNyayOneSelectorState(initial, {
      type: 'open',
      kind: 'persona',
      edge: 'selected',
    });
    expect(personaOpen).toMatchObject({ openKind: 'persona', activeIndex: 1 });

    const customerActive = reduceNyayOneSelectorState(personaOpen, { type: 'move', delta: 1 });
    expect(customerActive).toMatchObject({ openKind: 'persona', activeIndex: 2 });

    const languageOpen = reduceNyayOneSelectorState(customerActive, {
      type: 'open',
      kind: 'language',
      edge: 'selected',
    });
    expect(languageOpen).toMatchObject({ openKind: 'language', activeIndex: 0 });
  });

  it('supports wrapping arrows plus Home and End without skipping disabled options', () => {
    let state = reduceNyayOneSelectorState(createNyayOneSelectorState(), {
      type: 'open',
      kind: 'persona',
      edge: 'first',
    });
    state = reduceNyayOneSelectorState(state, { type: 'move', delta: -1 });
    expect(state.activeIndex).toBe(3);
    state = reduceNyayOneSelectorState(state, { type: 'move', delta: 1 });
    expect(state.activeIndex).toBe(0);
    state = reduceNyayOneSelectorState(state, { type: 'end' });
    expect(state.activeIndex).toBe(3);
    state = reduceNyayOneSelectorState(state, { type: 'home' });
    expect(state.activeIndex).toBe(0);
  });

  it('maps the complete trigger and listbox keyboard contract', () => {
    expect(getTriggerKeyAction('Enter')).toEqual({ type: 'open', edge: 'selected' });
    expect(getTriggerKeyAction(' ')).toEqual({ type: 'open', edge: 'selected' });
    expect(getTriggerKeyAction('ArrowDown')).toEqual({ type: 'open', edge: 'first' });
    expect(getTriggerKeyAction('ArrowUp')).toEqual({ type: 'open', edge: 'last' });
    expect(getTriggerKeyAction('Tab')).toBeNull();

    expect(getListboxKeyAction('ArrowDown')).toEqual({ type: 'move', delta: 1 });
    expect(getListboxKeyAction('ArrowUp')).toEqual({ type: 'move', delta: -1 });
    expect(getListboxKeyAction('Home')).toEqual({ type: 'home' });
    expect(getListboxKeyAction('End')).toEqual({ type: 'end' });
    expect(getListboxKeyAction('Enter')).toEqual({ type: 'activate' });
    expect(getListboxKeyAction(' ')).toEqual({ type: 'activate' });
    expect(getListboxKeyAction('Escape')).toEqual({ type: 'close', restoreFocus: true });
    expect(getListboxKeyAction('Tab')).toEqual({ type: 'close', restoreFocus: false });
    expect(getListboxKeyAction('x')).toBeNull();
  });

  it('leaves disabled choices inert while reporting their availability', () => {
    expect(getNyayOneSelectorActivation('persona', 0)).toEqual({
      enabled: false,
      close: false,
      announcement: 'Lawyer is coming soon.',
    });
    expect(getNyayOneSelectorActivation('persona', 1)).toEqual({
      enabled: true,
      close: true,
      announcement: 'Student selected. Available.',
    });
    expect(getNyayOneSelectorActivation('language', 1)).toEqual({
      enabled: false,
      close: false,
      announcement: 'हिन्दी is coming soon.',
    });
  });
});

describe('NYAY-7 auth selector browser safety contract', () => {
  it('uses document-scoped outside-click cleanup and focus restoration without persistence', () => {
    const source = readFileSync(new URL('./NyayOneAuthSelectors.tsx', import.meta.url), 'utf8');

    expect(source).toContain("document.addEventListener('pointerdown'");
    expect(source).toContain("document.removeEventListener('pointerdown'");
    expect(source).toContain('.focus()');
    expect(source).toContain('aria-activedescendant');
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/);
  });
});
