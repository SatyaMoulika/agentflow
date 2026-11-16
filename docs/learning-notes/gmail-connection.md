# Gmail connection setup

The current Gmail increment supports connecting an owned account with read-only consent, listing recent inbox message IDs, manually reading one message into a workflow, and locally disconnecting. Automatic triggers, approvals and sending are not available yet. No live Google authorization or browser acceptance has been verified.

1. In Google Cloud, create or select a project, enable the Gmail API, configure the OAuth consent screen and create a **web application** OAuth client. Configure a test audience/user as appropriate for your project. Register the exact redirect URI `http://localhost:5173/integrations/gmail/callback` for local testing. Use one hostname consistently.
2. In your existing private `backend/.env`, configure `AGENTFLOW_GMAIL_CLIENT_ID`, `AGENTFLOW_GMAIL_CLIENT_SECRET`, and `AGENTFLOW_GMAIL_REDIRECT_URI` with your own client values and the exact registered redirect URI. Gmail also requires `AGENTFLOW_CONNECTION_ENCRYPTION_KEY`; preserve any existing value. Never paste credentials into chat or commit them. The redirect origin must be in `AGENTFLOW_AUTH_ALLOWED_ORIGINS`; production requires HTTPS.
3. From the project root, run `uv run --directory backend --locked alembic upgrade head`, then restart the backend and frontend. Open **Integrations → Gmail → Connect Gmail**, sign in to Google and review the read-only consent request. The callback is bound to the AgentFlow user who began authorization and can be consumed once.
4. Integrations lists opaque connection IDs. Select **Show recent message IDs** to list up to ten inbox IDs. **Disconnect** deletes the locally stored refresh credential and preserves the connection record; revoke the application's Google grant in your Google Account if desired. A failed or lost callback needs a new connection attempt.

## Manual inbox workflow

Create `Manual Trigger → Read Gmail message → Classify text with Groq → End` in the editor. Select the owned connection on the Gmail node and leave its `message_id_field` set to `message_id`. Configure the classifier with `input_field` set to `text` and its desired labels. Save and validate, then use a listed ID as manual input:

```json
{"message_id": "replace-with-a-selected-message-id"}
```

The Gmail node returns `text` and `message_id`. Only inline UTF-8 plain-text parts are extracted, with a 16 KiB body limit; HTML and attachments are not interpreted. Classification requires nonempty text of at most 4,000 characters, so messages outside that limit fail rather than being silently changed. Gmail and Groq calls are synchronous and are not automatically retried or recovered. An in-flight call can finish after disconnect; ownership and revocation are checked before and after reads.

**Privacy:** the email text is saved in the workflow's execution history and is sent to Groq if a downstream node uses it. Review access and retention before using real mail. Email content is untrusted and a model's instruction to ignore malicious text is not a guarantee. AI workflow proposal generation does not currently support Gmail nodes; create or edit this flow manually.

The browser callback strips its query string before rendering and requests `Referrer-Policy: no-referrer` via the page. Configure your frontend server, reverse proxy and access logs not to record the callback query: it contains a short-lived authorization code. Never use real inbox content in test fixtures. Google classifies the Gmail read-only permission as restricted; verification and security-assessment requirements depend on the deployment and use of the data. See [Google's OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server) and [Gmail scope requirements](https://developers.google.com/workspace/gmail/api/auth/scopes).
