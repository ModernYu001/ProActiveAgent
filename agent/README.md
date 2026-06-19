# ProActive — 主动型资讯监控 Agent (MVP)

按 [架构设计文档](../架构设计文档.md) 实现的可运行最小版本：高频盯 4 类资讯 → 去重 → LLM 判断"值不值得打扰你" → 多渠道推送 → 后台评判/自省层周期复盘，判断 agent 是在"乱发干扰"还是"贴心懂你"并提改进建议。

## 监控的 4 类话题（在 `config.yaml` 调整）
1. GitHub AI Agent 热点项目（GitHub Search API，按星标）
2. 时政 / 突发新闻（高频，20 分钟）
3. 全球科技 / AI 行业新闻
4. AI 独角兽新闻（融资 / 估值 / 并购）

## 一键启动（本地 / macOS）

预先把 `config.yaml`（话题、阈值）和 `.env`（密钥、渠道）设好后，**双击 `start.command`** 即可——首次会自动建虚拟环境、装依赖，之后直接常驻盯梢，关窗口即停。

```bash
# 首次需给脚本执行权限（只做一次）
chmod +x start.command start.sh
```

命令行等价：`./start.sh loop`（Linux 同样适用）。想先单跑一轮看效果：`./start.sh once`。

## 手动跑（开发调试）

```bash
cd agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 密钥已预填; 按需改 SMTP / Telegram
python list_models.py          # 确认可用的 Gemini 模型 id, 回填 config.yaml
python run.py once             # 跑一轮, 看终端输出
python run.py quota            # 看今天各模型用了多少配额
```

## 配额管理（关键）

你的免费配额很紧——每个 Gemini key：`3.1-flash-lite` 300/天、`2.5-flash` 与 `3-flash` 各 10/天；grok 40/天。系统用两招保证不爆：

1. **配额感知调度**：每次调用前本地按天计数，自动挑还有额度的 key/模型；`flash-lite` 用尽才降级到稀缺模型，全爆则本轮跳过（不误推）。两个 key 让 `flash-lite` 实际约 600 次/天。
2. **批量判断**：一次 LLM 调用评分 12 条（`config.yaml > judge.batch_size`），而不是一条一次。配合去重，日均判断调用通常只有几十次，远在配额内。

`python run.py quota` 随时查看用量。配额数字在 `config.yaml > quotas`，按你实测调整。

## 命令

| 命令 | 作用 |
|---|---|
| `python run.py once` | 跑一轮所有话题（cron 推荐） |
| `python run.py loop` | 常驻，按各话题间隔自动调度 + 周期自省 |
| `python run.py digest` | 把"攒着"的内容汇总成每日摘要发出 |
| `python run.py review` | 立刻运行评判/自省层，输出复盘报告 + 改进建议 |
| `python run.py quota` | 查看今天各模型/各 key 已用配额 |
| `python run.py feedback <item_id> <signal>` | 记录反馈：`accepted`/`opened`/`clicked`/`ignored`/`rejected` |

反馈是 agent 变贴心的燃料——你对推送的每次 `accepted`/`rejected`，都会成为评判层复盘的依据。

## 交付渠道（`.env` 里逐个开关）
- **邮件**：填 SMTP（Gmail 需用应用专用密码，不是登录密码）。
- **Telegram**：建一个 bot 拿 token，`TELEGRAM_CHAT_ID` 见 `telegram_ch.py` 注释。
- **网页 modernyu.org**：生成 `web_out/index.html` + `feed.json`，把 `WEB_OUT_DIR` 指向网站发布目录或用 CI 同步。

三个可同时开，达阈值的内容会一起投递。

## 部署成"高频盯梢"（在你的服务器上）

**方式 A · 常驻进程**（最贴合"高频"）：
```bash
nohup python run.py loop > logs/agent.log 2>&1 &
# 或写成 systemd service 常驻
```

**方式 B · cron**（更省心）：
```cron
*/20 * * * *  cd /path/to/agent && .venv/bin/python run.py once
0 8 * * *     cd /path/to/agent && .venv/bin/python run.py digest
0 9 * * *     cd /path/to/agent && .venv/bin/python run.py review
```

## 调判断质量（最关键的旋钮）
- `config.yaml > thresholds.push`：调高 = 更安静、更精；调低 = 更全、可能更吵。
- `config.yaml > budget.max_instant_pushes_per_day`：每天即时推送硬上限，超出自动降级进摘要。
- `config.yaml > user_profile`：你的关注画像，判断层据此打分——写得越具体越贴心。
- 跑几天后 `python run.py review`，让评判层告诉你哪个来源在制造噪音、阈值该怎么调。

## 模型路由（`config.yaml > models`）
- 判断层（高频）：Gemini `3.1-flash-lite` 优选，其余 3 个 flash 轮训回退。
- 评判/自省层（低频、要强推理）：grok 优选，失败回退 Gemini 3 Flash。
- 模型 id 以 `list_models.py` 在你服务器上实测到的为准（Gemini 3.x 命名可能与默认值不同，改 `config.yaml` 即可）。

## 安全
- `.env` 已在 `.gitignore` 里，**切勿提交**。
- 你曾在对话里明文贴过这些密钥，建议适时在各平台轮换一次。
- MVP 全是只读动作（抓取 + 提醒），不代你对外行动，天然安全。

## 已知边界（见架构文档"演进路线"）
- 去重为"URL 指纹 + 标题模糊匹配"，未做向量语义去重（产品化再升级）。
- 单用户、配置在文件里；多用户 / 账号 / 付费属产品化阶段。
- 评判层的改进建议目前是"输出给你审批"，未自动改写 `config.yaml`（防自我跑偏）。
