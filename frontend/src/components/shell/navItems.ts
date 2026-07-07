/**
 * Navigation config for the Option J shell (SAATHI-343).
 * Rail = full desktop nav; bottomNav = the 5 mobile primaries + central Ask.
 * `to` points at canonical v3.2 screen routes (registry preserved).
 */
export interface NavItem {
  id: string;
  label: string;
  to: string;
  glyph: string; // simple text glyph (no emoji-as-icon)
}

export const railItems: NavItem[] = [
  { id: 'home', label: 'Home', to: '/s-13', glyph: '◱' },
  { id: 'research', label: 'AI Research', to: '/s-36', glyph: '⌕' },
  { id: 'internships', label: 'Internships', to: '/s-20', glyph: '▤' },
  { id: 'tutors', label: 'Find a Tutor', to: '/s-31', glyph: '◈' },
  { id: 'schools', label: 'Law Schools', to: '/s-27', glyph: '⌂' },
  { id: 'moot', label: 'Moot Court', to: '/s-41', glyph: '§' },
  { id: 'digests', label: 'Case Digests', to: '/s-46', glyph: '▭' },
  { id: 'exam', label: 'Exam Prep', to: '/s-55', glyph: '✎' },
  { id: 'clinical', label: 'Clinical Hours', to: '/s-61', glyph: '◷' },
  { id: 'calendar', label: 'Calendar', to: '/s-90', glyph: '◲' },
  { id: 'community', label: 'Community', to: '/s-50', glyph: '◌' },
  { id: 'profile', label: 'Profile', to: '/s-14', glyph: '◐' },
];

// Mobile bottom nav: 5 primaries; Ask is the central action.
export const bottomNavItems: NavItem[] = [
  { id: 'home', label: 'Home', to: '/s-13', glyph: '◱' },
  { id: 'research', label: 'Research', to: '/s-36', glyph: '⌕' },
  { id: 'internships', label: 'Internships', to: '/s-20', glyph: '▤' },
  { id: 'tutors', label: 'Tutors', to: '/s-31', glyph: '◈' },
  { id: 'profile', label: 'Profile', to: '/s-14', glyph: '◐' },
];

/**
 * Split the bottom-nav items around the central Ask action WITHOUT dropping any
 * item. Left gets the first half, right gets the remainder — so every configured
 * item always renders. (Guards the SAATHI-374 regression where index 4 was lost.)
 */
export function splitBottomNav(items: NavItem[] = bottomNavItems): { left: NavItem[]; right: NavItem[] } {
  const mid = Math.ceil(items.length / 2);
  return { left: items.slice(0, mid), right: items.slice(mid) };
}
