import { useParams } from 'react-router-dom';

interface ScreenPlaceholderProps {
  /** Canonical v3.2 screen ID (S-01 … S-99) supplied by the route registry. */
  id?: string;
}

/**
 * Foundation placeholder for a canonical screen ID (S-01 … S-99).
 * Real screens are implemented per release tranche in later tickets.
 */
export default function ScreenPlaceholder({ id }: ScreenPlaceholderProps) {
  const params = useParams();
  const screenId = id ?? params.screenId ?? 'S-??';
  return (
    <section className="screen-placeholder">
      <p className="eyebrow">LegalSaathi · Student</p>
      <h1>{screenId.toUpperCase()}</h1>
      <p>Foundation placeholder. This screen will be implemented in a later release tranche.</p>
    </section>
  );
}
