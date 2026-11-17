import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SHOP = re.compile(r"smartstore\.naver\.com|brand\.naver\.com|shopping\.naver\.com|coupang\.com|link\.coupang|"
                  r"cafe24|imweb|godo|makeshop|sixshop|kakao\.com/_|pf\.kakao|oliveyoung|11st|gmarket|auction|"
                  r"shop|store|mall|\.co\.kr|\.com")
SKIP = re.compile(r"naver\.com/(?!.*smartstore)|pstatic|navercorp|naver\.net|w3\.org|schema\.org|google|facebook|instagram")


def compact(s):
    return re.sub(r"\s+", "", s or "")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.net import Crawler, SlowdownController
    from bs4 import BeautifulSoup
    sd = SlowdownController(base=4.0, max_=60.0)
    c = Crawler(slowdown=sd)
    c.warmup()
    items = json.loads(Path(a.targets).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for it in items:
            if isinstance(it, str):
                try:
                    it = json.loads(it)
                except ValueError:
                    continue
            title, name = it.get("t", ""), it.get("n", "")
            rec = {"n": name, "t": title}
            try:
                c.slowdown.wait()
                r = c.session.get("https://search.naver.com/search.naver",
                                  params={"ssc": "tab.blog.all", "query": title}, headers=c._headers(), timeout=15)
                soup = BeautifulSoup(r.text, "lxml")
                posts = []
                for el in soup.find_all("a", href=True):
                    h = el["href"]
                    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)", h)
                    if m and (m.group(1), m.group(2)) not in [x[:2] for x in posts]:
                        posts.append((m.group(1), m.group(2), el.get_text(" ", strip=True)[:80]))
                rec["후보"] = posts[:5]
                pick = None
                for bid, no, txt in posts:
                    if compact(title)[:10] and compact(title)[:10] in compact(txt):
                        pick = (bid, no, txt)
                        break
                if pick is None and posts:
                    pick = posts[0]
                if pick:
                    c.slowdown.wait()
                    u = f"https://m.blog.naver.com/{pick[0]}/{pick[1]}"
                    pr = c.session.get(u, headers=c._headers(), timeout=15)
                    ps = BeautifulSoup(pr.text, "lxml")
                    body = ps.select_one(".se-main-container") or ps
                    text = body.get_text(" ", strip=True)
                    links = []
                    for el in body.find_all("a", href=True):
                        h = el["href"]
                        host = urlparse(h).netloc
                        if host and not SKIP.search(h) and host not in links:
                            links.append(host)
                    shopl = [x for x in links if SHOP.search(x)]
                    rec.update({"글": u, "글제목": (ps.title.get_text(strip=True) if ps.title else "")[:100],
                                "바깥링크": links[:15], "가게링크": shopl[:10],
                                "구매말": sorted(set(re.findall(r"구매|주문|스토어|공식몰|최저가|할인|쿠폰|정품|판매|예약|진료|상담|내원|보험|렌탈|수강", text)))[:15],
                                "본문앞": text[:300], "본문끝": text[-300:]})
                rec["성공"] = True
            except Exception as e:
                rec.update({"성공": False, "까닭": type(e).__name__ + ": " + str(e)[:100]})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
