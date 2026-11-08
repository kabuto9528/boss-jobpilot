import re
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit


DETAIL_TARGET = re.compile(r"/detail\?job=([a-z0-9-]+)")
PAGE_NUMBER = re.compile(r"[1-9][0-9]{0,8}")
SEARCH_CASES = {
    "运维实习生": (
        (("logged-in", "fixture-job-001"), ("same-title", "fixture-job-002"), ("no-jd", "fixture-job-003")),
        (("logged-in", "fixture-job-001"), ("missing-identity", None), ("link-only", None)),
    ),
    "风险详情": ((("logged-in", "fixture-job-001"), ("risk", None), ("same-title", "fixture-job-002")),),
    "风险列表": ((("logged-in", "fixture-job-001"),), ()),
    "页面不前进": (
        (("logged-in", "fixture-job-001"), ("same-title", "fixture-job-002")),
        (("same-title", "fixture-job-002"), ("logged-in", "fixture-job-001")),
        (("no-jd", "fixture-job-003"),),
    ),
    "身份冲突": ((("logged-in", "fixture-job-001"), ("same-title", "fixture-job-009")),),
    "别名重复": ((("logged-in", "fixture-job-001"), ("alias", "fixture-job-001")),),
    "别名分页": (
        (("logged-in", "fixture-job-001"),),
        (("alias", "fixture-job-001"),),
        (("same-title", "fixture-job-002"),),
    ),
}
DETAIL_IDS = {
    "same-title": "fixture-job-002",
    "no-jd": "fixture-job-003",
    "alias": "fixture-job-001",
    "link-only": None,
}


def search_prefix(keyword: str) -> str:
    return f"/search?{urlencode({'keyword': keyword})}&page="


def _detail_link(key: str) -> str:
    if key in {"logged-in", "missing-identity"}:
        return f"/{key}"
    return f"/detail?job={key}"


def _render_results(fixtures: Path, keyword: str, page: int) -> str:
    if keyword == "风险列表" and page == 2:
        return _risk(fixtures)
    if keyword == "未知列表":
        return "<!doctype html><main>页面加载异常</main>"

    if keyword == "持续分页":
        rows = ((f"loop-{page}", f"fixture-loop-{page}"),)
        has_next = True
    else:
        pages = SEARCH_CASES.get(keyword, ())
        rows = pages[page - 1] if page <= len(pages) else ()
        has_next = page < len(pages)

    cards = []
    for key, job_id in rows:
        link = escape(_detail_link(key), quote=True)
        identity = f'<span data-fixture-field="source_job_id">{escape(job_id)}</span>' if job_id else ""
        cards.append(f'<article data-fixture-card><a href="{link}">运维实习生</a>{identity}</article>')
    content = (
        f"<section data-fixture-results>{''.join(cards)}</section>"
        if cards else "<p data-fixture-empty>没有符合条件的职位</p>"
    )
    next_url = escape(f"{search_prefix(keyword)}{page + 1}", quote=True)
    next_link = f'<a data-fixture-next href="{next_url}">下一页</a>' if has_next else ""
    template = (fixtures / "search.html").read_text(encoding="utf-8")
    return template.format(keyword=escape(keyword), content=content, next_link=next_link)


def _risk(fixtures: Path) -> str:
    template = (fixtures / "risk.html").read_text(encoding="utf-8")
    return template.format(reason="SECURITY_CHECK", message="需要安全验证")


def render_search_fixture(target: str, fixtures: Path) -> str | None:
    url = urlsplit(target)
    if url.path == "/search":
        query = parse_qs(url.query)
        keywords = query.get("keyword", [])
        numbers = query.get("page", [])
        if len(keywords) != 1 or len(numbers) != 1:
            return None
        keyword, = keywords
        number, = numbers
        if keyword and PAGE_NUMBER.fullmatch(number) and target == f"{search_prefix(keyword)}{number}":
            return _render_results(fixtures, keyword, int(number))
        return None

    match = DETAIL_TARGET.fullmatch(target)
    if not match:
        return None
    key = match[1]
    if key == "risk":
        return _risk(fixtures)
    if key in DETAIL_IDS:
        job_id = DETAIL_IDS[key]
    elif key.startswith("loop-") and PAGE_NUMBER.fullmatch(key.removeprefix("loop-")):
        job_id = f"fixture-{key}"
    else:
        return None

    html = (fixtures / "job.html").read_text(encoding="utf-8")
    if job_id is None:
        html = html.replace('data-fixture-field="source_job_id"', "hidden")
    else:
        html = html.replace("fixture-job-001", job_id)
    if key == "no-jd":
        html = html.replace('data-fixture-field="jd_text"', "hidden")
    return html.replace(
        "<h2>职位描述</h2>",
        '<p data-fixture-field="salary_text">150–200 元/天</p>'
        '<p data-fixture-field="experience_text">经验不限</p><h2>职位描述</h2>',
    )
