import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { NyayOneRevLIcon } from './NyayOneRevLIcon';

export type NyayOneSelectorKind = 'persona' | 'language';

export type NyayOneSelectorOption = Readonly<{
  value: string;
  enabled: boolean;
  selected: boolean;
  status: 'Available' | 'Coming soon';
}>;

export const NYAYONE_PERSONA_OPTIONS: readonly NyayOneSelectorOption[] = Object.freeze([
  Object.freeze({ value: 'Lawyer', enabled: false, selected: false, status: 'Coming soon' }),
  Object.freeze({ value: 'Student', enabled: true, selected: true, status: 'Available' }),
  Object.freeze({ value: 'Customer', enabled: false, selected: false, status: 'Coming soon' }),
  Object.freeze({ value: 'University', enabled: false, selected: false, status: 'Coming soon' }),
]);

export const NYAYONE_LANGUAGE_OPTIONS: readonly NyayOneSelectorOption[] = Object.freeze([
  Object.freeze({ value: 'English', enabled: true, selected: true, status: 'Available' }),
  Object.freeze({ value: 'हिन्दी', enabled: false, selected: false, status: 'Coming soon' }),
  Object.freeze({ value: 'ಕನ್ನಡ', enabled: false, selected: false, status: 'Coming soon' }),
]);

const OPTIONS_BY_KIND: Readonly<Record<NyayOneSelectorKind, readonly NyayOneSelectorOption[]>> = {
  persona: NYAYONE_PERSONA_OPTIONS,
  language: NYAYONE_LANGUAGE_OPTIONS,
};

export type NyayOneSelectorState = Readonly<{
  openKind: NyayOneSelectorKind | null;
  activeIndex: number;
}>;

export type NyayOneSelectorAction =
  | Readonly<{
      type: 'open';
      kind: NyayOneSelectorKind;
      edge: 'selected' | 'first' | 'last';
    }>
  | Readonly<{ type: 'move'; delta: -1 | 1 }>
  | Readonly<{ type: 'home' }>
  | Readonly<{ type: 'end' }>
  | Readonly<{ type: 'close'; restoreFocus?: boolean }>
  | Readonly<{ type: 'activate' }>;

export function createNyayOneSelectorState(): NyayOneSelectorState {
  return { openKind: null, activeIndex: 0 };
}

function selectedIndexFor(kind: NyayOneSelectorKind): number {
  const selectedIndex = OPTIONS_BY_KIND[kind].findIndex((option) => option.selected);
  return selectedIndex < 0 ? 0 : selectedIndex;
}

export function reduceNyayOneSelectorState(
  state: NyayOneSelectorState,
  action: NyayOneSelectorAction,
): NyayOneSelectorState {
  if (action.type === 'open') {
    const options = OPTIONS_BY_KIND[action.kind];
    const activeIndex = action.edge === 'first'
      ? 0
      : action.edge === 'last'
        ? options.length - 1
        : selectedIndexFor(action.kind);
    return { openKind: action.kind, activeIndex };
  }

  if (action.type === 'close') {
    return state.openKind === null ? state : { ...state, openKind: null };
  }

  if (state.openKind === null || action.type === 'activate') {
    return state;
  }

  const optionCount = OPTIONS_BY_KIND[state.openKind].length;
  if (action.type === 'move') {
    return {
      ...state,
      activeIndex: (state.activeIndex + action.delta + optionCount) % optionCount,
    };
  }
  if (action.type === 'home') {
    return { ...state, activeIndex: 0 };
  }
  if (action.type === 'end') {
    return { ...state, activeIndex: optionCount - 1 };
  }
  return state;
}

export type NyayOneTriggerKeyAction = Readonly<{
  type: 'open';
  edge: 'selected' | 'first' | 'last';
}>;

export function getTriggerKeyAction(key: string): NyayOneTriggerKeyAction | null {
  if (key === 'Enter' || key === ' ') {
    return { type: 'open', edge: 'selected' };
  }
  if (key === 'ArrowDown') {
    return { type: 'open', edge: 'first' };
  }
  if (key === 'ArrowUp') {
    return { type: 'open', edge: 'last' };
  }
  return null;
}

export type NyayOneListboxKeyAction =
  | Readonly<{ type: 'move'; delta: -1 | 1 }>
  | Readonly<{ type: 'home' | 'end' | 'activate' }>
  | Readonly<{ type: 'close'; restoreFocus: boolean }>;

