# 쿠팡 검색 결과 위 상품 받기 — 키워드마다 새 브라우저 · 새 문맥(쿠키 · 기록 없음 = 시크릿)
import json, time, random, argparse
from pathlib import Path
from urllib.parse import quote

ap = argparse.ArgumentParser()
ap.add_argument("--targets", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--mode", default="pw")   # pw | probe
ap.add_argument("--top", type=int, default=20)
a = ap.parse_args()
words = json.loads(Path(a.targets).read_text(encoding="utf-8"))
out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
fo = out.open("a", encoding="utf-8")


def w(o):
    fo.write(json.dumps(o, ensure_ascii=False) + "\n"); fo.flush()


EXTRACT = r"""
(top) => {
  const lis = [...document.querySelectorAll('#product-list > li, ul#productList > li, li[class*=ProductUnit_productUnit], li.search-product')];
  const txt = document.body ? document.body.innerText : '';
  let brands = [];
  const bi = txt.indexOf('\n브랜드\n');
  if (bi >= 0) brands = txt.slice(bi + 5, bi + 800).split('\n').map(s => s.trim()).filter(s => s && s.length < 30).slice(0, 40);
  const rows = lis.slice(0, top).map((li, i) => {
    const t = (li.innerText || '').replace(/\s+/g, ' ').trim();
    const nameEl = li.querySelector('[class*=productName], .name');
    const img = li.querySelector('img');
    const rcEl = li.querySelector('[class*=ratingCount], .rating-total-count, [class*=RatingCount]');
    const rc = rcEl ? rcEl.innerText : ((t.match(/\((\d[\d,]*)\)/) || [])[1] || '');
    const adEl = li.querySelector('[class*=AdMark], .ad-badge, [class*=adMark], [class*=ad-badge]');
    const imgs = [...li.querySelectorAll('img')].map(x => (x.alt || '') + ' ' + (x.src || '')).join(' ');
    const rocket = /rocket|로켓/i.test(imgs) || /로켓/.test(t);
    const rocketKind = (imgs.match(/(logo_rocket[^. "]*|rocket[_-][a-z_]+|로켓[가-힣]+)/i) || [])[0] || '';
    const priceEl = li.querySelector('[class*=Price_priceValue], strong.price-value, [class*=priceValue]');
    const an = li.querySelector('a[href]');
    return {
      순서: i + 1,
      이름: (nameEl ? nameEl.innerText : (img ? img.alt : t.slice(0, 80))).trim().slice(0, 160),
      리뷰: String(rc).replace(/[^\d]/g, ''),
      광고: (adEl || /(^| )광고( |$)/.test(t)) ? '광고' : '',
      로켓: rocket ? '로켓' : '',
      로켓종류: rocketKind.slice(0, 40),
      값: priceEl ? priceEl.innerText.replace(/[^\d]/g, '') : ((t.match(/(\d[\d,]*)원/) || [])[1] || '').replace(/,/g, ''),
      주소: an ? an.getAttribute('href').slice(0, 200) : '',
      글: t.slice(0, 260),
    };
  });
  return { n: lis.length, title: document.title, url: location.href, brands, rows, head: txt.slice(0, 300) };
}
"""


def probe_http(q):
    from curl_cffi import requests as cr
    res = []
    for name, url in [("pc", "https://www.coupang.com/np/search?q=%s&listSize=36"),
                      ("mobile", "https://m.coupang.com/nm/search?q=%s")]:
        try:
            s = cr.Session(impersonate="chrome")
            r = s.get(url % quote(q), timeout=30, headers={"Accept-Language": "ko-KR,ko;q=0.9"})
            res.append({"길": "http-" + name, "상태": r.status_code, "길이": len(r.text), "앞": r.text[:400]})
        except Exception as e:
            res.append({"길": "http-" + name, "오류": str(e)[:300]})
        time.sleep(3)
    return res


def run_pw(words, headless, tag):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        zero = 0
        for k, q in enumerate(words):
            b = p.chromium.launch(channel="chrome", headless=headless,
                                  args=["--mute-audio", "--disable-blink-features=AutomationControlled", "--lang=ko-KR"])
            ctx = b.new_context(locale="ko-KR", viewport={"width": 1366, "height": 900}, timezone_id="Asia/Seoul")
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            pg = ctx.new_page()
            rec = {"키워드": q, "길": tag, "잰때": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            try:
                if k == 0 or random.random() < 0.3:
                    r0 = pg.goto("https://www.coupang.com/", timeout=45000)
                    rec["홈상태"] = r0.status if r0 else None
                    pg.wait_for_timeout(2500 + random.random() * 2000)
                r = pg.goto("https://www.coupang.com/np/search?q=" + quote(q) + "&listSize=36", timeout=60000)
                rec["상태"] = r.status if r else None
                pg.wait_for_timeout(3000)
                try:
                    pg.wait_for_selector('#product-list > li, li[class*=ProductUnit], li.search-product', timeout=12000)
                except Exception:
                    pass
                pg.mouse.wheel(0, 1500); pg.wait_for_timeout(1500)
                d = pg.evaluate(EXTRACT, a.top)
                rec.update(d)
                if not d["n"]:
                    rec["html앞"] = pg.content()[:1500]
            except Exception as e:
                rec["오류"] = str(e)[:400]
            w(rec)
            print(q, rec.get("상태"), rec.get("n"), str(rec.get("title", ""))[:40], flush=True)
            ctx.close(); b.close()
            zero = 0 if rec.get("n") else zero + 1
            if zero >= 3:
                print("0개 세 번 — 멈춤", flush=True); w({"멈춤": "0개 세 번", "키워드": q, "길": tag}); break
            time.sleep(7 + random.random() * 6)


if a.mode == "probe":
    for q in words:
        w({"키워드": q, "http": probe_http(q)})
    for hl in (True, False):
        run_pw(words, hl, "pw-headless" if hl else "pw-headed")
else:
    run_pw(words, False, "pw-headed")
fo.close()
