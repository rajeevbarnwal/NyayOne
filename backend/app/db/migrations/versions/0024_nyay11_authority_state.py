"""NYAY-11 closed guardian and institutional authority with audited legacy mapping."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op
revision = "0024_nyay11_authority_state"
down_revision = "0023_nyay22_mentor_ceremony"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('student_authority_states',
        sa.Column('registration_id', sa.Uuid(), sa.ForeignKey('student_registrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('guardian_state', sa.String(24), nullable=False),
        sa.Column('institutional_state', sa.String(24), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('guardian_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('guardian_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('guardian_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('guardian_dob_hash', sa.String(64), nullable=True),
        sa.Column('guardian_identity_hash', sa.String(64), nullable=True),
        sa.Column('relationship', sa.String(24), nullable=True),
        sa.Column('consent_version', sa.String(24), nullable=True),
        sa.Column('institutional_email_hash', sa.String(64), nullable=True),
        sa.Column('reviewer_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('institutional_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reproof_guardian', sa.Boolean(), nullable=False),
        sa.Column('reproof_institutional', sa.Boolean(), nullable=False),
        sa.Column('policy_version', sa.String(24), nullable=False),
        sa.CheckConstraint("guardian_state <> 'VERIFIED' OR (guardian_verified_at IS NOT NULL AND guardian_expires_at IS NOT NULL AND guardian_expires_at > guardian_verified_at AND guardian_dob_hash IS NOT NULL AND guardian_identity_hash IS NOT NULL AND length(guardian_identity_hash) = 64 AND relationship IS NOT NULL AND consent_version = 'guardian-consent.v1')", name=op.f('ck_student_authority_states_guardian_proof')),
        sa.CheckConstraint("guardian_state IN ('NOT_REQUIRED', 'REQUIRED_PENDING', 'VERIFIED', 'REJECTED', 'REVOKED')", name=op.f('ck_student_authority_states_guardian_state')),
        sa.CheckConstraint("institutional_state <> 'VERIFIED' OR (institutional_email_hash IS NOT NULL AND institutional_expires_at IS NOT NULL)", name=op.f('ck_student_authority_states_institutional_proof')),
        sa.CheckConstraint("institutional_state IN ('UNVERIFIED', 'PENDING', 'VERIFIED', 'REJECTED', 'EXPIRED', 'REVOKED')", name=op.f('ck_student_authority_states_institutional_state')),
        sa.CheckConstraint("policy_version = 'NYAY-11-v1'", name=op.f('ck_student_authority_states_policy_version')),
        sa.CheckConstraint("relationship IS NULL OR relationship IN ('parent', 'legal_guardian')", name=op.f('ck_student_authority_states_relationship')),
        sa.CheckConstraint('version >= 1', name=op.f('ck_student_authority_states_version')),
        sa.PrimaryKeyConstraint('registration_id', name='pk_student_authority_states'),
    )
    op.create_index('ix_student_authority_states_guardian_user_id', 'student_authority_states', ['guardian_user_id'], unique=False)
    op.create_index('ix_student_authority_states_reviewer_user_id', 'student_authority_states', ['reviewer_user_id'], unique=False)
    op.create_table('guardian_authority_invitations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('registration_id', sa.Uuid(), sa.ForeignKey('student_registrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('generation >= 1 AND length(token_hash) = 64', name=op.f('ck_guardian_authority_invitations_shape')),
        sa.CheckConstraint("state IN ('pending', 'consumed', 'revoked')", name=op.f('ck_guardian_authority_invitations_state')),
        sa.PrimaryKeyConstraint('id', name='pk_guardian_authority_invitations'),
        sa.UniqueConstraint('token_hash', name='uq_guardian_authority_invitations_token_hash'),
    )
    op.create_index('ix_guardian_authority_invitations_registration_id', 'guardian_authority_invitations', ['registration_id'], unique=False)
    op.create_table('institutional_authority_email_proofs',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email_hash', sa.String(64), nullable=False),
        sa.Column('institution', sa.String(120), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=True),
        sa.Column('provider_receipt_hash', sa.String(64), nullable=True),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state <> 'verified' OR code_hash IS NULL", name=op.f('ck_institutional_authority_email_proofs_consumed')),
        sa.CheckConstraint("state NOT IN ('active','verified') OR provider_receipt_hash IS NOT NULL", name=op.f('ck_institutional_authority_email_proofs_delivery')),
        sa.CheckConstraint('attempts BETWEEN 0 AND 5 AND length(email_hash) = 64', name=op.f('ck_institutional_authority_email_proofs_shape')),
        sa.CheckConstraint("state IN ('pending_delivery', 'active', 'verified', 'failed', 'revoked')", name=op.f('ck_institutional_authority_email_proofs_state')),
        sa.PrimaryKeyConstraint('user_id', name='pk_institutional_authority_email_proofs'),
    )
    op.create_table('institutional_reviewer_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('institution', sa.String(120), nullable=False),
        sa.Column('operation', sa.String(24), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("operation = 'review'", name=op.f('ck_institutional_reviewer_assignments_operation')),
        sa.PrimaryKeyConstraint('id', name='pk_institutional_reviewer_assignments'),
        sa.UniqueConstraint('user_id', 'institution', 'operation', name='uq_institutional_reviewer_assignments_user_id'),
    )
    op.create_table('student_authority_mutations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('registration_id', sa.Uuid(), sa.ForeignKey('student_registrations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation', sa.String(32), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('outcome_ct', sa.Text(), nullable=False),
        sa.CheckConstraint('length(key_hash) = 64 AND length(fingerprint) = 64', name=op.f('ck_student_authority_mutations_shape')),
        sa.PrimaryKeyConstraint('id', name='pk_student_authority_mutations'),
        sa.UniqueConstraint('actor_id', 'operation', 'key_hash', name='uq_student_authority_mutations_actor_id'),
    )
    op.create_index('ix_student_authority_mutations_registration_id', 'student_authority_mutations', ['registration_id'], unique=False)
    op.create_table('student_authority_audit_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('actor_class', sa.String(40), nullable=False),
        sa.Column('authority_class', sa.String(40), nullable=False),
        sa.Column('purpose_code', sa.String(24), nullable=False),
        sa.Column('transition_code', sa.String(100), nullable=False),
        sa.Column('policy_version', sa.String(24), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("actor_class IN ('student', 'guardian', 'owner', 'reviewer', 'admin', 'server')", name=op.f('ck_student_authority_audit_events_actor')),
        sa.CheckConstraint("authority_class IN ('student', 'guardian', 'owner', 'platform_owner', 'assigned_institutional_reviewer', 'admin', 'server', 'server_attested_guardian', 'server_age_policy', 'server_clock', 'server_profile_policy')", name=op.f('ck_student_authority_audit_events_authority')),
        sa.CheckConstraint("policy_version = 'NYAY-11-v1'", name=op.f('ck_student_authority_audit_events_policy')),
        sa.CheckConstraint("purpose_code IN ('guardian', 'institutional', 'legacy_mapping', 'identity')", name=op.f('ck_student_authority_audit_events_purpose')),
        sa.CheckConstraint("transition_code IN ('DEPENDENT_PROOF_INVALIDATED', 'EMAIL_PROOF_DENIED', 'EMAIL_PROOF_VERIFIED', 'EXPIRED_TO_PENDING', 'EXPIRED_TO_REJECTED', 'EXPIRED_TO_REVOKED', 'EXPIRED_TO_UNVERIFIED', 'EXPIRED_TO_VERIFIED', 'GUARDIAN_NOT_REQUIRED', 'GUARDIAN_REJECTED', 'GUARDIAN_REQUIRED_PENDING', 'GUARDIAN_REVOKED', 'GUARDIAN_VERIFIED', 'INSTITUTIONAL_EXPIRED', 'INSTITUTIONAL_PENDING', 'INSTITUTIONAL_REJECTED', 'INSTITUTIONAL_REVOKED', 'INSTITUTIONAL_UNVERIFIED', 'INSTITUTIONAL_VERIFIED', 'NOT_REQUIRED_TO_REJECTED', 'NOT_REQUIRED_TO_REQUIRED_PENDING', 'NOT_REQUIRED_TO_REVOKED', 'NOT_REQUIRED_TO_VERIFIED', 'PENDING_TO_EXPIRED', 'PENDING_TO_REJECTED', 'PENDING_TO_REVOKED', 'PENDING_TO_UNVERIFIED', 'PENDING_TO_VERIFIED', 'PROOF_REVOKED', 'REJECTED_TO_EXPIRED', 'REJECTED_TO_NOT_REQUIRED', 'REJECTED_TO_PENDING', 'REJECTED_TO_REQUIRED_PENDING', 'REJECTED_TO_REVOKED', 'REJECTED_TO_UNVERIFIED', 'REJECTED_TO_VERIFIED', 'REQUIRED_PENDING_TO_NOT_REQUIRED', 'REQUIRED_PENDING_TO_REJECTED', 'REQUIRED_PENDING_TO_REVOKED', 'REQUIRED_PENDING_TO_VERIFIED', 'REVIEWER_ASSIGNED', 'REVIEW_RETURNED_TO_QUEUE', 'REVOKED_TO_EXPIRED', 'REVOKED_TO_NOT_REQUIRED', 'REVOKED_TO_PENDING', 'REVOKED_TO_REJECTED', 'REVOKED_TO_REQUIRED_PENDING', 'REVOKED_TO_UNVERIFIED', 'REVOKED_TO_VERIFIED', 'UNVERIFIED_TO_EXPIRED', 'UNVERIFIED_TO_PENDING', 'UNVERIFIED_TO_REJECTED', 'UNVERIFIED_TO_REVOKED', 'UNVERIFIED_TO_VERIFIED', 'VERIFIED_TO_EXPIRED', 'VERIFIED_TO_NOT_REQUIRED', 'VERIFIED_TO_PENDING', 'VERIFIED_TO_REJECTED', 'VERIFIED_TO_REQUIRED_PENDING', 'VERIFIED_TO_REVOKED', 'VERIFIED_TO_UNVERIFIED')", name=op.f('ck_student_authority_audit_events_transition')),
        sa.PrimaryKeyConstraint('id', name='pk_student_authority_audit_events'),
    )
    op.create_table('student_authority_notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('registration_id', sa.Uuid(), sa.ForeignKey('student_registrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('state_version', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.CheckConstraint("code = 'review_returned_to_queue'", name=op.f('ck_student_authority_notifications_code')),
        sa.PrimaryKeyConstraint('id', name='pk_student_authority_notifications'),
        sa.UniqueConstraint('registration_id', 'state_version', 'code', name='uq_student_authority_notifications_registration_id'),
    )
    _map_legacy()
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION nyay11_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'authority_audit_append_only'; END; $$")
        op.execute("CREATE TRIGGER nyay11_audit_immutable BEFORE UPDATE OR DELETE ON student_authority_audit_events FOR EACH ROW EXECUTE FUNCTION nyay11_audit_immutable()")

def _map_legacy():
    bind = op.get_bind()
    guardian_map = {"pending":"REQUIRED_PENDING","sent":"REQUIRED_PENDING","verified":"VERIFIED","rejected":"REJECTED","revoked":"REVOKED"}
    institutional_map = {"pending":"UNVERIFIED","in_review":"PENDING","verified":"VERIFIED","rejected":"REJECTED","expired":"EXPIRED","revoked":"REVOKED"}
    for table, mapping in (("guardian_consents", guardian_map), ("student_verifications", institutional_map)):
        statuses = set(bind.execute(sa.text(f"SELECT DISTINCT status FROM {table}")).scalars())
        if not statuses <= set(mapping):
            raise RuntimeError("legacy_authority_unmapped")
    # Preserve every legacy row; mapping audit contains no registration/user ID.
    rows = bind.execute(sa.text("SELECT r.id, r.is_minor, g.status AS gs, v.status AS vs FROM student_registrations r LEFT JOIN guardian_consents g ON g.registration_id=r.id LEFT JOIN student_verifications v ON v.registration_id=r.id")).mappings()
    state = sa.table("student_authority_states", sa.column("registration_id", sa.Uuid()), sa.column("guardian_state"), sa.column("institutional_state"), sa.column("version"), sa.column("reproof_guardian", sa.Boolean()), sa.column("reproof_institutional", sa.Boolean()), sa.column("policy_version"))
    audit = sa.table("student_authority_audit_events", sa.column("id",sa.Uuid()), sa.column("actor_class"),sa.column("authority_class"),sa.column("purpose_code"),sa.column("transition_code"),sa.column("policy_version"),sa.column("occurred_at",sa.DateTime(timezone=True)))
    for row in rows:
        gs = guardian_map[row["gs"]] if row["gs"] else ("REQUIRED_PENDING" if row["is_minor"] else "NOT_REQUIRED")
        ins = institutional_map[row["vs"]] if row["vs"] else "UNVERIFIED"
        bind.execute(audit.insert(), [{"id":uuid.uuid4(),"actor_class":"server","authority_class":"server","purpose_code":"legacy_mapping","transition_code":code,"policy_version":"NYAY-11-v1","occurred_at":datetime.now(timezone.utc)} for code in (f"GUARDIAN_{gs}",f"INSTITUTIONAL_{ins}")])
        for purpose, code in (("guardian", "VERIFIED_TO_REQUIRED_PENDING" if gs == "VERIFIED" else None), ("institutional", "VERIFIED_TO_PENDING" if ins == "VERIFIED" else None)):
            if code is not None:
                bind.execute(audit.insert().values(id=uuid.uuid4(), actor_class="server", authority_class="server_profile_policy", purpose_code=purpose, transition_code=code, policy_version="NYAY-11-v1", occurred_at=datetime.now(timezone.utc)))
        bind.execute(state.insert().values(registration_id=uuid.UUID(str(row["id"])),guardian_state="REQUIRED_PENDING" if gs=="VERIFIED" else gs,institutional_state="PENDING" if ins=="VERIFIED" else ins,version=1,reproof_guardian=gs=="VERIFIED",reproof_institutional=ins=="VERIFIED",policy_version="NYAY-11-v1"))

def downgrade():
    for table in ('student_authority_states', 'guardian_authority_invitations', 'institutional_authority_email_proofs', 'institutional_reviewer_assignments', 'student_authority_mutations', 'student_authority_audit_events', 'student_authority_notifications'):
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {table} LIMIT 1')).first() is not None:
            raise RuntimeError('authority_downgrade_requires_empty_graph')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS nyay11_audit_immutable ON student_authority_audit_events")
        op.execute("DROP FUNCTION IF EXISTS nyay11_audit_immutable()")
    op.drop_table('student_authority_notifications')
    op.drop_table('student_authority_audit_events')
    op.drop_table('student_authority_mutations')
    op.drop_table('institutional_reviewer_assignments')
    op.drop_table('institutional_authority_email_proofs')
    op.drop_table('guardian_authority_invitations')
    op.drop_table('student_authority_states')