export function getListboxKeyAction(key: string): NyayOneListboxKeyAction | null {
  switch (key) {
    case 'ArrowDown':
      return { type: 'move', delta: 1 };
    case 'ArrowUp':
      return { type: 'move', delta: -1 };
    case 'Home':
      return { type: 'home' };
    case 'End':
      return { type: 'end' };
    case 'Enter':
    case ' ':
      return { type: 'activate' };
    case 'Escape':
      return { type: 'close', restoreFocus: true };
    case 'Tab':
      return { type: 'close', restoreFocus: false };
    default:
      return null;
  }
}

export type NyayOneSelectorActivation = Readonly<{
  enabled: boolean;
  close: boolean;
  announcement: string;
}>;

export function getNyayOneSelectorActivation(
  kind: NyayOneSelectorKind,
  optionIndex: number,
): NyayOneSelectorActivation {
  const option = OPTIONS_BY_KIND[kind][optionIndex];
  if (!option) {
    return { enabled: false, close: false, announcement: 'That option is unavailable.' };
  }
  if (!option.enabled) {
    return {
      enabled: false,
      close: false,
      announcement: `${option.value} is coming soon.`,
    };
  }
  return {
    enabled: true,
    close: true,
    announcement: `${option.value} selected. Available.`,
  };
}

export type NyayOneAuthSelectorsProps = Readonly<{
  showPersona?: boolean;
  showLanguage?: boolean;
  compact?: boolean;
  className?: string;
}>;

