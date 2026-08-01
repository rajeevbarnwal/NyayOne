/** Redact media credentials and opaque negotiation payloads from runtime logs. */
export function redactMediaRuntimeMessage(value) {
  return String(value)
    .replace(
      /([?&](?:access_token|join_request)=)[^&\s'"`]+/gi,
      '$1[redacted]',
    )
    .replace(
      /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
      '[redacted-jwt]',
    );
}
