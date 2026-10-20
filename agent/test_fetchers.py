"""快速检查 4 个 Fetcher 是否能正常返回数据。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from proactive.fetchers.github_trending import fetch_github_trending
from proactive.fetchers.tavily_news import fetch_tavily
from proactive.fetchers.grok_x import fetch_grok_x
from proactive.fetchers.reddit import fetch_reddit

TESTS = [
    ("GitHub Trending", fetch_github_trending, {
        "id": "test_github", "queries": ["topic:llm"], "created_within_days": 90,
        "surge_min_stars": 200, "track_pool": 5, "top_n": 3,
    }),
    ("Tavily News", fetch_tavily, {
        "id": "test_tavily", "queries": ["AI model release"], "tavily_topic": "news",
        "search_depth": "basic", "include_raw_content": False, "days": 1, "max_results": 3,
    }),
    ("Grok/X", fetch_grok_x, {
        "id": "test_grok", "queries": ["AI news"], "max_results": 3,
        "importance_hint": "新模型、重大进展优先",
    }),
    ("Reddit", fetch_reddit, {
        "id": "test_reddit", "subreddits": ["LocalLLaMA"], "sort": "hot",
        "max_results": 3, "queries": ["new model"], "days": 2,
    }),
]

ok_count = 0
for name, fn, topic in TESTS:
    print(f"\n{'='*50}")
    print(f"🔍 测试: {name}")
    try:
        items = fn(topic)
        if items:
            print(f"  ✅ 成功，返回 {len(items)} 条")
            for i, it in enumerate(items[:2], 1):
                print(f"    [{i}] {it.get('title','(无标题)')[:70]}")
                print(f"        url: {it.get('url','')[:80]}")
            ok_count += 1
        else:
            print(f"  ⚠️  返回空列表（0条），可能有问题")
    except Exception as e:
        print(f"  ❌ 异常: {e}")

print(f"\n{'='*50}")
print(f"结果: {ok_count}/{len(TESTS)} 个 Fetcher 正常")
