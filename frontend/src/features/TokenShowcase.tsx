import type { ThemeMode } from '../hooks/useTheme';

/**
 * Internal token/theme verification route (SAATHI-365). Not a product screen and
 * not part of the S-01..S-99 registry — a lightweight showcase to eyeball tokens,
 * both themes, typography, semantic status primitives, focus rings, and 44px targets.
 */
const SURFACES = ['--bg', '--surface', '--elevated', '--panel', '--accent', '--accent2'] as const;

interface TokenShowcaseProps {
  theme: ThemeMode;
  toggleTheme: () => void;
}

export default function TokenShowcase({ theme, toggleTheme }: TokenShowcaseProps) {
  return (
    <section style={{ width: 'min(100%, 900px)', padding: 'var(--space-5)' }}>
      <p className="eyebrow">NyayOne · Design tokens</p>
      <h1 style={{ fontFamily: 'var(--font-serif)' }}>Option J v3.2 token &amp; theme check</h1>
      <p style={{ color: 'var(--text3)' }}>
        Active theme: <strong>{theme === 'dark' ? 'Chambers Dark' : 'Clean Chambers Light'}</strong>
      </p>

      <button type="button" className="btn btn--primary tap" onClick={toggleTheme}>
        Toggle theme
      </button>

      <h2 style={{ fontFamily: 'var(--font-serif)', marginTop: 'var(--space-6)' }}>Surfaces &amp; accent</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
        {SURFACES.map((v) => (
          <div
            key={v}
            style={{
              width: 120,
              height: 64,
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--line)',
              background: `var(${v})`,
              display: 'flex',
              alignItems: 'flex-end',
              padding: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--fs-xs)',
              color: 'var(--text2)',
            }}
          >
            {v}
          </div>
        ))}
      </div>

      <h2 style={{ fontFamily: 'var(--font-serif)', marginTop: 'var(--space-6)' }}>Typography</h2>
      <p style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--fs-2xl)' }}>Newsreader — reading serif</p>
      <p style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--fs-lg)' }}>Hanken Grotesk — UI / body</p>
      <p style={{ fontFamily: 'var(--font-mono)' }}>JetBrains Mono — S-27 · ₹35,000 · IST</p>

      <h2 style={{ fontFamily: 'var(--font-serif)', marginTop: 'var(--space-6)' }}>Semantic status</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
        <span className="status status--ok">Verified</span>
        <span className="status status--warn">Under review</span>
        <span className="status status--risk">Action needed</span>
        <span className="status status--info">Info</span>
      </div>

      <h2 style={{ fontFamily: 'var(--font-serif)', marginTop: 'var(--space-6)' }}>Controls (44px min)</h2>
      <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
        <button type="button" className="btn tap">Secondary</button>
        <button type="button" className="btn btn--primary tap">Primary</button>
      </div>
    </section>
  );
}
