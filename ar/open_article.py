"""남의 카페 글 한 건 열기 — v2.1 로 열고, 안 열리면 v4 로 연다(10-23 실측: 89/89 둘 다 열림).

빈틈지도 · 경쟁사 수집 · 조회수 수집이 같이 쓰려고 입력·출력을 단순하게 둔다.
  입력: get(주소, 헤더) → (상태 번호, 응답 글)  — 어느 통신 도구든 이 모양으로 감싸 넘긴다(make_get).
        url = 검색 결과에 뜬 글 주소(art 열쇠가 붙은 그대로) · club_id = 카페 번호(알면).
  출력: dict 한 개 — 열림 · 연주소(v2.1/v4) · 요청수 · 까닭 · 본문(HTML) · 댓글수 · 조회수 · 카페번호 · 제목 · 쓴때 · 댓글.
  막힘(429 · 오류 번호 없는 403 · '이용이 제한' 화면)이면 Blocked 를 올린다 — 멈출지는 부르는 쪽이 정한다.
  일시 실패(시간 초과 · 연결 실패 · 5xx · 못 읽는 응답)는 '일시': True 를 붙인다 — 다시 열면 열릴 수 있으니 '다 처리함'이 아니다
  (10-24 GPT 3차 '막음' 7). 200 이어도 글 객체 · 본문 칸이 없거나 오류 번호가 붙으면 일시(4차 '막음' 3).
  확정된 실패(지워진 글 4003 · 오류 번호가 붙은 4xx · 404 · 410 · 글 객체는 있는데 본문 칸이 빈 200)만 일시가 아니다.
★네이버로 요청을 보내는 길은 make_get 하나뿐이고, 그 get 은 부를 때마다 GitHub 서버인지 본다(require_github —
  집 PC 에서 직접 불러도 통신 도구까지 가지 않는다 · 10-24 GPT 검토 '막음' 1). 카페 칸 수집(cafe_scan.make_fetch)도 같은 검사를 쓴다.
  예외: 검색광고 API(keyword_volume.py)는 공식 열쇠로 부르는 API 라 검색 화면 수집이 아니다 → 집 PC 허용(총괄 판정, 10-24).
요청 수는 RequestBudget 이 통신 직전에 센다(v2.1 실패 → v4 대체 호출도 한 번씩 · 예외가 나도 센 값은 남는다).
근거: vault/03_지식/활용방안/네이버_카페_남의글_여는법.md (주소 모양 · 헤더 · 막힘 판정).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

V21 = "https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{cafe}/articles/{aid}"
V4 = "https://article.cafe.naver.com/gw/v4/cafes/{cafe}/articles/{aid}"
POST = re.compile(r"cafe\.naver\.com/(?:ca-fe/(?:web/)?cafes/|f-e/cafes/)?([A-Za-z0-9_-]+)/(?:articles/)?(\d+)")
ART = re.compile(r"[?&]art=([^&#]+)")
BLOCK_WORDS = ("이용이 제한",)
DELETED = "4003"
KST = timezone(timedelta(hours=9))
# 글 쓴 때가 들어 있을 수 있는 칸. ⚠️ 어느 칸이 실제로 오는지는 아직 원본으로 맞춰 보지 못했다 —
#   본체가 처음 몇 글의 칸 이름(글칸)을 남기므로 첫 실행 뒤 확인한다.
DATE_KEYS = ("writeDate", "writeDateTimestamp", "writeDateTime", "registerDate", "createDate", "addDate")


class Blocked(Exception):
    """진짜 막힘 — 이 글만의 문제가 아니라 그 회차 전체의 문제."""


class NotOnGitHub(RuntimeError):
    """GitHub 서버(GITHUB_ACTIONS=true)가 아닌 곳에서 네이버 검색 화면 · 카페 글 요청을 하려 함."""


class BudgetOut(Exception):
    """요청 예산을 다 씀 — 다음 요청을 보내지 않는다."""


def require_github():
    """네이버 검색 화면 · 카페 글 요청 바로 앞에서 부른다. 집 IP 보호(설계서 5절)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise NotOnGitHub("네이버 검색 화면 · 카페 글 요청은 GitHub 서버에서만 합니다(집 IP 보호).")


class RequestBudget:
    """요청 수 장부. take() 를 통신 바로 앞에서 부른다 — 한도에 닿으면 BudgetOut, 아니면 1 더한다.
    posts = 열기 시작한 글 수(실패 · 막힘도 센다)."""

    def __init__(self, limit, used=0):
        self.limit, self.used, self.posts = max(0, int(limit)), int(used), 0

    @property
    def left(self):
        return max(0, self.limit - self.used)

    def take(self):
        if self.used >= self.limit:
            raise BudgetOut(f"요청 상한 {self.limit}번")
        self.used += 1


def post_key(url):
    """카페 글 주소 → (카페 토막, 글 번호). 모바일·PC·신형 주소를 같은 모양으로. 글 주소가 아니면 None."""
    m = POST.search(url or "")
    return (m.group(1), m.group(2)) if m else None


