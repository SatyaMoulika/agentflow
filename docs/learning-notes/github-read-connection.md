# Read GitHub through an HTTP connection

Use **Integrations → GitHub** to create a read-only connection to one repository's issues or pull requests. It uses the existing owner-bound HTTP connections and HTTP GET node, and supports manually started workflows. Webhook/scheduled triggers and GitHub write actions are not implemented.

## Create a token for local use

1. Open [GitHub fine-grained tokens](https://github.com/settings/personal-access-tokens) and choose **Generate new token**.
2. Name it `AgentFlow Local` and choose a short expiration, such as 30 days or your organization's shorter required lifetime.
3. Select the repository's owner under **Resource owner**. Under **Repository access**, choose **Only select repositories** and select the repository you want AgentFlow to read.
4. For an issues/PR briefing, grant **Issues: Read-only** and **Pull requests: Read-only**. Metadata read access is included automatically. Leave other optional permissions unset. Repository metadata alone does not need the two additional permissions.
5. Generate the token and save it privately. Organization policies may require administrator approval before private repository access works. Paste it only into AgentFlow's Credential field; never into chat, a workflow definition or a repository file.

For organization-wide or long-lived integrations, a GitHub App is a later option. See [GitHub's token guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## Connect and make the first read

1. Keep the existing `AGENTFLOW_CONNECTION_ENCRYPTION_KEY` in private `backend/.env`. Restart the API if that key was added after the API started. Do not generate a replacement for an existing key.
2. When the API runs on port **8001**, start Vite from the project root with `AGENTFLOW_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev`. Open `http://localhost:5173` and sign in.
3. Open **Integrations → GitHub** and enter the repository owner, name and whether to read issues or pull requests. For a private repository, paste the fine-grained token into the credential field. Select **Create GitHub connection**. Public repositories can be read without a token. This stores an HTTP connection and does not yet contact GitHub.

   Alternatively, **Integrations → HTTP connections** supports other fixed GitHub endpoints such as repository metadata:

   | Field          | Value                                     |
   | -------------- | ----------------------------------------- |
   | Name           | `GitHub repository overview`              |
   | HTTPS endpoint | `https://api.github.com/repos/OWNER/REPO` |
   | Authentication | `Bearer token`                            |
   | Credential     | Your token, without a `Bearer ` prefix    |

   Replace `OWNER/REPO` with the exact selected repository, for example `SatyaMoulika/agentflow`. Create the connection. This stores the encrypted credential; it does not yet call GitHub.

4. Create `Manual Trigger → HTTP GET → End`. On HTTP GET, select the connection. Save, validate, and run with `{}`.
5. Inspect the actual result: `status_code` should be `200`, and `body` should contain the selected GitHub data. This verifies the selected endpoint, not every future GitHub capability.

To read issues or pull requests, create separate fixed connections ending in `/issues` or `/pulls`, with the matching read permissions. The issues endpoint can include pull requests; entries with a `pull_request` key represent PRs. See [GitHub's issues API](https://docs.github.com/en/rest/issues/issues).

## Limits and troubleshooting

- The connector sends a fixed `User-Agent: AgentFlow/0.1` header, which satisfies GitHub's [User-Agent requirement](https://docs.github.com/en/rest/using-the-rest-api/getting-started-with-the-rest-api#user-agent).
- Requests remain GET-only and synchronous, with no automatic retry or replay. No repository changes, comments or labels are written.
- Each connection authorizes one exact public HTTPS URL. Query parameters, redirects, arbitrary headers and automatic pagination are unavailable. Collection endpoints return GitHub's default first page; responses exceeding the existing 64 KiB limit fail rather than being truncated.
- Validation checks graph structure and connection availability; the actual run checks GitHub authorization. An expired token, missing repository grant or organization approval can make a read fail. Create a replacement connection explicitly when rotating a token, then revoke the old connection.
- An empty issues array can be a successful read. A successful HTTP node does not guarantee Groq configuration or that AI summaries are accurate. Agent HTTP results sent to Groq are also retained in run history, as disclosed in the app.

## Verification — 16 November 2026

The standard backend checker passed **944 tests**, Ruff lint/format and Pyright, with **446 opt-in integrations skipped**. The transport test verifies the application header on the actual HTTP stack. One unauthenticated read of GitHub's public `octocat/Hello-World` repository passed through the controlled executor, without credentials, database writes or printing the response payload. Authenticated private-repository reads and browser acceptance remain unverified. No frontend, database schema or migration changed for this compatibility update.
