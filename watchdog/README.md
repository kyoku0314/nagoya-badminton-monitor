# Independent watchdog (Cloudflare Workers)

This is an external watchdog for the existing GitHub Actions court monitor. It checks every five minutes, requests a recovery run if the latest run started over 22 minutes ago, and sends Discord notifications for recovery and failures. It does **not** replace the existing 15-minute schedule or change court-search rules.

## One-time setup

1. Create a Cloudflare account and a Workers KV namespace named `NAGOYA_WATCHDOG_STATE`.
2. Replace `REPLACE_WITH_KV_NAMESPACE_ID` in `wrangler.jsonc` with the KV namespace ID.
3. Create a fine-grained GitHub token limited to repository `kyoku0314/nagoya-badminton-monitor`, with **Actions: Read and write** permission.
4. In this directory run `npx wrangler login`, `npx wrangler secret put GITHUB_TOKEN`, and `npx wrangler secret put DISCORD_WEBHOOK_URL` (use your existing Discord webhook URL).
5. Run `npx wrangler deploy`. The scheduled trigger is UTC, but runs every five minutes regardless of time zone.

Keep tokens and webhook URLs out of git. Never paste them in a chat. The watchdog needs an external account deployment and cannot be activated by committing code alone.

## Behavior and limitations

- The monitor workflow already supports `workflow_dispatch`.
- Stale threshold: 22 minutes since last workflow run was created.
- Recovery cooldown: 20 minutes, recorded in Workers KV.
- Running/queued jobs are not duplicated.
- Alerts are rate-limited to one per hour.
- GitHub and Cloudflare schedules are best-effort; this reduces missed scans but cannot guarantee zero missed runs.
- A GitHub workflow run marked successful is not proof that every court/date was scanned. Application-level heartbeat and scan completeness checks would be a useful next enhancement.
- Cloudflare KV is eventually consistent; simultaneous checks can theoretically race. For strict exactly-once dispatch, use a Durable Object.
