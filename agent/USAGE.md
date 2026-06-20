# ProActive 使用手册

主动型资讯监控 Agent：高频盯 4 类资讯 → 去重 → LLM 判断"值不值得打扰你" → Telegram/网页/邮件推送 → 后台自省层周期复盘并提改进建议。先本地自用，验证好用后再产品化。

---

## 一、当前生效配置（已跑通）

| 项 | 现状 |
|---|---|
| 判断层模型 | Gemini `gemini-3.1-flash-lite`（两个 key 约 600 次/天），逐级回退到 2.5-flash-lite / 2.5-flash / 3-flash-preview |
| 自省层模型 | grok `grok-4.20-fast`（流式）→ grok-non-reasoning →（兜底）Gemini 2.5-flash |
| 推送渠道 | ✅ Telegram、✅ 网页(`web_out/`)；邮件需填 Gmail 应用专用密码后才可用 |
| 监控话题 | GitHub AI Agent 热点 / 时政突发 / 科技AI / AI独角兽 |
| 新闻数据源 | **Tavily 搜索为主**(高频, 90-120min) + **grok 从 X 拉取为补充**(每天1次)；GitHub 走官方 Search API |
| 配额管理 | 本地按天计数 + 远端 429 兜底，绝不超配额 |

---

## 二、最常用：启动与停止

**正式常驻盯梢**（推荐）：双击 `start.command`（macOS）。首次自动建环境装依赖，之后按各话题间隔自动监控 + 每日自省，**关窗口即停**。
命令行等价：`./start.sh loop`。

**先单跑一轮看效果**：`./start.sh once` 或 `./.venv/bin/python run.py once`。

---

## 三、命令速查

所有命令在 `agent/` 目录下，用虚拟环境的 python：`./.venv/bin/python run.py <命令>`

| 命令 | 作用 | 何时用 |
|---|---|---|
| `once` | 跑一轮所有话题 | 测试 / 配合 cron |
| `loop` | 常驻，按各话题间隔自动调度 + 每日自省 | 正式盯梢（= start.command） |
| `test` | 向所有已启用渠道发一条测试消息 | 验证 Telegram/邮件/网页连通 |
| `digest` | 把"攒着"的内容汇总成每日摘要发出 | 每天定时 / 手动 |
| `review` | 复盘 + 改进建议 + 提议新「关注画像」 | 跑满一天后看效果 |
| `apply-profile` | 审批采纳自省层提议的新画像 | review 后觉得画像更新合理时 |
| `quota` | 看各模型配额 + 本月 Tavily 点数 | 担心配额时 |
| `feedback <item_id> <signal>` | 反馈 accepted/clicked/opened/ignored/rejected（同时更新来源采纳率）| 觉得某条推送好/不好 |

### 判断机制：两段式 + 个性化（越用越懂你）

- **两段式**：第一段标题+摘要批量**粗筛**（省调用），≥`triage_floor`(50) 才进第二段**读正文深判**（Tavily advanced 已带回正文，不额外抓页面），更准、理由有据。
- **来源采纳率先验**：每条反馈更新该来源滑动平均采纳率，判断分按它加减最多 ±15。常采纳的源升权、常忽略的降权。
- **自省重写画像**：`review` 基于反馈提议新 `user_profile` → `proposed_profile.txt`；`apply-profile` 采纳后写 `learned_profile.txt`，判断层优先用（删文件即回退）。
- **15% 探索名额**：即时推送留 15% 给"重要但被降权最多"的内容，防信息茧房。
- **限频/重试**：Gemini 按 `rate_limits`(设计 10 RPM/实际 15) 自动节流；429/网络异常自动等待重试（8/16/30/60s），重试耗尽才降级。

> 相关参数在 `config.yaml` 的 `judge` / `personalize` / `rate_limits` 段。

诊断脚本（不经 run.py）：`./.venv/bin/python list_models.py` —— 列出代理与 Gemini 上真实可用的模型 id，并自测 grok 连通。改完密钥/模型时用。

---

## 四、日常工作流

1. **平时**：双击 `start.command` 让它常驻；有达阈值的资讯就推到 Telegram，攒着的进每日摘要。
2. **跑满一天**：`run.py review` 看自省层的复盘——它判断自己在"乱发干扰"还是"贴心懂你"，并给改进建议（高风险建议需你点头）。
3. **觉得推送质量不对**：
   - 太吵 → `config.yaml` 里 `thresholds.push` 调高（如 78–80）。
   - 太安静 → 调低（如 60–65）。
   - 对单条表态 → `run.py feedback <item_id> rejected`，喂给自省层。
4. **想知道花了多少配额**：`run.py quota`。

---

## 五、配置文件

### `.env`（密钥与渠道，隐藏文件，`open -e .env` 编辑）
- **LLM**：Gemini 两个 key、grok 代理地址/密钥/模型/`GROK_STREAM=true`（必须流式，否则代理返回空）。
- **GitHub**：`GITHUB_TOKEN` 已配，提高 trending 抓取上限。
- **Tavily**：`TAVILY_API_KEY` 已配，新闻主力搜索源。
- **渠道开关**：`EMAIL_ENABLED` / `TELEGRAM_ENABLED` / `WEB_ENABLED`，以及各自凭据。三个可同时开。
- **要点**：`.env` 优先于 shell 环境变量（已设 `override=True`），所以以 `.env` 为准。`.env` 已在 `.gitignore`，**切勿提交**。

