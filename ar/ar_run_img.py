"""카페 글 본문 열기 + 댓글 전부 + 본문 · 댓글 사진(작은 그림 w300 · 1117 키워드 보충 창 갈래 art-open-img-bc · art-open-cm 바탕)
(둘째 쪽부터 이어 받기 · 1116 네일샵 마무리 창이 만든 갈래 art-open-cm) (서버 전용) — 목록 파일의 글 주소를 open_article 로 열어 본문 글자 · 댓글 · 글쓴이를 남긴다.
python ar/ar_run.py --targets plan/t0.json --out out/글.jsonl"""
import argparse, json, random, re, sys, time, html
sys.path.insert(0, "ar")
from curl_cffi import requests as cr
from open_article import Blocked, open_article, post_key

TAG = re.compile(r"<[^>]+>")
IMG = re.compile(r"(?is)<img\s[^>]*>")
SRC = re.compile(r'(?i)(?:data-lazy-src|data-src|src)\s*=\s*"([^"]+)"')
import os, urllib.request
PIC = {"n": 0}


def okpic(u):
    u = html.unescape(u or "")
    if not u.startswith("http") or "pstatic.net" not in u and "phinf" not in u:
        return ""
    if "storep-phinf" in u or "sticker" in u.lower() or "emoticon" in u.lower():
        return ""
    return u


def thumb(u):
    b = u.split("?")[0]
    return b + "?type=w300"


