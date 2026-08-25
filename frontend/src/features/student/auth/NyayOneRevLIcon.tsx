export type NyayOneRevLIconName =
  | 'badge'
  | 'checkc'
  | 'globe'
  | 'home'
  | 'idcard'
  | 'otp'
  | 'pen'
  | 'refresh'
  | 'send'
  | 'shield'
  | 'sim'
  | 'userplus'
  | 'users';

type IconProps = Readonly<{
  name: NyayOneRevLIconName;
  framed?: boolean;
  className?: string;
}>;

/** Exact 18px Revision L vector primitives from the sealed Option 3.2.1 source. */
export function NyayOneRevLIcon({ name, framed = true, className = '' }: IconProps) {
  const paths = (
    <>
      {name === 'sim' && <><rect x="7" y="3" width="10" height="18" rx="2.5" fill="currentColor" opacity=".16"/><rect x="7" y="3" width="10" height="18" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M10.5 17.5h3" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}
      {name === 'otp' && <><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" fill="currentColor" opacity=".14"/><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><rect x="9.4" y="10.2" width="5.2" height="4.6" rx="1.1" fill="currentColor"/><path d="M10.6 10.2V9a1.4 1.4 0 0 1 2.8 0v1.2" fill="none" stroke="currentColor" strokeWidth="1.5"/></>}
      {name === 'userplus' && <><circle cx="10" cy="8.5" r="3.6" fill="currentColor" opacity=".16"/><circle cx="10" cy="8.5" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M4 19.5a6 6 0 0 1 12 0M18 8v6M15 11h6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}
      {name === 'badge' && <><path d="M12 2.8l2.3 1.6 2.8-.3 1 2.6 2.6 1-.3 2.8 1.6 2.3-1.6 2.3.3 2.8-2.6 1-1 2.6-2.8-.3-2.3 1.6-2.3-1.6-2.8.3-1-2.6-2.6-1 .3-2.8L2.8 12l1.6-2.3-.3-2.8 2.6-1 1-2.6 2.8.3z" fill="currentColor" opacity=".16"/><path d="m8.6 12.2 2.3 2.3 4.5-4.7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'idcard' && <><rect x="3" y="5" width="18" height="14" rx="2.5" fill="currentColor" opacity=".14"/><rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><circle cx="8.6" cy="11" r="2" fill="currentColor"/><path d="M6 16c.5-1.6 1.5-2.4 2.6-2.4S10.7 14.4 11.2 16M14 9.5h5M14 12.5h5M14 15.5h3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></>}
      {name === 'users' && <><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/><circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M15.5 6.2a3.2 3.2 0 0 1 0 5.9M20.5 19a5.2 5.2 0 0 0-3.6-4.9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></>}
      {name === 'globe' && <><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M3.5 12h17M12 3.5c2.6 2.3 3.9 5.1 3.9 8.5s-1.3 6.2-3.9 8.5c-2.6-2.3-3.9-5.1-3.9-8.5s1.3-6.2 3.9-8.5z" fill="none" stroke="currentColor" strokeWidth="1.6"/></>}
      {name === 'send' && <><path d="M4 11 20 4l-4.5 16-4-6.5z" fill="currentColor" opacity=".16"/><path d="M4 11 20 4l-4.5 16-4-6.5zM11.5 13.5 20 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
      {name === 'pen' && <><path d="M4 20l4.2-1L19.5 7.7a2.1 2.1 0 0 0-3-3L5.2 16z" fill="currentColor" opacity=".14"/><path d="M4 20l4.2-1L19.5 7.7a2.1 2.1 0 0 0-3-3L5.2 16zM14 6.5l3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
      {name === 'refresh' && <><path d="M5 12a7 7 0 0 1 12-4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M17.6 3.8v4h-4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><path d="M19 12a7 7 0 0 1-12 4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M6.4 20.2v-4h4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".08"/></>}
      {name === 'checkc' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="m8 12.3 2.7 2.7 5.3-5.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'home' && <><path d="M4 11 12 4l8 7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><path d="M6 10v9.5h12V10" fill="currentColor" opacity=".14"/><path d="M6 10v9.5h12V10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/></>}
      {name === 'shield' && <path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>}
    </>
  );
  const svg = <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">{paths}</svg>;
  return framed
    ? <span className={`v321-revl-icon${className ? ` ${className}` : ''}`} aria-hidden="true">{svg}</span>
    : svg;
}

export function NyayOneRevLLockup({ reversed = false }: Readonly<{ reversed?: boolean }>) {
  const primary = reversed ? '#efedf6' : '#2e3a8c';
  const documentInk = reversed ? '#1c2454' : '#ffffff';
  const seal = reversed ? '#dfb458' : '#c89a3a';
  const wordmark = reversed ? '#efedf6' : '#14161a';
  const muted = reversed ? '#9aa0cc' : '#5c5f7a';
  return (
    <svg className="v321-lockup" viewBox="0 0 300 72" role="img" aria-label="NyayOne — Legal, on the record">
      <g transform="translate(4 4)">
        <circle cx="32" cy="32" r="30" fill="none" stroke={primary} strokeWidth="3"/>
        <circle cx="32" cy="32" r="26" fill="none" stroke={primary} strokeWidth="1.2" strokeDasharray="1.5 3.4" strokeLinecap="round"/>
        <rect x="18" y="15" width="22" height="30" rx="2.5" fill={primary}/>
        <rect x="22.5" y="21.5" width="13" height="2.2" rx="1.1" fill={documentInk}/>
        <rect x="22.5" y="26" width="13" height="2.2" rx="1.1" fill={documentInk}/>
        <rect x="22.5" y="30.5" width="8" height="2.2" rx="1.1" fill={documentInk}/>
        <circle cx="40.5" cy="41.5" r="10" fill={documentInk}/>
        <circle cx="40.5" cy="41.5" r="8.7" fill="none" stroke={primary} strokeWidth="2.1"/>
        <circle cx="40.5" cy="41.5" r="6.2" fill={seal}/>
        <circle cx="40.5" cy="41.5" r="2.2" fill={documentInk}/>
      </g>
      <text x="82" y="43" fontFamily="Spectral, Georgia, serif" fontSize="34" fontWeight="600" fill={wordmark}>Nyay<tspan fontWeight="300" fill={muted}>One</tspan></text>
      <text x="83" y="58" fontFamily="Space Grotesk, Helvetica, sans-serif" fontSize="9" fontWeight="600" letterSpacing="2" fill={muted}>LEGAL, ON THE RECORD</text>
    </svg>
  );
}
