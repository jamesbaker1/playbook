# playbook-traces worker

This Worker is the untrusted collection inbox for consented web-gym traces. The
production services currently configured in this repository are:

- Web gym: `https://jamesbaker1.github.io/playbook/`
- Engine: `https://playbook-engine.james-baker1628.workers.dev`
- Trace collector: `https://playbook-traces.james-baker1628.workers.dev`

`POST /api/traces` is public and returns browser CORS headers only for configured
origins; CORS is not authentication. It validates the envelope, request-text
length (at most 2,000,000 characters), event count (at most 200), app version, and
explicit current training/evaluation consent. `GET /api/traces` and
`GET /api/traces/<key>` require
`Authorization: Bearer <READ_TOKEN>`. There is no public administrative UI.

Browser scores are not trusted. `training/human_data.py` downloads each record,
replays its actions locally, recomputes the score, and exports only reproducible,
complete, consented episodes. An optional display handle remains in raw storage
and is not copied into training data.

## Deploy and synchronize administrative access

Run commands from `web/worker`. Authenticate Wrangler with `npx wrangler login`
if needed, then deploy with `npx wrangler deploy`.

`READ_TOKEN` is write-only after it is stored in Cloudflare. Generate one strong
random token, retain it in a password manager, and use that exact same value both
as the Worker secret and as the local `PLAYBOOK_TRACES_TOKEN`. Never commit it,
paste it into documentation, or pass it as a command-line argument.

```bash
npx wrangler secret put READ_TOKEN
# Paste the retained value at Wrangler's interactive prompt.
read -s PLAYBOOK_TRACES_TOKEN
export PLAYBOOK_TRACES_TOKEN
```

```powershell
npx wrangler secret put READ_TOKEN
# Paste the retained value at Wrangler's interactive prompt.
$secure = Read-Host "PLAYBOOK_TRACES_TOKEN" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:PLAYBOOK_TRACES_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
```

For later sessions, load the same value from a password manager. A local `.env`
is gitignored, but it is plaintext and should only be used on a suitably protected
machine. Changing only one side causes authenticated reads to return HTTP 401;
Cloudflare cannot reveal the old secret, so set both sides again from one retained
value.

## Inspect production data

Wrangler can inspect KV without the read token:

```bash
npx wrangler kv key list --binding TRACES --remote --prefix 'trace:'
npx wrangler kv key get 'trace:MATTER:TIMESTAMP:UUID' --binding TRACES --remote --text
```

```powershell
npx wrangler kv key list --binding TRACES --remote --prefix "trace:"
npx wrangler kv key get "trace:MATTER:TIMESTAMP:UUID" --binding TRACES --remote --text
```

The protected API can also list records (and returns a pagination cursor when
more pages exist):

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $PLAYBOOK_TRACES_TOKEN" \
  https://playbook-traces.james-baker1628.workers.dev/api/traces
```

```powershell
$headers = @{ Authorization = "Bearer $env:PLAYBOOK_TRACES_TOKEN" }
Invoke-RestMethod `
  -Headers $headers `
  -Uri "https://playbook-traces.james-baker1628.workers.dev/api/traces"
```

Do not delete a record merely because verification rejects it. Preserve rejected
records and reason counts for audit and pipeline monitoring. If deletion is
authorized, resolve and review the exact key first; do not use a broad prefix.

## Troubleshooting

- HTTP 401 on `GET`: local and Worker tokens differ, the environment variable is
  empty, or the `Authorization` header is missing. Re-synchronize both sides.
- HTTP 400 on `POST`: inspect the JSON error; consent, app version, or trace shape
  failed validation.
- HTTP 413 on `POST`: the request text exceeds 2,000,000 characters.
- Wrangler login callback times out: keep the initiating terminal open, retry
  `npx wrangler login`, and ensure the browser can reach the exact localhost
  callback port Wrangler prints. Do not share callback URLs because they contain
  short-lived authorization material.
- Wrangler deploy/KV requests time out: first retry a read-only command such as
  `npx wrangler whoami`; check Cloudflare status and local proxy/firewall settings,
  then retry. A timeout does not prove that a mutation failed, so verify the
  deployed version or exact key before repeating a write or delete.

See `training/README.md` for verified export, review gates, and training launch.
