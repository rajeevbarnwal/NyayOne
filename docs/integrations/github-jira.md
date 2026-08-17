# GitHub and Jira API Integration

NyayOne is configured around these external project systems:

- GitHub repository: `rajeevbarnwal/NyayOne`
- GitHub API endpoint: `https://api.github.com/repos/rajeevbarnwal/NyayOne`
- Jira site: `https://legalsaathi.atlassian.net`
- Jira project key: `NYAY`
- Jira board ID: `68`
- Jira project API endpoint: `https://legalsaathi.atlassian.net/rest/api/3/project/NYAY`
- Jira board API endpoint: `https://legalsaathi.atlassian.net/rest/agile/1.0/board/68`

## Local Secrets

Copy `.env.example` to `.env` and fill only local secrets there. Do not commit `.env`.

```bash
GITHUB_TOKEN=
JIRA_EMAIL=
JIRA_API_TOKEN=
```

GitHub tokens should be scoped to the least privilege required by the task. For repository metadata, read metadata is enough; for publishing code, use normal git authentication or a token with content write permission.

For Jira Cloud, Atlassian supports basic auth for simple REST scripts using the Atlassian account email address plus an API token. Password authentication is deprecated. For a production user-facing integration, prefer OAuth/Forge rather than collecting personal API tokens.

## Verification

After `.env` exists, run:

```bash
./scripts/check_integrations.py
```

The script checks GitHub repository metadata and, when Jira credentials are present, validates both the Jira project and board APIs.

## Workflow Convention

Use Jira issue keys in branch names, commits, and pull requests where practical:

```text
feature/NYAY-123-short-description
fix/NYAY-124-short-description
```

Pull requests should include the Jira issue key so GitHub work remains traceable to Jira planning.

## Official API References

- GitHub REST: get a repository
  `GET /repos/{owner}/{repo}`
- Jira Cloud platform REST: get project
  `GET /rest/api/3/project/{projectIdOrKey}`
- Jira Software Cloud REST: get board
  `GET /rest/agile/1.0/board/{boardId}`
- Jira Cloud authentication: basic auth with Atlassian email plus API token for scripts
