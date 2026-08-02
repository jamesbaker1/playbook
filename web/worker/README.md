# playbook-traces worker

Collects episode traces contributed from the web gym into Cloudflare KV.

- `POST /api/traces` — public, CORS-limited to the gym's origin. Validates shape,
  size (≤ 2 MB, ≤ 200 events), app version, optional background category, and
  explicit versioned training/evaluation consent before storing the record.
- `GET /api/traces` / `GET /api/traces/<key>` — require `Authorization: Bearer
  <READ_TOKEN>` (a Worker secret).

**Trust model:** uploads are anonymous and client-scored, so nothing here is
trusted. `training/human_data.py` downloads the records, replays every action
sequence through the real environment, recomputes the score deterministically,
and drops incomplete, non-reproducible, or unconsented records. Only verified
episodes are exported for training, tagged `agent: human`; the optional display
handle remains in raw storage and is not copied into the training dataset.

Deploy / manage (from this directory):

```bash
npx wrangler deploy
npx wrangler secret put READ_TOKEN        # paste the read token
npx wrangler kv key list --binding TRACES --remote --prefix trace:
```

Web integration points (kept deliberately tiny so UI work can proceed freely):

1. `index.html` loads `contribute.js` after `app.js`.
2. `app.js`, in the score block's actions row:
   `if (window.playbookContribute) window.playbookContribute(r, actions, () => driver.trace());`

Everything else (consent copy, upload call, status UI) lives in
`web/contribute.js`, which no other code depends on.
