const OWNER = "kyoku0314";
const REPO = "nagoya-badminton-monitor";
const WORKFLOW = "monitor.yml";
const API = `https://api.github.com/repos/${OWNER}/${REPO}`;
const headers = token => ({
  "Accept": "application/vnd.github+json",
  "Authorization": `Bearer ${token}`,
  "X-GitHub-Api-Version": "2022-11-28",
  "User-Agent": "nagoya-badminton-watchdog"
});
async function github(path, env, options = {}) {
  const res = await fetch(API + path, { ...options, headers: { ...headers(env.GITHUB_TOKEN), ...(options.headers || {}) } });
  if (!res.ok) throw new Error(`GitHub API ${res.status}: ${(await res.text()).slice(0,180)}`);
  return res.status === 204 ? null : res.json();
}
async function notify(env, message) {
  if (!env.DISCORD_WEBHOOK_URL) return;
  const res = await fetch(env.DISCORD_WEBHOOK_URL, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: message, allowed_mentions: { parse: [] } })
  });
  if (!res.ok) throw new Error(`Discord HTTP ${res.status}`);
}

// Official reservation service operates 08:00-24:00 Japan time.
// Do not treat its overnight and year-end closures as monitoring failures.
function monitoringWindow(timestamp = Date.now()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts(new Date(timestamp));
  const get = type => Number(parts.find(p => p.type === type).value);
  const month = get("month"), day = get("day");
  const hour = get("hour"), minute = get("minute");
  if ((month === 12 && day >= 29) || (month === 1 && day <= 3))
    return { enabled: false, reason: "official_holiday" };
  if (hour < 8) return { enabled: false, reason: "night_rest" };
  if (hour === 8 && minute < 15)
    return { enabled: false, reason: "morning_grace" };
  return { enabled: true, reason: "business_hours" };
}

async function oneTimeSelfTest(env) {
  const key = "selftest-2026-11-12-v1";
  const state = JSON.parse(await env.WATCHDOG_STATE.get(key) || "{}");
  if (state.completed) return;
  // An extra normal workflow run tests the actual dispatch permission.
  if (!state.dispatched) {
    await github(`/actions/workflows/${WORKFLOW}/dispatches`, env, {
      method: "POST", headers: { "Content-Type": "application/json" },
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
  if (!env.GITHUB_TOKEN || !env.WATCHDOG_STATE) throw new Error("Missing GITHUB_TOKEN or WATCHDOG_STATE binding");
  const now = Date.now();
  const window = monitoringWindow(now);
  if (!window.enabled) {
    console.info("PAUSED", window.reason);
    return { status: "PAUSED", reason: window.reason };
  }
  const data = await github(`/actions/workflows/${WORKFLOW}/runs?per_page=20&branch=main`, env);
  const runs = (data.workflow_runs || []).filter(r => ["schedule", "workflow_dispatch"].includes(r.event));
  const latest = runs[0];
  const active = runs.some(r => ["queued", "in_progress", "waiting", "pending", "requested"].includes(r.status));
  const lastStart = latest ? Date.parse(latest.created_at) : 0;
  const age = lastStart ? Math.round((now - lastStart) / 60000) : null;
  const lastSuccess = runs.find(r => r.conclusion === "success");
  const successAge = lastSuccess ? Math.round((now - Date.parse(lastSuccess.created_at)) / 60000) : null;
  const stale = !latest || age > 22;
  const state = JSON.parse(await env.WATCHDOG_STATE.get("state") || "{}");
  const lastDispatch = state.lastDispatch || 0;
  const cooldown = now - lastDispatch < 20 * 60000;
  if (stale && !active && !cooldown) {
    // Write the cooldown first to reduce repeated dispatches on retried invocations.
    await env.WATCHDOG_STATE.put("state", JSON.stringify({ ...state, lastDispatch: now }));
    await github(`/actions/workflows/${WORKFLOW}/dispatches`, env, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" })
    });
    console.info("RECOVERY", JSON.stringify({ ageMinutes: age, reason: "stale_workflow" }));
    await notify(env, `🔄 羽毛球监控自动补跑：距离上次启动 ${age ?? "未知"} 分钟，已请求 GitHub 重新运行。`);
    return { status: "dispatched", age };
  }
  // Alert only after repeated failures or prolonged absence of successful runs.
  const failing = latest?.conclusion === "failure" || (successAge !== null && successAge > 60);
  if (failing && now - (state.lastAlert || 0) > 60 * 60000) {
    await env.WATCHDOG_STATE.put("state", JSON.stringify({ ...state, lastAlert: now }));
    console.warn("ERROR", JSON.stringify({ reason: "monitor_failure", successAgeMinutes: successAge }));
    await notify(env, `⚠️ 羽毛球监控故障：最近运行状态 ${latest?.conclusion || latest?.status || "未知"}，距上次成功启动 ${successAge ?? "未知"} 分钟。请检查 GitHub Actions。\n${latest?.html_url || ""}`);
  }
  const status = active ? "RUNNING" : stale ? "COOLDOWN" : "HEALTHY";
  console.info(status, JSON.stringify({ ageMinutes: age, successAgeMinutes: successAge, lastRunConclusion: latest?.conclusion || null }));
  return { status, age, successAge };
}
export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      const window = monitoringWindow();
      if (!window.enabled) {
        console.info("PAUSED", window.reason);
        return { status: "PAUSED", reason: window.reason };
      }
      await oneTimeSelfTest(env);
      return check(env);
    })().catch(async err => {
      console.error("ERROR", String(err.message));
      await notify(env, `🚨 外部守护检查失败：${String(err.message).slice(0,250)}`).catch(console.error);
      throw err;
    }));
  },
  async fetch(request, env) {
    // A public read-only diagnostic never dispatches or exposes credentials.
    const url = new URL(request.url);
    if (url.pathname !== "/health") return new Response("Nagoya badminton watchdog", { status: 200 });
    try {
      if (!env.GITHUB_TOKEN || !env.WATCHDOG_STATE) throw new Error("Missing runtime configuration");
      const data = await github(`/actions/workflows/${WORKFLOW}/runs?per_page=1&branch=main`, env);
      const latest = data.workflow_runs?.[0];
      console.info("HEALTH_CHECK", JSON.stringify({ githubApi: "ok", hasRuns: !!latest }));
      return Response.json({ watchdog: "online", githubApi: "ok", hasRuns: !!latest });
    } catch (err) {
      console.error("ERROR", "health_check", String(err.message));
      return Response.json({ watchdog: "degraded", githubApi: "error" }, { status: 503 });
    }
  }
};
