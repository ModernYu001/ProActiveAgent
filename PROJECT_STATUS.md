# ProActive 项目现状总结

> 更新：2026-06-19 ｜ 状态：**MVP 已跑通，可正式常驻使用**

主动型资讯监控 Agent：高频盯 4 类资讯 → 去重 → LLM 判断"值不值得打扰你" → Telegram/网页推送 → 后台自省层周期复盘。先本地自用，验证后可产品化对 C 端发布。

---

## 一、整体状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 采集（4 类源） | ✅ 运行中 | GitHub / Tavily / grok-X 已全部跑通 |
| 去重 | ✅ | URL 指纹 + 标题模糊匹配，跨源合并同一事件 |
| 判断层（打分） | ✅ | Gemini 批量打分，正常推送/摘要/丢弃分档 |
| 自省层（Critic） | ✅ | grok 主用 + Gemini 兜底 |
| 推送渠道 | ✅ Telegram + 网页 ｜ ⏸ 邮件 | 邮件需填 Gmail 应用专用密码 |
| 配额/成本控制 | ✅ | Gemini / grok / Tavily 三套额度均已守护 |
| 一键启动 | ✅ | 双击 `start.command` |

---

## 二、数据源现状

| 话题 | 源 | 频率 | 备注 |
|---|---|---|---|
| GitHub AI Agent 热点 | GitHub Search API | 12h | 按星标取 Top10 |
| 时政 / 突发 | Tavily(主) + grok-X(补) | 4h / 每天1次 | |
| 科技 / AI 行业 | Tavily(主) + grok-X(补) | 8h / 每天1次 | |
| AI 独角兽 | Tavily(主) + grok-X(补) | 1天 / 每天1次 | |

grok-X 经实测**可实时访问 X**；偶发空响应已加"最多重试 3 次"。

---

## 三、模型路由现状

- **判断层（高频）**：Gemini `gemini-3.1-flash-lite`（两个 key ≈ 600 次/天），回退 2.5-flash-lite → 2.5-flash → 3-flash-preview。
- **自省层（低频）**：grok `grok-4.20-fast`（流式）→ grok-non-reasoning →（兜底）Gemini 2.5-flash。
- **grok-X 采集**：grok `grok-4.20-fast`，空响应自动重试。

> grok 调用必须流式（`GROK_STREAM=true`），否则代理返回空。

---

## 四、配额与成本控制（核心）

| 资源 | 上限 | 机制 |
|---|---|---|
| Gemini | 各模型每 key/天（lite 300、2.5/3-flash 各 10） | 本地按天计数 + 远端 429 兜底，用尽自动降级 |
| grok | 40 次/天 | 本地计数；空响应**不计**额度，最多重试 3 次 |
| Tavily | **800 点/月**（1000 × 80%） | 本地按月计数，每查询 1 点，到顶暂停至下月 |

省配额三招：去重前置（多数轮次"新 0"）、判断层批量打分（15 条/次）、配额感知调度。
当前 Tavily 间隔（4h/8h/1天）约 **720 点/月**，留有余量。`run.py quota` 可查实时用量。

---

## 五、当前关键参数（config.yaml）

- 推送阈值 `thresholds`：push 72 / digest 50。
- 打扰预算 `budget.max_instant_pushes_per_day`：8（滚动 24h；超出降级进每日摘要）。
- 判断批大小 `judge.batch_size`：15。
- 自省频率 `critic_interval_hours`：24。

---

## 六、常用命令

```bash
# 启动
双击 start.command            # 常驻盯梢（= run.py loop）
./.venv/bin/python run.py once    # 单跑一轮

# 运维
run.py test       # 测各渠道连通(看 Telegram 排版)
run.py digest     # 把摘要队列发出
run.py review     # 自省复盘 + 改进建议
run.py quota      # 看 LLM / Tavily 用量
run.py feedback <item_id> <signal>   # 反馈喂给自省层
list_models.py    # 诊断模型 id / 连通性
```

---

## 七、已知限制

- 新闻非分钟级（受 Tavily 1000 点/月限制）；升级套餐 + 调高 `TAVILY_MONTHLY_CREDITS` 可恢复高频。
- 邮件渠道未启用（缺 Gmail 应用专用密码）。
- 去重为标题模糊匹配，未上向量语义去重。
- 自省层改进建议为"输出待你审批"，未自动改写 config。
- 单用户、配置在文件里（多用户/账号/付费属产品化阶段）。

---

## 八、可选增强（按需推进）

1. 网页端 👍/👎 反馈按钮，点一下回流给自省层。
2. 自省建议经确认后自动改写 config。
3. 开机自启 / 后台常驻（launchd），无需一直开窗口。
4. 配额按太平洋时间重置，与 Google/Tavily 窗口对齐。
5. 升级语义向量去重。
6. 新闻源加中文（`hl=zh-CN` 或中文 queries）/ 指定媒体。

---

## 九、文件位置

- 设计：`架构设计文档.md`
- 工程：`agent/`（`使用手册.md`、`配置指南.md`、`config.yaml`、`.env`、`proactive/` 源码）
