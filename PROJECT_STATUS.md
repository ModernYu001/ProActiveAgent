# ProActive 项目现状总结

> 更新：2026-06-20 ｜ 状态：**MVP 已跑通并常驻使用；已加两段式读正文 + 个性化学习**

主动型资讯监控 Agent：盯 4 类资讯 → 去重 → 两段式 LLM 判断（粗筛→读正文深判）→ 个性化排序 → Telegram/网页推送 → 后台自省层周期复盘并提议优化。先本地自用，验证后可产品化对 C 端发布。

---

## 一、整体状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 采集（4 类源） | ✅ 运行中 | GitHub / Tavily / grok-X 全部跑通 |
| 去重 | ✅ | URL 指纹 + 标题模糊匹配，跨源合并同一事件 |
| 判断层 | ✅ | **两段式**：批量粗筛 → 读正文深判 |
| 个性化（越用越懂你）| ✅ | 来源采纳率先验 + 自省重写画像 + 15% 探索名额 |
| 自省层（Critic） | ✅ | grok 主用 + Gemini 兜底；提议改进 + 新画像 |
| 推送渠道 | ✅ Telegram + 网页 ｜ ⏸ 邮件 | 默认每轮直发；邮件需填 Gmail 应用专用密码 |
| 配额/限频控制 | ✅ | Gemini 日额度 + RPM 节流 + 429 重试；grok / Tavily 各有守护 |
| 一键启动 | ✅ | 双击 `start.command` |

---

## 二、数据源现状

| 话题 | 源 | 频率 | 备注 |
|---|---|---|---|
| GitHub AI Agent 热点 | GitHub Search API | 12h | 按星标取 Top10 |
| 时政 / 突发 | Tavily advanced(主) + grok-X(补) | 2次/天 + 每天1次 | advanced 带回正文 |
| 科技 / AI 行业 | Tavily advanced(主) + grok-X(补) | 2次/天 + 每天1次 | |
| AI 独角兽 | Tavily advanced(主) + grok-X(补) | 2次/天 + 每天1次 | |

- **Tavily advanced** 模式直接带回 `raw_content`（正文），供第二段深判，无需额外抓网页。
- **grok-X** 经实测可实时访问 X；偶发空响应已加自动重试（最多 3 次，空响应不计配额）。

---

## 三、判断机制：两段式 + 个性化

**两段式判断**
1. 第一段（便宜）：标题+摘要**批量粗筛**，分数 ≥ `triage_floor`(50) 才进下一段。
2. 第二段（精读）：仅对通过者**读正文深判**，更准、推送理由有据可依。

**个性化（越用越懂你）**
- **来源采纳率先验**：每条反馈更新该来源的滑动平均采纳率（EMA）；判断分按它加减最多 ±15。常采纳的源升权、常忽略的降权。
- **自省重写画像**：`review` 基于反馈提议新 `user_profile` → `proposed_profile.txt`；`apply-profile` 审批后写 `learned_profile.txt`，判断层优先用（删文件即回退）。
- **15% 探索名额**：即时推送留 15% 给"重要但被个性化降权最多"的内容，防信息茧房。

---

## 四、模型路由现状

- **判断层（高频）**：Gemini `gemini-3.1-flash-lite`（两个 key ≈ 900 次/天预算），回退 2.5-flash-lite → 2.5-flash → 3-flash-preview。
- **自省层（低频）**：grok `grok-4.20-fast`（流式）→ grok-non-reasoning →（兜底）Gemini 2.5-flash。
- **grok-X 采集**：grok `grok-4.20-fast`，空响应自动重试。

> grok 调用必须流式（`GROK_STREAM=true`），否则代理返回空。

---

## 五、配额 / 限频 / 成本控制（核心）

| 资源 | 上限 | 机制 |
|---|---|---|
| Gemini 日额度 | flash-lite 450/key（×2≈900/天）；2.5/3-flash 各 10/key | 本地按天计数 + 远端 429 兜底，用尽自动降级 |
| Gemini 限频(RPM) | flash-lite 设计 10（实际 15）；2.5/3-flash 设计 3（实际 5） | 客户端自动节流 + **429/网络异常等待重试**（8/16/30/60s）|
| grok | 40 次/天 | 本地计数；空响应**不计**额度，最多重试 3 次 |
| Tavily | **800 点/月**（1000 × 80%）| 本地按月计数；advanced=2 点/查询，到顶暂停至下月 |

省配额：去重前置（多数轮次"新 0"）+ 两段式（只对粗筛通过者读正文）+ 配额感知调度 + RPM 节流。
两段式实测日均约 35–40 次 Gemini 调用（占 900 的 < 5%），瓶颈是 RPM 已由节流解决。
Tavily 当前 2次/天 advanced ≈ **720 点/月**，留余量。`run.py quota` 查实时用量。

---

## 六、当前关键参数（config.yaml）

- 阈值 `thresholds`：push 72 / digest 50；`judge.triage_floor`：50（进深判线）。
- 投递 `delivery.send_every_run`：true（**每轮直发**，不受每日预算限制）；`max_per_run`：15。
- 个性化 `personalize`：先验权重 15、EMA α 0.2、探索比例 0.15、探索门槛 80。
- 限频 `rate_limits`：见上表。
- 自省频率 `critic_interval_hours`：24。

---

## 七、常用命令

```bash
# 启动
双击 start.command                 # 常驻盯梢（= run.py loop）
./.venv/bin/python run.py once     # 单跑一轮（每轮结果直发 Telegram）

# 运维
run.py test           # 测各渠道连通(看 Telegram 排版)
run.py digest         # 把摘要队列发出
run.py review         # 自省复盘 + 改进建议 + 提议新画像
run.py apply-profile  # 采纳自省层提议的新画像(审批)
run.py quota          # 看 LLM 配额 + 本月 Tavily 点数
run.py feedback <item_id> <signal>   # 反馈(accepted/clicked/opened/ignored/rejected)
list_models.py        # 诊断模型 id / 连通性
```

---

## 八、已知限制

- 新闻非分钟级（受 Tavily 1000 点/月限制）；升级套餐 + 调高 `TAVILY_MONTHLY_CREDITS` 可恢复高频。
- 加了 RPM 节流后，单次 `once` 比以前慢（深判按 RPM 间隔，`loop` 后台无感）。
- 邮件渠道未启用（缺 Gmail 应用专用密码）。
- 去重为标题模糊匹配，未上向量语义去重。
- 反馈仍靠命令行手动打（网页/Telegram 一键反馈待做）。
- 单用户、配置在文件里（多用户/账号/付费属产品化阶段）。

---

## 九、可选增强（按需推进）

1. 网页/Telegram 端 👍/👎 一键反馈，点一下回流给个性化（**最该先做**，闭环关键）。
2. 自省的"改进建议"经确认后自动改写 config（画像已可自动，配置项还没）。
3. 开机自启 / 后台常驻（launchd），无需一直开窗口。
4. 配额按太平洋时间重置，与 Google/Tavily 窗口对齐。
5. 升级语义向量去重。
6. 新闻源加中文（`hl=zh-CN` 或中文 queries）/ 指定媒体。

---

## 十、文件位置

- 设计：`ARCHITECTURE.md`
- 工程：`agent/`（`USAGE.md`、`SETUP.md`、`config.yaml`、`.env`、`proactive/` 源码）
- 本地个性化状态（不进仓库）：`agent/learned_profile.txt`、`proposed_profile.txt`、`proactive.db`
