# NyayOne Runtime Isolation Contract

This contract records the NYAY-20 operational boundary. It applies to active
NyayOne runtime configuration, local Compose, CI database services, integration
metadata and operator runbooks.

## Canonical identities

| Surface | NyayOne value |
|---|---|
| Application | `NyayOne` |
| GitHub repository | `rajeevbarnwal/NyayOne` |
| Jira project and board | `NYAY`, board `68` |
| Jira tenant | `https://legalsaathi.atlassian.net` |
| Session cookie | `nyayone_session` |
| Compose project | `nyayone` |
| Local database user/database | `nyayone` / `nyayone` |
| CI database user | `nyayone_ci` |
| Local host ports | `1130` through `1144` as reserved in `docker-compose.yml` |
| TURN relay block | `21500-21549/udp` |
| Video subnet | `172.29.31.0/24` |

The Atlassian tenant is the only approved LegalSaathi-named operational
exception. NyayOne has its own project and board on that shared tenant.

Container-internal ports such as frontend `1030`, backend `1031`, PostgreSQL
`5432` and LiveKit `7880` are implementation details. Isolation is enforced at
the published host-port, Compose-resource and identity boundaries.

## Data and compatibility assumption

NyayOne starts with its own empty PostgreSQL volume. No LegalSaathi production,
staging or subscriber data is imported. Calendar producer metadata, UID domains
and deterministic UUID namespaces therefore use NyayOne identities from the
first NyayOne database. If data is imported later, that is a separate migration
and subscriber-compatibility project; operators must not copy a LegalSaathi
database into this runtime and rely only on its Alembic revision.

The historical public-organisation UUID namespace remains unchanged because it
was embedded in migration `0015`. NYAY-16 owns migration provenance and any
future compatibility-aware namespace transition. Historical migration files
must never be edited to perform rebranding.

## Security and CI enforcement

- Non-local environments refuse the checked-in local database password.
- Active runtime configuration refuses legacy database, cookie, repository,
  storage and integration identities without echoing credentials.
- GitHub and Jira integration origins are allowlisted exactly. This prevents a
  configuration change from forwarding repository or Jira credentials to an
  attacker-controlled host.
- The policy gate parses Settings defaults, environment defaults, rendered
  Compose, CI PostgreSQL identities and active source contracts.
- Seeded negative tests prove the policy fails on legacy and arbitrary drift,
  wrong Compose credentials, database path-prefix tricks and excluded-history
  mistakes.

Historical migrations, sealed QA evidence and SAATHI traceability references
are not rewritten. Frontend package IDs, Capacitor application IDs and remaining
browser/mobile product namespaces are owned by NYAY-18.
