// Nagoya badminton Cloudflare external watchdog.
// Runtime bindings: GITHUB_TOKEN (secret), DISCORD_WEBHOOK_URL (secret),
// WATCHDOG_STATE (KV). Never commit credentials.
const OWNER = "kyoku0314";
const REPO = "nagoya-badminton-monitor-public";
const WORKFLOW = "monitor.yml";
const API = "https://api.github.com/repos/" + OWNER + "/" + REPO;

function headers(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: "Bearer " + token,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "nagoya-badminton-watchdog"
  };
}
async function github(path, env, options = {}) {
  const res = await fetch(API + path, {
    ...options, headers: { ...headers(env.GITHUB_TOKEN), ...(options.headers || {}) }
  });
  if (!res.ok) throw new Error("GitHub API " + res.status + ": " + (await res.text()).slice(0, 180));
  return res.status === 204 ? null : res.json();
}
async function notify(env, message) {
  if (!env.DISCORD_WEBHOOK_URL) return;
  const res = await fetch(env.DISCORD_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: message, allowed_mentions: { parse: [] } })
  });
  if (!res.ok) throw new Error("Discord HTTP " + res.status);
}
// All schedule decisions use JST. GitHub timestamps remain UTC for age calculations.
function japanTime(timestamp = Date.now()) {
  const pieces = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts(new Date(timestamp));
  const number = (name) => Number(pieces.find((p) => p.type === name).value);
  return {
    month: number("month"), day: number("day"),
    hour: number("hour"), minute: number("minute")
  };
}
function monitoringWindow(timestamp = Date.now()) {
  const jst = japanTime(timestamp);
  if ((jst.month === 12 && jst.day >= 29) || (jst.month === 1 && jst.day <= 3))
    return { enabled: false, reason: "official_holiday", jst };
  if (jst.hour < 8) return { enabled: false, reason: "night_rest", jst };
  if (jst.hour === 8 && jst.minute < 5)
    return { enabled: false, reason: "morning_grace", jst };
  return { enabled: true, reason: "business_hours", jst };
}
async function oneTimeSelfTest(env) {
  const key = "selftest-2026-11-12-v1";
  const state = JSON.parse((await env.WATCHDOG_STATE.get(key)) || "{}");
  if (state.completed) return;
  if (!state.dispatched) {
    await github("/actions/workflows/" + WORKFLOW + "/dispatches", env, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" })
    });
    await env.WATCHDOG_STATE.put(key, JSON.stringify({ dispatched: true, completed: false }));
    console.info("SELFTEST_DISPATCH_OK");
  }
  await notify(env, "🧪 外部守护自检：GitHub Actions 补跑请求成功，Discord 通知通道正常。此消息为一次性测试。");
  await env.WATCHDOG_STATE.put(key, JSON.stringify({ dispatched: true, completed: true }));
  console.info("SELFTEST_DISCORD_OK");
}
async function check(env) {
  if (!env.GITHUB_TOKEN || !env.WATCHDOG_STATE)
    throw new Error("Missing GITHUB_TOKEN or WATCHDOG_STATE binding");
  const now = Date.now();
  const window = monitoringWindow(now);
  if (!window.enabled) {
    console.info("PAUSED", JSON.stringify({ reason: window.reason, jst: window.jst }));
    return { status: "PAUSED", reason: window.reason };
  }
  const data = await github("/actions/workflows/" + WORKFLOW + "/runs?per_page=20&branch=main", env);
  const runs = (data.workflow_runs || []).filter((r) => ["schedule", "workflow_dispatch"].includes(r.event));
  const latest = runs[0];
  const active = runs.some((r) => ["queued", "in_progress", "waiting", "pending", "requested"].includes(r.status));
  const lastStart = latest ? Date.parse(latest.created_at) : 0;
  const age = lastStart ? Math.round((now - lastStart) / 60000) : null;
  const lastSuccess = runs.find((r) => r.conclusion === "success");
  const successAge = lastSuccess ? Math.round((now - Date.parse(lastSuccess.created_at)) / 60000) : null;
  // Allow the 08:02 scheduled GitHub run to start; recover from 08:05 onward.
  const jstNow = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(now));
  const morningStartup = jstNow >= "08:00" && jstNow < "08:05";
  const stale = !latest || age > 35;
  if (morningStartup) {
    console.info("MORNING_CHECK", JSON.stringify({ ageMinutes: age, active, dispatchAllowed: false }));
    return { status: "MORNING_CHECK", age };
  }
  const state = JSON.parse((await env.WATCHDOG_STATE.get("state-public")) || "{}");
  const lastDispatch = state.lastDispatch || 0;
  const cooldown = now - lastDispatch < 20 * 60000;
  if (stale && !active && !cooldown) {
    await env.WATCHDOG_STATE.put("state-public", JSON.stringify({ ...state, lastDispatch: now }));
    await github("/actions/workflows/" + WORKFLOW + "/dispatches", env, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" })
    });
    console.info("RECOVERY", JSON.stringify({ ageMinutes: age, reason: "stale_workflow" }));
    await notify(env, "🔄 羽毛球监控自动补跑：距离上次启动 " + (age ?? "未知") + " 分钟，已请求 GitHub 重新运行。");
    return { status: "dispatched", age };
  }
  const failing = latest?.conclusion === "failure" || (successAge !== null && successAge > 60);
  if (failing && now - (state.lastAlert || 0) > 60 * 60000) {
    await env.WATCHDOG_STATE.put("state-public", JSON.stringify({ ...state, lastAlert: now }));
    console.warn("ERROR", JSON.stringify({ reason: "monitor_failure", successAgeMinutes: successAge }));
    await notify(env, "⚠️ 羽毛球监控故障：最近运行状态 " +
      (latest?.conclusion || latest?.status || "未知") +
      "，距上次成功启动 " + (successAge ?? "未知") +
      " 分钟。请检查 GitHub Actions。\n" + (latest?.html_url || ""));
  }
  const status = active ? "RUNNING" : stale ? "COOLDOWN" : "HEALTHY";
  console.info(status, JSON.stringify({
    ageMinutes: age, successAgeMinutes: successAge,
    lastRunConclusion: latest?.conclusion || null
  }));
  return { status, age, successAge };
}
export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      // Guard before self-test: overnight does NOT dispatch or send Discord.
      const window = monitoringWindow();
      if (!window.enabled) {
        console.info("PAUSED", JSON.stringify({ reason: window.reason, jst: window.jst }));
        return { status: "PAUSED", reason: window.reason };
      }
      return check(env);
    })().catch(async (err) => {
      console.error("ERROR", String(err.message));
      await notify(env, "🚨 外部守护检查失败：" + String(err.message).slice(0, 250))
        .catch(console.error);
      throw err;
    }));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/health")
      return new Response("Nagoya badminton watchdog", { status: 200 });
    try {
      if (!env.GITHUB_TOKEN || !env.WATCHDOG_STATE)
        throw new Error("Missing runtime configuration");
      const data = await github("/actions/workflows/" + WORKFLOW + "/runs?per_page=1&branch=main", env);
      const latest = data.workflow_runs?.[0];
      const window = monitoringWindow();
      console.info("HEALTH_CHECK", JSON.stringify({ githubApi: "ok", hasRuns: !!latest }));
      return Response.json({
        watchdog: "online", repository: REPO, githubApi: "ok", hasRuns: !!latest,
        monitoring: window.enabled ? "active" : "paused", reason: window.reason
      });
    } catch (err) {
      console.error("ERROR", "health_check", String(err.message));
      return Response.json({ watchdog: "degraded", githubApi: "error" }, { status: 503 });
    }
  }
};