export function NyayOneAuthSelectors({
  showPersona = true,
  showLanguage = true,
  compact = false,
  className = '',
}: NyayOneAuthSelectorsProps) {
  const idPrefix = useId().replace(/:/g, '');
  const rootRef = useRef<HTMLDivElement>(null);
  const personaTriggerRef = useRef<HTMLButtonElement>(null);
  const languageTriggerRef = useRef<HTMLButtonElement>(null);
  const personaListboxRef = useRef<HTMLDivElement>(null);
  const languageListboxRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<NyayOneSelectorState>(createNyayOneSelectorState);
  const [announcement, setAnnouncement] = useState('');

  useEffect(() => {
    if (state.openKind === 'persona') {
      personaListboxRef.current?.focus();
    } else if (state.openKind === 'language') {
      languageListboxRef.current?.focus();
    }
  }, [state.openKind]);

  useEffect(() => {
    if (state.openKind === null) {
      return undefined;
    }
    const handleOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setState((current) => reduceNyayOneSelectorState(current, { type: 'close' }));
      }
    };
    document.addEventListener('pointerdown', handleOutsidePointer);
    return () => document.removeEventListener('pointerdown', handleOutsidePointer);
  }, [state.openKind]);

  const focusTrigger = (kind: NyayOneSelectorKind) => {
    if (kind === 'persona') {
      personaTriggerRef.current?.focus();
    } else {
      languageTriggerRef.current?.focus();
    }
  };

  const closeListbox = (restoreFocus: boolean) => {
    const closingKind = state.openKind;
    setState((current) => reduceNyayOneSelectorState(current, { type: 'close' }));
    if (restoreFocus && closingKind !== null) {
      focusTrigger(closingKind);
    }
  };

  const openListbox = (
    kind: NyayOneSelectorKind,
    edge: NyayOneTriggerKeyAction['edge'] = 'selected',
  ) => {
    setState((current) => reduceNyayOneSelectorState(current, { type: 'open', kind, edge }));
  };

  const activateOption = (kind: NyayOneSelectorKind, optionIndex: number) => {
    const activation = getNyayOneSelectorActivation(kind, optionIndex);
    setAnnouncement(activation.announcement);
    if (activation.close) {
      setState((current) => reduceNyayOneSelectorState(current, { type: 'close' }));
      focusTrigger(kind);
    }
  };

  const handleTriggerKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    kind: NyayOneSelectorKind,
  ) => {
    if (event.key === 'Escape' && state.openKind === kind) {
      event.preventDefault();
      closeListbox(true);
      return;
    }
    const action = getTriggerKeyAction(event.key);
    if (action === null) {
      return;
    }
    event.preventDefault();
    openListbox(kind, action.edge);
  };

  const handleListboxKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const action = getListboxKeyAction(event.key);
    if (action === null || state.openKind === null) {
      return;
    }
    if (action.type === 'close') {
      if (event.key !== 'Tab') {
        event.preventDefault();
      }
      closeListbox(action.restoreFocus);
      return;
    }
    event.preventDefault();
    if (action.type === 'activate') {
      activateOption(state.openKind, state.activeIndex);
      return;
    }
    setState((current) => reduceNyayOneSelectorState(current, action));
  };

  const handleOptionPointerMove = (
    event: ReactPointerEvent<HTMLDivElement>,
    kind: NyayOneSelectorKind,
    optionIndex: number,
  ) => {
    if (event.pointerType === 'touch' || state.openKind !== kind) {
      return;
    }
    setState((current) => ({ ...current, activeIndex: optionIndex }));
  };

  const renderSelector = (kind: NyayOneSelectorKind) => {
    const options = OPTIONS_BY_KIND[kind];
    const isOpen = state.openKind === kind;
    const selectedOption = options[selectedIndexFor(kind)];
    const label = kind === 'persona' ? 'I’m joining as' : 'Language';
    const triggerId = `${idPrefix}-${kind}-trigger`;
    const labelId = `${idPrefix}-${kind}-label`;
    const listboxId = `${idPrefix}-${kind}-listbox`;
    const activeOptionId = `${idPrefix}-${kind}-option-${state.activeIndex}`;
    const triggerRef = kind === 'persona' ? personaTriggerRef : languageTriggerRef;
    const listboxRef = kind === 'persona' ? personaListboxRef : languageListboxRef;
    const triggerContractAttributes = kind === 'persona'
      ? { 'data-nyayone-persona-trigger': '' }
      : { 'data-nyayone-language-trigger': '' };

    return (
      <div
        className={`nyayone-selector-field${compact ? ' nyayone-selector-field--compact' : ''}`}
        data-nyayone-selector={kind}
        key={kind}
      >
        <span className="nyayone-selector-label" id={labelId}>{label}</span>
        <div className={`nyayone-selector${isOpen ? ' is-open' : ''}`}>
          <button
            {...triggerContractAttributes}
            ref={triggerRef}
            className="nyayone-selector__trigger"
            id={triggerId}
            type="button"
            aria-haspopup="listbox"
            aria-expanded={isOpen}
            aria-controls={listboxId}
            aria-labelledby={`${labelId} ${triggerId}`}
            onClick={() => {
              if (isOpen) {
                closeListbox(true);
              } else {
                openListbox(kind);
              }
            }}
            onKeyDown={(event) => handleTriggerKeyDown(event, kind)}
          >
            <span className={kind === 'persona' ? 'v321-icon--indigo' : 'v321-icon--teal'}>
              <NyayOneRevLIcon name={kind === 'persona' ? 'users' : 'globe'} framed={false}/>
            </span>
            <span className="nyayone-selector__value">{selectedOption.value}</span>
            <span className="nyayone-selector__chevron" aria-hidden="true">▾</span>
          </button>
          <div
            ref={listboxRef}
            className="nyayone-selector__listbox"
            id={listboxId}
            role="listbox"
            tabIndex={-1}
            hidden={!isOpen}
            aria-labelledby={labelId}
            aria-activedescendant={isOpen ? activeOptionId : undefined}
            onKeyDown={handleListboxKeyDown}
          >
            {options.map((option, optionIndex) => {
              const isActive = isOpen && state.activeIndex === optionIndex;
              const optionContractAttributes = kind === 'persona'
                ? {
                    'data-nyayone-persona-option': '',
                    'data-nyayone-value': option.value,
                  }
                : {
                    'data-nyayone-language-option': '',
                    'data-nyayone-value': option.value,
                  };
              return (
                <div
                  {...optionContractAttributes}
                  className={[
                    'nyayone-selector__option',
                    isActive ? 'is-active' : '',
                    option.selected ? 'is-selected' : '',
                    option.enabled ? '' : 'is-disabled',
                  ].filter(Boolean).join(' ')}
                  id={`${idPrefix}-${kind}-option-${optionIndex}`}
                  key={option.value}
                  role="option"
                  aria-selected={option.selected}
                  aria-disabled={!option.enabled}
                  onClick={() => activateOption(kind, optionIndex)}
                  onPointerMove={(event) => handleOptionPointerMove(event, kind, optionIndex)}
                >
                  <span className="nyayone-selector__option-value">{option.value}</span>
                  {' '}
                  <span
                    className={`nyayone-selector__status nyayone-selector__status--${option.enabled ? 'available' : 'coming-soon'}`}
                  >
                    {option.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div
      ref={rootRef}
      className={`nyayone-selector-group${className ? ` ${className}` : ''}`}
      role="group"
      aria-label="Sign-in preferences"
    >
      {showPersona ? renderSelector('persona') : null}
      {showLanguage ? renderSelector('language') : null}
      <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcement}
      </span>
    </div>
  );
}
