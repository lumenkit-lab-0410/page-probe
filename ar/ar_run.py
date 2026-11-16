"""카페 글 본문 열기 (서버 전용) — 목록 파일의 글 주소를 open_article 로 열어 본문 글자 · 댓글 · 글쓴이를 남긴다.
python ar/ar_run.py --targets plan/t0.json --out out/글.jsonl"""
import argparse, json, random, re, sys, time, html
sys.path.insert(0, "ar")
from curl_cffi import requests as cr
from open_article import Blocked, open_article, post_key

TAG = re.compile(r"<[^>]+>")


def text(h):
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", h or "")
    t = html.unescape(TAG.sub(" ", h))
    return re.sub(r"[ \t\u00a0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets"); ap.add_argument("--out")
    a = ap.parse_args()
    urls = json.load(open(a.targets, encoding="utf-8"))
    s = cr.Session(impersonate="chrome131")
    last = {}

    def get(api, headers):
        import os
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("서버에서만")
        r = s.get(api, headers=headers, timeout=25)
        last["b"] = r.text
        return r.status_code, r.text

    blocks = 0
    out = open(a.out, "w", encoding="utf-8")
    for i, u in enumerate(urls, 1):
        k = post_key(u)
        rec = {"글": f"{k[0]}/{k[1]}" if k else "", "주소": u.split("?")[0]}
        try:
            o = open_article(get, u, "", lambda: time.sleep(random.uniform(2.0, 3.5)))
        except Blocked as e:
            blocks += 1
            rec.update({"열림": False, "까닭": f"막힘 {e}", "일시": True})
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            if blocks >= 5:
                print("5연속 막힘 — 멈춤"); break
            time.sleep(30 * blocks); continue
        rec.update({"열림": o["열림"], "까닭": o.get("까닭", ""), "일시": bool(o.get("일시")) and not o["열림"], "연주소": o.get("연주소", "")})
        if o["열림"]:
            blocks = 0
            wr = {}
            try:
                j = json.loads(last.get("b") or "{}"); res = j.get("result", j)
                art = res.get("article") or {}
                w = art.get("writer") or {}
                wr = {"별명": w.get("nick") or w.get("nickname") or "", "아이디": (w.get("memberKey") or w.get("id") or "")[:12],
                      "등급": (w.get("memberLevelName") or (w.get("memberLevel") or {}).get("name") if isinstance(w.get("memberLevel"), dict) else w.get("memberLevelName") or "")}
                cm = res.get("comments") or {}
                items = cm.get("items") if isinstance(cm, dict) else cm
                cms = [{"쓴이": ((x.get("writer") or {}).get("nick") or ""), "글": text(str(x.get("content") or ""))[:300]} for x in (items or [])[:40]]
            except Exception as e:
                cms = [{"쓴이": "", "글": t[:300]} for t in (o.get("댓글") or [])[:40]]
            rec.update({"제목": o.get("제목", ""), "본문": text(o.get("본문", ""))[:4000], "댓글수": o.get("댓글수"),
                        "조회수": o.get("조회수"), "쓴때": o.get("쓴때", ""), "글쓴이": wr, "댓글": cms})
        out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
        if i % 20 == 0:
            time.sleep(random.uniform(8, 14))
    print("끝", i)


if __name__ == "__main__":
    main()
