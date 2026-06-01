#!/usr/bin/env python3
"""Lead Hunter v2 — 多渠道获客监控 + 仪表盘数据
监控平台：GitHub, Reddit, Hacker News, V2EX
输出：stdout 供 cron 推送 + lead-data.json 供仪表盘
"""

import json, re, time, hashlib, os, sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

# 清代理（直连海外 API）
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy']:
    os.environ.pop(k, None)

# ─── 配置 ───────────────────────────────────
DATA_FILE = os.path.expanduser("/mnt/f/AI赚钱思路/获客/lead-data.json")
SEEN_FILE = os.path.expanduser("~/.hermes/data/lead-hunter-seen-v2.json")
STATE_FILE = os.path.expanduser("~/.hermes/data/lead-hunter-state.json")
MIN_SCORE = 30

CHANNELS = {
    "github":   {"active": True,  "risk": "低", "desc": "GitHub Issues (bounty/help-wanted)"},
    "reddit":   {"active": True,  "risk": "低", "desc": "Reddit r/forhire r/freelance"},
    "hn":       {"active": True,  "risk": "低", "desc": "Hacker News"},
    "v2ex":     {"active": False, "risk": "低", "desc": "V2EX 求职/外包节点"},
    "zhihu":    {"active": False, "risk": "中", "desc": "知乎 (需浏览器)"},
    "xhs":      {"active": False, "risk": "高", "desc": "小红书 (需反爬)"},
    "weibo":    {"active": False, "risk": "中", "desc": "微博 (需API/浏览器)"},
    "douyin":   {"active": False, "risk": "高", "desc": "抖音 (需APP模拟)"},
}

BIZ_KEYWORDS = {
    "AI Agent开发":    ["ai agent", "智能体", "langchain", "autogpt", "openai api", "llm"],
    "自动化工作流":     ["automation", "workflow", "n8n", "make.com", "zapier", "自动化"],
    "Web全栈":         ["full stack", "react", "next.js", "fastapi", "django", "全栈"],
    "数据采集":         ["web scraping", "scraper", "crawler", "爬虫", "采集", "数据"],
    "API集成":         ["api integration", "api对接", "接口", "webhook", "rest"],
    "微信机器人":       ["wechat bot", "微信机器人", "公众号", "企业微信"],
    "Chrome插件":      ["chrome extension", "浏览器插件", "插件开发"],
    "SaaS MVP":        ["saas", "mvp", "prototype", "创业", "startup"],
    "Discord/Telegram Bot": ["discord bot", "telegram bot", "bot开发"],
}

SKILLS = [kw for v in BIZ_KEYWORDS.values() for kw in v]
BLACKLIST = ["blockchain", "crypto", "nft", "web3", "token", "solidity",
             "onlyfans", "adult", "casino", "gambling"]

# ─── 工具 ───────────────────────────────────
def load_json(path, default=None):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f: json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_json(url):
    h = {"User-Agent": "LeadHunter/2.0", "Accept": "application/json"}
    for attempt in range(3):
        try:
            req = Request(url, headers=h)
            with urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except: time.sleep(2 ** attempt)
    return None

def score(text):
    t = text.lower()
    s = sum(10 for kw in SKILLS if kw in t)
    s -= sum(40 for kw in BLACKLIST if kw in t)
    s += sum(3 for w in ["budget","$","pay","hourly","quote","rate","💰","预算","报酬"] if w in t.lower())
    s += sum(5 for w in ["urgent","asap","急","立即"] if w in t.lower())
    return min(max(s, 0), 100)

def classify(text):
    t = text.lower()
    best, best_s = "其他", 0
    for biz, kws in BIZ_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in t)
        if hits > best_s: best, best_s = biz, hits
    return best

def mid(source, item_id):
    return hashlib.md5(f"{source}:{item_id}".encode()).hexdigest()[:12]

# ─── 采集器 ─────────────────────────────────
def hunt_github():
    results = []
    queries = ["help wanted ai", "help wanted automation", "help wanted python",
               "good first issue ai", "bounty issue"]
    for q in queries:
        data = fetch_json(f"https://api.github.com/search/issues?q={quote(q)}+is:open+is:issue&sort=updated&per_page=10")
        if not data: continue
        for i in data.get("items", []):
            tid = mid("github", str(i["id"]))
            t = i.get("title","")
            b = i.get("body","") or ""
            s = score(f"{t} {b}")
            labels = [l["name"] for l in i.get("labels",[])]
            if "bounty" in str(labels).lower(): s += 30
            if s >= MIN_SCORE:
                results.append({"id":tid,"source":"github","title":t,"body":b[:300],
                    "url":i["html_url"],"score":min(s,100),"bizType":classify(f"{t} {b}"),
                    "time":i.get("updated_at","")[:16],"status":"new"})
        time.sleep(1.5)
    return results

