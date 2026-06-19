# ProActive Agent

主动型资讯监控 Agent：高频盯 4 类资讯（GitHub AI Agent 热点 / 时政突发 / 科技AI / AI 独角兽）→ 去重 → LLM 判断"值不值得打扰你" → Telegram / 网页推送 → 后台自省层周期复盘，判断自己是在"乱发干扰"还是"贴心懂你"并提改进建议。

不只是抓取——核心是**判断层**（值不值得打扰你）。配额感知调度 + 批量判断 + 多源去重，在免费额度内做到高频盯梢。

## 快速开始

```bash
cd agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入你自己的密钥
python list_models.py          # 确认可用模型 id / 连通性
python run.py once             # 跑一轮看效果
```

本地一键常驻：双击 `agent/start.command`（macOS）。

## 文档

- `架构设计文档.md` — 七模块架构、数据流、演进路线
- `agent/使用手册.md` — 命令、配置、排错、数据源
- `agent/配置指南.md` — 密钥与渠道配置步骤
- `项目现状总结.md` — 当前实现状态一览

## 技术要点

- **数据源**：GitHub Search API、Tavily 搜索、grok 实时拉取 X。
- **判断层**：Gemini Flash 批量打分（相关度/新颖性/影响力/紧迫性）。
- **自省层**：grok 周期复盘推送质量并提改进建议。
- **成本控制**：Gemini 按天 + 远端 429 兜底；grok 40/天 + 空响应重试不计费；Tavily 月度 80% 硬控。

## 安全

所有密钥通过 `.env` 注入（已在 `.gitignore`，不进仓库）。`.env.example` 仅含占位符。

## 许可

私有项目，自用为主。