### `config.yaml`（话题与策略，改完无需动代码）
- `user_profile`：你的关注画像，判断层据此打分——写得越具体越贴心。
- `thresholds.push / digest`：推送/摘要的分数线（默认 72 / 50）。
- `budget.max_instant_pushes_per_day`：每天即时推送硬上限（默认 8），超出自动降级进摘要。
- `topics[].queries / interval_min`：每个话题的搜索词和轮询间隔。
- `models`：模型路由（judge / summarize / critic）。
- `quotas`：每个模型每日上限（每 key），本地计数用。
- `judge.batch_size`：一次 LLM 调用评分多少条（默认 15，越大越省调用）。

---

## 六、它如何省配额（重要机制）

免费配额很紧（flash-lite 300/key/天、2.5/3-flash 各 10/key/天、grok 40/天）。三招保证不爆：

1. **去重前置**：精确指纹 + 标题模糊匹配，已见过的根本不进 LLM（这就是为什么大多数轮次"新 0"）。
2. **批量判断**：一次调用评分 15 条，而非一条一次。
3. **配额感知调度**：每次调用前本地按天计数，自动挑还有额度的 key/模型；flash-lite 用尽才降级；远端返回 429 则本地立即标记用尽并降级。

> 配额是**本地记录**（`proactive.db`），按本地日期重置；远端 429 是真正的安全网。两层都在。

---

## 七、出问题怎么查

- **全被丢弃 / 0 推送**：多半是判断层 LLM 调用失败。看终端有没有 `⚠ 判断失败 [...]:` 那行，它会给真实报错（模型 id 错 / 配额尽 / 端点不通）。再跑 `list_models.py` 确认模型 id 与密钥。
- **邮件 535 BadCredentials**：`SMTP_PASS` 不是登录密码，要用 Gmail「应用专用密码」（先开两步验证）。或把 `EMAIL_ENABLED` 设 false。
- **grok 报 `Expecting value`**：代理需流式，确保 `.env` 里 `GROK_STREAM=true`。
- **密钥明明有效却报过期/无效**：可能 shell 里 export 了旧 key。已设 `.env` 优先；彻底干净可 `unset GEMINI_API_KEYS`。
- **某话题一直"新 0"**：正常，是去重生效，只评真正的新条目。
- **`[tavily]` 报错**：检查 `TAVILY_API_KEY` 与额度（dev key 有调用上限）。
- **grok-X 拉回为空 / `[grok_x]` 失败**：很可能你的代理未开启 xAI 实时 X 访问。不影响主流程——Tavily 是主力。要确认可单独看 `*_x` 话题那轮的输出。

## 数据源一览

| 话题 | 源 | 方式 | 频率 |
|---|---|---|---|
| GitHub AI Agent 热点 | GitHub Search API | 按星标搜 ai-agent 等 topic | 720min |
| 时政 / 科技AI / AI独角兽 | **Tavily**(主力) | 搜索 API, 返回正文+真实链接+时间 | 90-120min |
| 同上 | **grok-X**(补充) | grok 拉取过去24h X 热点 | 每天1次 |

> 两个源同名合并显示，去重会跨源合并同一事件。想加中文源/特定媒体，改 `config.yaml` 对应话题的 `queries` 即可。

**Tavily 月度额度（80% 硬控）**：每个搜索查询消耗 1 点。`.env` 里 `TAVILY_MONTHLY_CREDITS`(默认1000) × `TAVILY_BUDGET_RATIO`(默认0.8) = **800 点/月上限**，到顶自动暂停搜索到下月，绝不超额。当前三个 Tavily 话题的间隔（4h/8h/1天）约消耗 720 点/月，留有余量。`run.py quota` 会显示本月已用点数。想更频繁就升级 Tavily 套餐并调高 `TAVILY_MONTHLY_CREDITS`。

**Telegram 排版**：消息按话题加 emoji（🌍时政 🤖科技 🦄独角兽 🐙GitHub）、加粗标题直接可点、高分条目带 🔥、附理由与来源分数，已关闭链接大预览保持紧凑。

---

## 八、文件结构

```
agent/
  start.command / start.sh    # 一键启动
  run.py                      # 主入口(once/loop/digest/review/quota/test/feedback)
  list_models.py              # 诊断: 列模型 id + 测连通
  config.yaml                 # 话题与策略
  .env                        # 密钥与渠道(勿提交)
  proactive.db                # 本地记忆: 已见条目/判断/推送/反馈/配额/自省报告
  web_out/                    # 网页渠道产物(index.html + feed.json)
  proactive/
    llm.py        # 统一 LLM 客户端(配额感知 + grok流式 + 跨provider回退)
    pipeline.py   # 一轮编排: 采集→去重→硬规则→批量判断→分档
    fetchers/     # github_trending / news_rss 采集器
    judge.py      # 重要性打分(批量)
    critic.py     # 自省层(复盘+改进建议)
    dedup.py      # 去重(指纹+标题相似度)
    deliver/      # email / telegram / web 三渠道
    store.py      # SQLite 持久化
    render.py     # 渲染邮件HTML/纯文本/网页
```

---

## 九、可选增强（按需找我做）

- 网页端 👍/👎 反馈按钮，点一下回流给自省层。
- 自省层改进建议经确认后**自动改写** config。
- `start.command` 做成开机自启 / 后台常驻（launchd），不用一直开窗口。
- 配额按**太平洋时间**重置，与 Google 配额窗口对齐。
- 升级语义向量去重（替代标题模糊匹配）。