def hunt_reddit():
    results = []
    for sub in ["forhire", "freelance"]:
        try:
            data = fetch_json(f"https://www.reddit.com/r/{sub}/new.json?limit=25&raw_json=1")
            if not data: continue
            for p in data.get("data",{}).get("children",[]):
                d = p["data"]
                pid = mid("reddit", d["id"])
                t, b = d.get("title",""), d.get("selftext","")[:500]
                s = score(f"{t} {b}")
                if s >= MIN_SCORE and "[hiring]" in t.lower():
                    results.append({"id":pid,"source":"reddit","title":t,"body":b[:300],
                        "url":f"https://reddit.com{d.get('permalink','')}","score":s,
                        "bizType":classify(f"{t} {b}"),
                        "time":datetime.fromtimestamp(d["created_utc"],tz=timezone.utc).strftime("%m-%d %H:%M"),
                        "status":"new"})
            time.sleep(1.5)
        except Exception as e:
            print(f"    ⚠ Reddit/{sub}: {e}", file=sys.stderr)
    return results

def hunt_hn():
    results = []
    for q in ["freelancer", "seeking freelancer", "hiring developer", "who can build"]:
        data = fetch_json(f"https://hn.algolia.com/api/v1/search?query={quote(q)}&tags=story,ask_hn&hitsPerPage=15")
        if not data: continue
        for h in data.get("hits",[]):
            hid = mid("hn", h["objectID"])
            t, b = h.get("title",""), h.get("story_text","") or ""
            s = score(f"{t} {b}")
            if s >= MIN_SCORE:
                results.append({"id":hid,"source":"hn","title":t,"body":b[:300],
                    "url":f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "score":s,"bizType":classify(f"{t} {b}"),
                    "time":h.get("created_at","")[:16],"status":"new"})
        time.sleep(1)
    return results

# ─── 主流程 ─────────────────────────────────
def main():
    seen = set(load_json(SEEN_FILE) or [])
    state = load_json(STATE_FILE) or {"total_scanned":0,"total_matched":0,"total_replied":0,"total_converted":0}
    all_leads = load_json(DATA_FILE) or {"stats":state,"leads":[]}
    existing = all_leads.get("leads",[])

    print("🔍 Lead Hunter v2 启动...", file=sys.stderr)
    new_count = 0

    for name, func in [("GitHub", hunt_github), ("Reddit", hunt_reddit), ("HN", hunt_hn)]:
        chan = CHANNELS.get(name.lower(),{})
        if not chan.get("active",True): continue
        print(f"  📡 {name}...", file=sys.stderr)
        try:
            results = func()
            ch_new = 0
            for r in results:
                state["total_scanned"] += 1
                if r["id"] not in seen:
                    seen.add(r["id"])
                    existing.insert(0, r)
                    state["total_matched"] += 1
                    new_count += 1
                    ch_new += 1
            print(f"     {len(results)}条, {ch_new}新匹配", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ {name}: {e}", file=sys.stderr)
        # 每渠道保存一次，防止超时丢数据
        existing = existing[:500]
        save_json(SEEN_FILE, list(seen))
        save_json(STATE_FILE, state)
        all_leads = {"stats": state, "leads": existing, "channels": CHANNELS,
                     "keywords": {"hot": list(BIZ_KEYWORDS.keys()), "skills": SKILLS},
                     "updated": datetime.now(timezone.utc).isoformat()}
        save_json(DATA_FILE, all_leads)

    if new_count == 0:
        print("[SILENT]")
        return

    new = [l for l in existing if l["status"]=="new"][:10]
    print(f"\n🎯 本轮发现 {new_count} 个新线索 (累计匹配 {state['total_matched']}):\n")
    for i, l in enumerate(new, 1):
        e = "🔥" if l["score"]>=70 else "⭐" if l["score"]>=50 else "💡"
        print(f"{e} [{l['score']}] {l['source']} | {l['bizType']} | {l['time']}")
        print(f"   {l['title'][:100]}")
        print(f"   🔗 {l['url']}")

if __name__ == "__main__":
    main()