def _when(v):
    """에포크(초·밀리초) 또는 날짜 글 → 'YYYY-MM-DD' (한국 시각). 못 읽으면 ''."""
    if v in (None, ""):
        return ""
    try:
        n = float(v)
        if n > 1e11:
            n /= 1000.0
        return datetime.fromtimestamp(n, KST).date().isoformat()
    except (TypeError, ValueError):
        m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(v))
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def parse_response(status, body):
    """글 주소 응답 하나 → 열림 여부와 숫자. 막힘이면 Blocked."""
    try:
        j = json.loads(body) if body else None
    except ValueError:
        j = None
    parsed = isinstance(j, dict)
    j = j if parsed else {}
    res = j.get("result", j)
    res = res if isinstance(res, dict) else {}
    code = str(res.get("errorCode") or j.get("errorCode") or "")
    if status == 429 or (status == 403 and not code) or any(w in (body or "")[:5000] for w in BLOCK_WORDS):
        raise Blocked(f"HTTP {status}")
    if status != 200:
        temp = status >= 500 or not (code or status in (404, 410))
        return {"열림": False, "까닭": f"HTTP {status} {code}".strip(), "오류번호": code, "일시": temp}
    if not parsed:
        return {"열림": False, "까닭": "못 읽는 응답", "오류번호": "", "일시": True}
    art = res.get("article")
    if code or not isinstance(art, dict) or not ({"contentHtml", "content"} & set(art)):
        # 4차 '막음' 3: 200 이어도 글 객체 · 본문 칸이 없으면(빈 {} · 일시 오류 JSON) 다시 열 일 — 확인된 삭제(4003)만 끝
        return {"열림": False, "까닭": f"글 구조 없는 200 응답 {code}".strip(), "오류번호": code, "일시": code != DELETED}
    content = art.get("contentHtml") or art.get("content") or ""
    comments = res.get("comments")
    items = comments.get("items") if isinstance(comments, dict) else comments
    when = ""
    for k in DATE_KEYS:
        when = _when(art.get(k))
        if when:
            break
    return {"열림": bool(content), "까닭": "" if content else "본문 빈 응답",
            "본문": content, "댓글수": art.get("commentCount"), "조회수": art.get("readCount"),
            "카페번호": str(res.get("cafeId") or art.get("cafeId") or ""),
            "제목": (art.get("subject") or "").strip(), "쓴때": when,
            "댓글": [str((x or {}).get("content") or "") for x in items] if isinstance(items, list) else None,
            "글칸": sorted(art.keys())}


def open_article(get, url, club_id="", pace=None, charge=None):
    """글 한 건을 연다. v2.1(카페 번호를 알 때) → 안 열리면 v4. 막힘이면 Blocked 를 그대로 올린다.
    charge = 통신 바로 앞에서 부르는 예산 차감(RequestBudget.take). BudgetOut · NotOnGitHub 은 그대로 올린다."""
    key = post_key(url)
    if not key:
        return {"글": "", "열림": False, "연주소": "", "요청수": 0, "까닭": "글 주소 아님", "시도": []}
    cafe, aid = key
    club = cafe if cafe.isdigit() else str(club_id or "")
    tries, n = [], 0
    out = None

    def call(api, headers):
        nonlocal n
        if pace:
            pace()
        if charge:
            charge()          # 보내기 전에 센다 — 아래에서 무엇이 터져도 이 한 번은 장부에 남는다
        n += 1
        try:
            st, text = get(api, headers)
        except (Blocked, NotOnGitHub, BudgetOut):
            raise
        except Exception as e:  # 통신 실패(시간 초과 · 연결 끊김) — 일시 실패. 주소·헤더는 남기지 않는다
            return {"열림": False, "까닭": type(e).__name__, "일시": True}
        return parse_response(st, text)

    if club:
        art = ART.search(url)
        r = call(V21.format(cafe=club, aid=aid) + "?useCafeId=true&requestFrom=A"
                 + (f"&art={art.group(1)}" if art else ""), {"Referer": url})
        tries.append({"주소": "v2.1", "까닭": r.get("까닭", "")})
        if r["열림"]:
            out = {**r, "연주소": "v2.1"}
        elif r.get("오류번호") == DELETED:
            out = {**r, "연주소": "", "까닭": "지워진 글(4003)"}
    else:
        tries.append({"주소": "v2.1", "까닭": "카페 번호 모름"})
    if out is None:
        q = urlsplit(url).query
        v4q = (q + "&" if q else "") + f"useCafeId={'true' if cafe.isdigit() else 'false'}&buid={uuid.uuid4()}"
        r = call(V4.format(cafe=cafe, aid=aid) + "?" + v4q,
                 {"Referer": url, "x-cafe-product": "mweb", "origin": "https://m.cafe.naver.com"})
        tries.append({"주소": "v4", "까닭": r.get("까닭", "")})
        out = {**r, "연주소": "v4" if r["열림"] else ""}
    out.pop("오류번호", None)
    return {**out, "글": f"{cafe}/{aid}", "요청수": n, "시도": tries}


def make_get(session, timeout=25):
    """requests · curl_cffi 세션 → open_article 이 받는 get(주소, 헤더)."""
    def get(api, headers):
        require_github()      # 부를 때마다 — make_get 을 직접 불러도 집 PC 에서는 통신 도구까지 가지 않는다
        r = session.get(api, headers=headers, timeout=timeout)
        return r.status_code, r.text
    return get
