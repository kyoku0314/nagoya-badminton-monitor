# Cloudflare Worker: Nagoya badminton watchdog

This directory contains the revised source for the existing Cloudflare Worker **nagoya-badminton-monitor**. It preserves the GitHub Actions watchdog, Discord notifications, KV cooldown state, one-time self-test, and `/health` endpoint.

## Japan-time behavior

- 00:00–07:59 JST: quiet; no GitHub dispatch and no Discord alerts.
- 08:00–08:14 JST: startup grace period; quiet.
- 08:15–23:59 JST: watchdog active.
- December 29–January 3 JST: official Nagoya reservation-system holiday; quiet.
- The normal GitHub monitor workflow is not modified by these Worker changes.

## Safe deployment prerequisites

The workflow `.github/workflows/deploy-cloudflare.yml` is **manual only**. It deliberately will not deploy until `cloudflare/wrangler.toml` exists. Do not invent the existing KV namespace ID or Cron trigger: deployment can otherwise overwrite important Worker bindings or schedules.

1. In Cloudflare, confirm the **account ID**, the exact **WATCHDOG_STATE KV namespace ID**, and the existing **Cron Trigger** expression for `nagoya-badminton-monitor`.
2. Copy `wrangler.toml.example` to `wrangler.toml`, replace the KV namespace placeholder with the real existing ID, and explicitly copy the Worker’s current Cron expression into `[triggers]`. Do not change any other Worker bindings; add them to config if present.
3. Confirm GitHub Actions secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are present. Do not paste secret values into chat or commit them.
4. Run **Test Cloudflare Watchdog** and inspect the results; then manually dispatch **Deploy Cloudflare Watchdog** once. Confirm the Worker still has its existing secrets, KV binding, and Cron trigger.
5. Check Cloudflare logs and the `/health` endpoint. A healthy REST endpoint should show `monitoring: paused` during quiet hours, and `active` during monitoring hours.

Source code is unbundled JavaScript. The existing active Worker has **not** been changed by committing these files to GitHub.
