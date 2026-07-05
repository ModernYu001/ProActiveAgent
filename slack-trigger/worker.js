/**
 * Slack 斜杠命令 → 触发 GitHub Actions workflow 的中转 Worker。
 *
 * 支持命令:
 *   /proactive  → ProActiveAgent 仓库跑一轮资讯
 *   /ytreport   → SlackYT 仓库发一次 YouTube 日报
 *
 * 需要两个 Secret(在 Worker 的 Settings → Variables and Secrets 里配):
 *   GH_PAT                GitHub fine-grained PAT, 只需 Actions: Read and write
 *   SLACK_SIGNING_SECRET  Slack App 的 Signing Secret, 用于验证请求真的来自你的 Slack
 */

const ROUTES = {
  "/proactive": {
    repo: "ModernYu001/ProActiveAgent",
    workflow: "proactive.yml",
    label: "ProActive 资讯轮",
  },
  "/ytreport": {
    repo: "ModernYu001/SlackYT",
    workflow: "daily.yml",
    label: "YouTube 日报",
  },
};

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("slack-trigger worker: alive");
    }
    const body = await request.text();

    // ---- 1. 验证 Slack 签名(防止任何知道 URL 的人乱触发) ----
    const ts = request.headers.get("X-Slack-Request-Timestamp") || "";
    const sig = request.headers.get("X-Slack-Signature") || "";
    if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) {
      return new Response("stale request", { status: 401 });
    }
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw", enc.encode(env.SLACK_SIGNING_SECRET),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
    );
    const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`v0:${ts}:${body}`));
    const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
    if (`v0=${hex}` !== sig) {
      return new Response("bad signature", { status: 401 });
    }

    // ---- 2. 按命令路由, 调 GitHub API 触发 workflow ----
    const cmd = new URLSearchParams(body).get("command");
    const route = ROUTES[cmd];
    if (!route) {
      return slackReply(`未知命令: ${cmd}`);
    }
    const gh = await fetch(
      `https://api.github.com/repos/${route.repo}/actions/workflows/${route.workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GH_PAT}`,
          "Accept": "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "slack-trigger-worker",
        },
        body: JSON.stringify({ ref: "main" }),
      },
    );
    if (gh.status === 204) {
      return slackReply(`🚀 已触发「${route.label}」，结果一两分钟后到频道。`);
    }
    return slackReply(`❌ 触发失败 HTTP ${gh.status}: ${(await gh.text()).slice(0, 200)}`);
  },
};

function slackReply(text) {
  // ephemeral = 只有敲命令的人自己看得见, 不刷屏
  return new Response(
    JSON.stringify({ response_type: "ephemeral", text }),
    { headers: { "Content-Type": "application/json" } },
  );
}
