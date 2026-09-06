"""Documentation-only headers for authority-first runtime validation.

These factories supply OpenAPI metadata, never dependencies or validators.
Routes retain their existing runtime Header defaults/manual extraction so
authentication, ownership and governance checks keep their original precedence.
"""


def required_idempotency_header() -> dict:
    """Return a fresh required non-null header; family-specific rules stay local."""
    return {
        "parameters": [{
            "name": "Idempotency-Key",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Required for a successful mutation; validated by the operation after its authority checks.",
        }],
    }
