# LegalSaathi registration data dictionary

Generated from the live `postgresql` schema. Alembic is the source of truth.

## `audit_events`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `actor_user_id` | `UUID` | Yes |
| `actor_role` | `VARCHAR(40)` | Yes |
| `action` | `VARCHAR(120)` | No |
| `resource_type` | `VARCHAR(80)` | No |
| `resource_id` | `UUID` | Yes |
| `before_state` | `JSON` | Yes |
| `after_state` | `JSON` | Yes |
| `ip_hash` | `VARCHAR(64)` | Yes |
| `user_agent_hash` | `VARCHAR(64)` | Yes |
| `created_at` | `TIMESTAMP` | No |

## `consents`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `registration_id` | `UUID` | No |
| `purpose` | `VARCHAR(64)` | No |
| `accepted` | `BOOLEAN` | No |
| `policy_version` | `VARCHAR(40)` | No |
| `accepted_at` | `TIMESTAMP` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |

## `guardian_consents`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `registration_id` | `UUID` | No |
| `status` | `VARCHAR(32)` | No |
| `verified` | `BOOLEAN` | No |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |

## `otp_challenges`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `registration_id` | `UUID` | No |
| `verifier_hash` | `VARCHAR(64)` | No |
| `attempts` | `INTEGER` | No |
| `max_attempts` | `INTEGER` | No |
| `expires_at` | `TIMESTAMP` | No |
| `consumed_at` | `TIMESTAMP` | Yes |
| `locked_until` | `TIMESTAMP` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |
| `purpose` | `VARCHAR(16)` | No |

## `otp_outbox`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `challenge_id` | `UUID` | No |
| `destination_ct` | `VARCHAR(600)` | No |
| `code_ct` | `VARCHAR(600)` | Yes |
| `key_version` | `VARCHAR(8)` | No |
| `purpose` | `VARCHAR(16)` | No |
| `status` | `VARCHAR(16)` | No |
| `attempts` | `INTEGER` | No |
| `last_error` | `VARCHAR(200)` | Yes |
| `delivered_at` | `TIMESTAMP` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |

## `recovery_sessions`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `opaque_id` | `VARCHAR(64)` | No |
| `lookup_hash` | `VARCHAR(64)` | No |
| `registration_id` | `UUID` | Yes |
| `challenge_id` | `UUID` | Yes |
| `status` | `VARCHAR(24)` | No |
| `expires_at` | `TIMESTAMP` | No |
| `consumed_at` | `TIMESTAMP` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |

## `student_profiles`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `registration_id` | `UUID` | No |
| `college` | `VARCHAR(160)` | Yes |
| `year_of_study` | `VARCHAR(40)` | Yes |
| `enrolment_ct` | `VARCHAR(600)` | Yes |
| `enrolment_hash` | `VARCHAR(64)` | Yes |
| `institutional_email_ct` | `VARCHAR(600)` | Yes |
| `institutional_email_hash` | `VARCHAR(64)` | Yes |
| `bar_enrolment_ct` | `VARCHAR(600)` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |
| `bar_enrolment_hash` | `VARCHAR(64)` | Yes |
| `key_version` | `VARCHAR(8)` | No |

## `student_registrations`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `user_id` | `UUID` | No |
| `first_name` | `VARCHAR(60)` | No |
| `middle_name` | `VARCHAR(60)` | Yes |
| `last_name` | `VARCHAR(60)` | No |
| `mobile_hash` | `VARCHAR(64)` | No |
| `mobile_ct` | `VARCHAR(600)` | No |
| `dob_ct` | `VARCHAR(600)` | No |
| `institution_ref` | `VARCHAR(120)` | Yes |
| `status` | `VARCHAR(32)` | No |
| `is_minor` | `BOOLEAN` | No |
| `idempotency_key` | `VARCHAR(200)` | Yes |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |
| `dob_hash` | `VARCHAR(64)` | No |
| `key_version` | `VARCHAR(8)` | No |

## `student_verifications`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `registration_id` | `UUID` | No |
| `method` | `VARCHAR(32)` | No |
| `status` | `VARCHAR(32)` | No |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |

## `users`

| Column | Type | Nullable |
|---|---|---|
| `id` | `UUID` | No |
| `role` | `VARCHAR(32)` | No |
| `status` | `VARCHAR(32)` | No |
| `created_at` | `TIMESTAMP` | No |
| `updated_at` | `TIMESTAMP` | No |
| `deleted_at` | `TIMESTAMP` | Yes |
| `metadata_json` | `JSON` | Yes |
