"""推文草稿生成：每轮推送后, 把最高分条目改写成中文 X(推特)草稿, 发到 Slack 供人工挑选。

只生成草稿、绝不自动发推——判断和人味留给人, 苦力给机器。
配置见 config.yaml 的 drafts 段; 模型走 models.drafts(缺省用 models.summarize 路由)。
"""
from __future__ import annotations

from .deliver.slack_ch import send_slack

SYSTEM = """你是一个中文科技类 X(推特)账号的写手。基于给定的真实资讯素材写推文草稿。

X 算法口味(按此优化, 这是实证规律):
- 回复的权重是点赞的十几倍, 作者参与的对话权重更高 → 每条必须留"可回复的口子":
  鲜明立场、可反驳的判断、或结尾一个具体问题(不要"你怎么看"这种空泛问法)
- 信息流只显示前 1-2 行 → 第一行必须是钩子: 反直觉结论 / 具体数字 / 冲突对比,
  绝不用"今天分享一个…"式开头
- 转发动机是"替我说话"或"值得存" → 提供可收藏的干货密度(具体数字、实体名、清单),
  或一句让人想引用的锐评
- 正文带外链触达直接砍半 → 正文绝不放链接, 来源链接单独标注、发布时贴在评论区

硬性要求:
- 只使用素材中给出的事实, 严禁编造数字、调研、案例或引语; 观点可以尖锐, 事实必须有源
- 每条不超过 240 字, 中文口语化, 短句多留白, 一条只讲一个点
- 不用 hashtag, 不堆 emoji, 不做标题党(钩子必须被素材事实支撑)
- 禁用 AI 味口水词: 炸裂、刷新认知、格局、赛道、狂热、掰手腕、重磅、天花板、拉满
- 不要自行做倍数、排名、增长率等换算或跨素材对比——只引用素材里原有的数字
- 三条草稿的结构和结尾必须各不相同: 一条以锐利判断收尾、一条以具体问题收尾、
  一条以"这意味着什么"的推演收尾; 不要每条都用"你觉得…吗?"

输出格式: 每条草稿 = 正文, 然后单独一行"评论区补链: <来源URL>"。
草稿之间用单独一行 --- 分隔, 不要编号和其他说明文字。"""


def make_drafts(llm, cfg: dict, items: list[dict]) -> bool:
    """从本轮推送条目中取最高分几条 → LLM 写 N 条草稿 → 发 Slack。返回是否成功。"""
    dcfg = cfg.get("drafts", {})
    if not dcfg.get("enabled", False) or not items:
        return False
    n = dcfg.get("count", 3)
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    top = top[: dcfg.get("max_source_items", 6)]
    material = "\n\n".join(
        f"[{i.get('topic_name', '')}] ★{i.get('score', 0)} {i['title']}\n"
        f"{i.get('summary') or i.get('reason', '')}\n{i['url']}"
        for i in top
    )
    user = (f"以下是今天筛出的高价值资讯素材：\n\n{material}\n\n"
            f"从中挑最适合发推的角度，写 {n} 条草稿。")
    route = cfg.get("models", {}).get("drafts") or cfg["models"]["summarize"]
    try:
        text = llm.complete(route, SYSTEM, user, temperature=0.7, max_tokens=4000)
    except Exception as e:  # noqa: BLE001
        print(f"[drafts] 生成失败: {e}")
        return False
    ok = send_slack(text.strip(), f"✍️ 今日推文草稿 ×{n}（挑一条、改两个字再发）")
    print(f"[drafts] 草稿已发 Slack: {ok}")
    return ok
