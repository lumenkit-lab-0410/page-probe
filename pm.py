import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MAX_PAGES = 1
RAW_KEEP = 400000


def with_start(url, start):
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "start"]
    q.append(("start", str(start)))
    return urlunparse(p._replace(query=urlencode(q)))


def fetch_more(crawler, url, referer):
    crawler.slowdown.wait()
    h = crawler._headers()
    h.update({"Accept": "*/*", "Referer": referer, "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
              "Sec-Fetch-Site": "same-site"})
    h.pop("Upgrade-Insecure-Requests", None)
    r = crawler.session.get(url, headers=h, timeout=15)
    return r.status_code, r.text


def dest_map(bc, texts):
    from bs4 import BeautifulSoup
    out = {}
    for t in texts:
        for part in bc._html_parts(t) if t.lstrip()[:1] in "{[" else [t]:
            soup = BeautifulSoup(part, "lxml")
            for fr in soup.select("._fe_view_power_content"):
                d = fr.get("data-power-content-url") or ""
                links = bc._ad_links(fr)
                if links and d:
                    out[links[0]["href"].split("?", 1)[0]] = d
    return out


def one(kw, crawler, bc, keep_raw):
    from urllib.parse import quote
    html = crawler.fetch_search(kw)
    rec = {"화면길이": len(html)}
    try:
        read = bc.read_brand_ads(html)
    except bc.UnreadablePage as e:
        rec["브랜드칸"] = {"못읽음": str(e)}
        return rec
    more = read.get("더보기") or ""
    pages, raws, more_texts = [], [], []
    if more:
        if more.startswith("/"):
            more = "https://s.search.naver.com" + more
        referer = "https://search.naver.com/search.naver?query=" + quote(kw)
        start = int(dict(parse_qsl(urlparse(more).query)).get("start") or 1)
        total_before = len(read["광고"])
        cur = read
        for _ in range(MAX_PAGES):
            url = with_start(more, start)
            try:
                code, text = fetch_more(crawler, url, referer)
            except Exception as e:
                pages.append({"start": start, "오류": type(e).__name__})
                break
            if keep_raw:
                raws.append({"start": start, "code": code, "raw": text[:RAW_KEEP]})
            elif code == 200:
                more_texts.append(text)
            got = bc.add_more(cur, [text]) if code == 200 else cur
            new = len(got["광고"]) - len(cur["광고"])
            cards = 0
            try:
                for part in bc._html_parts(text):
                    from bs4 import BeautifulSoup
                    cards += len(bc._cards_in(BeautifulSoup(part, "lxml")))
            except Exception:
                pass
            pages.append({"start": start, "code": code, "길이": len(text), "카드": cards, "새광고": new})
            cur = got
            if code != 200 or cards == 0 or new == 0:
                break
            start += cards
        read = cur
        read["더보기열어봄"] = True
        read["더보기전광고수"] = total_before
    try:
        dm = dest_map(bc, [html] + [r["raw"] for r in raws] + more_texts)
        for ad in read.get("광고") or []:
            ad["연결"] = dm.get(ad.get("열쇠"), "")
    except Exception as e:
        rec["연결오류"] = type(e).__name__
    rec["브랜드칸"] = read
    rec["더보기쪽"] = pages
    if keep_raw:
        rec["더보기원문"] = raws
    return rec


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--base", type=float, default=4.0)
    p.add_argument("--raw", default="0")
    a = p.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("runner only", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib.net import Crawler, CrawlerError, SlowdownController, CircuitBreakerOpen
    from lib import bc
    sd = SlowdownController(base=a.base, max_=60.0)
    sd.ACCELERATION_FLOOR = 1.0
    crawler = Crawler(slowdown=sd)
    crawler.warmup()
    words = list(dict.fromkeys(json.loads(Path(a.targets).read_text(encoding="utf-8"))))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = bad = blocks = 0
    with out.open("a", encoding="utf-8") as f:
        for kw in words[:600]:
            rec = {"키워드": kw, "때": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            try:
                rec.update(one(kw, crawler, bc, a.raw == "1"))
                rec["성공"] = True
                ok += 1
                blocks = 0
            except CircuitBreakerOpen as e:
                rec.update({"성공": False, "까닭": "blocked", "막힘": True})
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                bad += 1
                break
            except Exception as e:
                rec.update({"성공": False, "까닭": type(e).__name__ + ": " + str(e)[:120]})
                bad += 1
                if isinstance(e, CrawlerError):
                    blocks += 1
                    if blocks >= 5:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        break
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
    print(f"{len(words)} / ok {ok} / failed {bad}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
