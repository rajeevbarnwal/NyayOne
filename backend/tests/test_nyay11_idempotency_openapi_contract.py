"""Published idempotency headers must match the existing runtime contract.

Resolve component references: the sealed mentor API declares reusable header
parameters. Optional and body-only interfaces are deliberate exceptions, not
missing requirements. This inventory does not change authentication precedence.
"""
import pytest


REQUIRED_HEADERS = (
    *(('post', '/api/v1/auth/student/authority/' + path) for path in (
        'guardian/request', 'guardian/consent', 'guardian/revoke',
        'institutional/request', 'institutional/review',
        'institutional/email/request', 'institutional/email/verify',
        'institutional/assignment', 'institutional/break-glass',
    )),
    *(('post', '/api/v1/auth/mentor/' + path) for path in (
        'ceremony/initiate', 'ceremony/verify', 'ceremony/exchange',
        'session/rotate', 'session/revoke', 'session/logout', 'ceremony/recover',
    )),
    ('delete', '/api/v1/auth/mentor/authority'),
    ('post', '/api/v1/auth/student/verification/status'),
    ('post', '/api/v1/credentials'),
    ('post', '/api/v1/credentials/{credential_id}/share-projections'),
    ('post', '/api/v1/issuer/credentials/{credential_id}/verify'),
    ('post', '/api/v1/credentials/{credential_id}/verification-tokens'),
    ('post', '/api/v1/issuer/credentials/{credential_id}/revoke'),
    ('post', '/api/v1/internship-reports'),
    ('post', '/api/v1/moderation/internship-reports/{report_id}/actions'),
    ('post', '/api/v1/moderation/risk-clusters'),
    ('post', '/api/v1/moderation/internship-reports/{report_id}/identity-access-requests'),
    ('post', '/api/v1/moderation/identity-access-requests/{request_id}/approvals'),
    ('post', '/api/v1/moderation/risk-labels/{cluster_id}/publish'),
    ('post', '/api/v1/organisation-response-requests'),
    ('post', '/api/v1/organisation-responses'),
    ('post', '/api/v1/moderation/organisation-responses/{response_id}/decide'),
    ('post', '/api/v1/calendar/events'),
    ('post', '/api/v1/calendar/exports'),
    ('patch', '/api/v1/student/profile/personal'),
    ('patch', '/api/v1/student/profile/academic'),
    ('patch', '/api/v1/student/profile/interests'),
    ('patch', '/api/v1/auth/student/profile'),
    *(('post', '/api/v1/auth/student/email-identities' + path) for path in (
        '', '/{identity_id}/verify', '/{identity_id}/resend', '/{identity_id}/primary',
    )),
    ('delete', '/api/v1/auth/student/email-identities/{identity_id}'),
)
OPTIONAL_HEADERS = (
    ('post', '/api/v1/auth/student/register'),
    ('post', '/api/v1/student/privacy/export'),
    ('post', '/api/v1/student/privacy/delete'),
)
BODY_ONLY = (
    ('post', '/api/v1/tutoring/booking-holds'),
    ('post', '/api/v1/payments/orders'),
)


@pytest.fixture(scope='module')
def document():
    from tests import apptemplate

    app, client = apptemplate.mounted_app()
    try:
        yield app.openapi()
    finally:
        client.close()


def resolve(document, value):
    seen = set()
    while '$ref' in value:
        reference = value['$ref']
        assert reference.startswith('#/') and reference not in seen
        seen.add(reference)
        value = document
        for part in reference[2:].split('/'):
            value = value[part.replace('~1', '/').replace('~0', '~')]
    return value


def header_parameters(document, method, path):
    item = document['paths'][path]
    parameters = [*item.get('parameters', []), *item[method].get('parameters', [])]
    return [
        value for parameter in parameters
        if (value := resolve(document, parameter)).get('in') == 'header'
        and value.get('name', '').lower() == 'idempotency-key'
    ]


def admits_null(document, schema):
    schema = resolve(document, schema)
    if schema.get('nullable') is True or schema.get('type') == 'null':
        return True
    if isinstance(schema.get('type'), list) and 'null' in schema['type']:
        return True
    return any(admits_null(document, branch) for key in ('anyOf', 'oneOf') for branch in schema.get(key, []))


def test_audited_inventory_is_closed_and_nonempty():
    assert len(REQUIRED_HEADERS) == len(set(REQUIRED_HEADERS)) == 43
    assert len(OPTIONAL_HEADERS) == len(set(OPTIONAL_HEADERS)) == 3
    assert len(BODY_ONLY) == len(set(BODY_ONLY)) == 2
    assert len(set(REQUIRED_HEADERS + OPTIONAL_HEADERS + BODY_ONLY)) == 48


@pytest.mark.parametrize(('method', 'path'), REQUIRED_HEADERS)
def test_mandatory_header_is_exactly_once_required_and_nonnullable(document, method, path):
    parameters = header_parameters(document, method, path)
    assert len(parameters) == 1, 'IDEMPOTENCY_OPENAPI_HEADER_INVENTORY'
    assert parameters[0].get('required') is True, 'IDEMPOTENCY_OPENAPI_REQUIRED'
    schema = resolve(document, parameters[0]['schema'])
    assert schema.get('type') == 'string', 'IDEMPOTENCY_OPENAPI_STRING'
    assert not admits_null(document, schema), 'IDEMPOTENCY_OPENAPI_NON_NULLABLE'


@pytest.mark.parametrize(('method', 'path'), OPTIONAL_HEADERS)
def test_genuine_optional_header_remains_optional(document, method, path):
    parameters = header_parameters(document, method, path)
    assert len(parameters) == 1
    assert parameters[0].get('required') is False
    assert admits_null(document, parameters[0]['schema'])


@pytest.mark.parametrize(('method', 'path'), BODY_ONLY)
def test_body_idempotency_does_not_gain_a_header_requirement(document, method, path):
    assert header_parameters(document, method, path) == []
    operation = document['paths'][path][method]
    request = resolve(document, operation['requestBody'])
    schema = resolve(document, request['content']['application/json']['schema'])
    assert 'idempotency_key' in schema['required']
    assert resolve(document, schema['properties']['idempotency_key'])['type'] == 'string'
