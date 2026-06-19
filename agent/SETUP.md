# ProActive 配置指南

只需配两个文件：`.env`（密钥与渠道）和 `config.yaml`（话题与阈值）。
`.env` 在首次启动时已从模板自动生成，LLM 密钥已预填——所以**重点只有两步**。

---

## 第 0 步（必做）：确认模型 id —— 这是"全部被丢弃"的原因

你第一次跑全被丢弃，是因为判断层的 Gemini 模型 id 多半不对（`gemini-3.1-flash-lite`
这个名字在 API 里不一定存在），调用全失败 → 保守给 0 分 → 全丢。

在 agent 目录下运行（用 start.command 建好的虚拟环境）：

```bash
cd /Users/modern_yu/Agent/ProActive/agent
./.venv/bin/python list_models.py
```

它会打印「你的密钥真正能用的 Gemini 模型 id」+ 测试 grok 是否连通。
然后把 `config.yaml > models` 和 `quotas` 里的模型名，改成列表里真实存在的 id。例如若实际叫
`gemini-2.0-flash-lite` / `gemini-2.5-flash`，就照着改。**名字必须和列表完全一致。**

改完再 `./.venv/bin/python run.py once`，正常就会有内容被判为 push/digest 了。
若仍全失败，看终端新增的 `⚠ 判断失败 [...]:` 那行，它会告诉你真正的报错。

---

## 第 1 步：配一个收信渠道（`.env`）

`.env` 在 agent 目录下（隐藏文件，`open -e .env` 用文本编辑器打开）。三选一即可，先用邮件最省事。

### 方案 A · 邮件（推荐，最简单）
Gmail 不能用登录密码，要用「应用专用密码」：
1. 打开 Google 账号 → 安全性 → 开启「两步验证」（必须先开）。
2. 再进「应用专用密码」(App passwords)，生成一串 16 位密码。
3. 填进 `.env`：
   ```
   EMAIL_ENABLED=true
   SMTP_USER=surfingviking@gmail.com
   SMTP_PASS=刚生成的16位应用专用密码（去掉空格）
   EMAIL_TO=surfingviking@gmail.com
   ```

### 方案 B · Telegram
1. Telegram 里找 `@BotFather` → 发 `/newbot` → 拿到 bot token。
2. 给你的新 bot 发任意一条消息。
3. 浏览器打开 `https://api.telegram.org/bot<你的token>/getUpdates`，找到 `"chat":{"id":数字}`。
4. 填进 `.env`：
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=你的token
   TELEGRAM_CHAT_ID=上面的数字
   ```

### 方案 C · 网页 modernyu.org
生成 `index.html` + `feed.json`，把目录指向你网站发布目录（或之后用脚本同步）：
```
WEB_ENABLED=true
WEB_OUT_DIR=/你的网站/发布目录
```

> 三个可同时开。`.env` 改完保存即可，无需改代码。

---

## 第 2 步（可选）：调话题与灵敏度（`config.yaml`）

都已预填好，想微调时改这几处：

- **`user_profile`**：你的关注画像。判断层据此打分，写得越具体越贴心。
- **`thresholds.push` / `digest`**：默认 72 / 50。
  - 嫌太安静 → 把 `push` 调到 60–65。
  - 嫌太吵 → 调到 78–80。
- **`budget.max_instant_pushes_per_day`**：每天即时推送上限（默认 8），超出自动进摘要。
- **`topics[].queries`**：每个话题的搜索词，可增删。
- **`topics[].interval_min`**：轮询间隔（分钟）。突发类已设 20 分钟。

---

## 配好后怎么跑

```bash
./.venv/bin/python run.py once      # 先单跑一轮验证有内容、有推送
./.venv/bin/python run.py quota     # 看今天用了多少配额
```
没问题后，**双击 `start.command`** 常驻盯梢即可。

## 验证清单
- [ ] `list_models.py` 能列出 Gemini 模型，grok 返回 OK
- [ ] `config.yaml` 里的模型名 = 列表里的真实 id
- [ ] `.env` 至少开了一个渠道并填好凭据
- [ ] `run.py once` 有条目被判为 push 或 digest（不再全丢）
- [ ] 收到了一封测试邮件 / Telegram / 网页有内容