def save(u, path):
    try:
        req = urllib.request.Request(thumb(u), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://cafe.naver.com/"})
        with urllib.request.urlopen(req, timeout=20) as r:
            b = r.read()
        if len(b) < 800:
            return False
        open(path, "wb").write(b); PIC["n"] += 1
        return True
    except Exception:
        return False


def body_pics(h):
    """본문 HTML 의 사진을 [사진n] 표시로 바꾸고 주소 목록을 돌려준다."""
    urls = []
    def rep(m):
        src = SRC.findall(m.group(0))
        u = next((okpic(x) for x in src if okpic(x)), "")
        if not u:
            return " "
        urls.append(u)
        return f" [사진{len(urls)}] "
    return IMG.sub(rep, h or ""), urls


def find_urls(x, depth=0):
    """댓글 한 개(dict)에서 사진 주소(스티커 빼고)."""
    out = []
    if depth > 4:
        return out
    if isinstance(x, dict):
        for k, v in x.items():
            kl = str(k).lower()
            if "sticker" in kl or "writer" in kl or "profile" in kl:
                continue
            if isinstance(v, str) and ("image" in kl or "url" in kl or "path" in kl) and okpic(v):
                out.append(okpic(v))
            elif isinstance(v, (dict, list)):
                out += find_urls(v, depth + 1)
    elif isinstance(x, list):
        for v in x:
            out += find_urls(v, depth + 1)
    return list(dict.fromkeys(out))


def text(h):
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", h or "")
    t = html.unescape(TAG.sub(" ", h))
    return re.sub(r"[ \t\u00a0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


ARTQ = re.compile(r"[?&]art=([^&#]+)")
CM_ENDS = [
    ("v2", "https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{c}/articles/{a}/comments/pages/{p}?requestFrom=A&orderBy=asc{art}", {}),
    ("v4", "https://article.cafe.naver.com/gw/v4/cafes/{c}/articles/{a}/comments/pages/{p}?requestFrom=A&orderBy=asc{art}", {"x-cafe-product": "mweb", "origin": "https://m.cafe.naver.com"}),
]
GOOD = {}


def more_comments(get, url, cafe_id, aid, cms, seen, want):
    """댓글 둘째 쪽부터 끝까지. 맞는 주소를 찾으면 그 주소만 쓴다. 돌려주는 값 = 기록(어느 주소 · 몇 쪽 · 몇 개)."""
    m = ARTQ.search(url); artq = f"&art={m.group(1)}" if m else ""
    log = []
    ends = [e for e in CM_ENDS if e[0] == GOOD.get("e")] or CM_ENDS
    for name, tpl, hd in ends:
        got_any = False
        for p in range(1, 40):
            time.sleep(random.uniform(1.2, 2.2))
            try:
                st, body = get(tpl.format(c=cafe_id, a=aid, p=p, art=artq), {"Referer": url, **hd})
            except Exception as e:
                log.append(f"{name} p{p} {type(e).__name__}"); break
            if st != 200:
                log.append(f"{name} p{p} HTTP {st}"); break
            try:
                j = json.loads(body); r = j.get("result", j); c = r.get("comments", r)
                its = c.get("items") if isinstance(c, dict) else c
            except Exception:
                log.append(f"{name} p{p} 못 읽음"); break
            new = 0
            for i, x in enumerate(its or []):
                kx = str(x.get("id") or x.get("commentId") or f"{p}-{i}")
                if kx in seen: continue
                seen.add(kx); new += 1
                cms.append({"쓴이": ((x.get("writer") or {}).get("nick") or ""), "글": text(str(x.get("content") or ""))[:1000], "사진주소": find_urls(x)})
            if new: got_any = True
            if not its or (new == 0 and p > 1) or len(cms) >= want or len(cms) >= 400:
                break
        log.append(f"{name} 받은 댓글 {len(cms)}/{want}")
        if got_any or len(cms) >= want:
            GOOD["e"] = name; break
    return " · ".join(log)


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
                cms = [{"쓴이": ((x.get("writer") or {}).get("nick") or ""), "글": text(str(x.get("content") or ""))[:1000], "사진주소": find_urls(x)} for x in (items or [])]
                seen = {str(x.get("id") or x.get("commentId") or i) for i, x in enumerate(items or [])}
                rec["댓글칸"] = sorted(cm.keys()) if isinstance(cm, dict) else type(cm).__name__
                want = int(o.get("댓글수") or 0)
                cafe_id = str(res.get("cafeId") or art.get("cafeId") or "")
                if want > len(cms) and cafe_id:
                    rec["댓글_더받음"] = more_comments(get, u, cafe_id, k[1], cms, seen, want)

            except Exception as e:
                cms = [{"쓴이": "", "글": t[:300]} for t in (o.get("댓글") or [])[:40]]
                rec["댓글오류"] = repr(e)[:200]
            bh, burls = body_pics(o.get("본문", ""))
            d = os.path.join(os.path.dirname(a.out) or ".", "사진", rec["글"].replace("/", "_")); pics = []
            os.makedirs(d, exist_ok=True)
            for n, pu in enumerate(burls[:8], 1):
                fn = f"b{n}.jpg"
                if save(pu, os.path.join(d, fn)): pics.append({"자리": f"본문 [사진{n}]", "파일": fn})
            cn = 0
            for ci, c in enumerate(cms, 1):
                us = c.pop("사진주소", []) if isinstance(c, dict) else []
                if us:
                    c["글"] = "[댓글사진] " + c.get("글", "")
                for m_, pu in enumerate(us[:2], 1):
                    if cn >= 10: break
                    fn = f"c{ci}_{m_}.jpg"
                    if save(pu, os.path.join(d, fn)): pics.append({"자리": f"댓글 {ci}번({c.get('쓴이','')})", "파일": fn}); cn += 1
            rec.update({"사진": pics, "본문사진수": len(burls), "댓글사진수": sum(1 for c in cms if isinstance(c, dict) and c.get("글", "").startswith("[댓글사진]"))})
            rec.update({"제목": o.get("제목", ""), "본문": text(bh)[:4000], "댓글수": o.get("댓글수"),
                        "조회수": o.get("조회수"), "쓴때": o.get("쓴때", ""), "글쓴이": wr, "댓글": cms})
        out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
        if i % 20 == 0:
            time.sleep(random.uniform(8, 14))
    print("끝", i, "사진", PIC["n"])


if __name__ == "__main__":
    main()
