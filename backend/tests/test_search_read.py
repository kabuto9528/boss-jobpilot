from hashlib import sha256

import pytest

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import fixture_site
from backend.app.browser.fixture_search_pages import search_prefix
from backend.app.browser.search_read import read_fixture_search


@pytest.fixture
def search(browser_profiles):
    settings, profile = browser_profiles

    def run(keyword, max_pages=5, max_jobs=10, *, script=None):
        with fixture_site() as origin, persistent_context(settings, profile) as context:
            if script is not None:
                context.add_init_script(script)
            requests = []
            context.on("request", lambda request: requests.append((request.method, request.url)))
            result = read_fixture_search(context, origin, keyword=keyword, max_pages=max_pages, max_jobs=max_jobs)
        assert all(method == "GET" and url.startswith(f"{origin}/") for method, url in requests)
        return result, [url.removeprefix(origin) for _, url in requests]

    return run


def test_reads_two_pages_in_order_and_handles_duplicate_and_missing_fields(search):
    keyword = "运维实习生"
    result, requests = search(keyword, max_pages=2, max_jobs=5)
    assert (result.pages_attempted, result.details_attempted, result.duplicates) == (2, 5, 1)
    assert result.stop_reason == "exhausted"
    assert result.skipped == {"missing_identity": 1}
    url_key = "url:" + sha256(b"/detail?job=link-only").hexdigest()
    assert [job.identity_key for job in result.jobs] == [
        "fixture:fixture-job-001", "fixture:fixture-job-002", "fixture:fixture-job-003", url_key,
    ]
    first, second, missing_jd, link_only = result.jobs
    assert first.title == second.title == "运维实习生"
    assert first.company == second.company == "示例云科技"
    assert first.jd_text == (
        "岗位职责\n维护 Linux 服务，排查验证码服务的运行告警。\n\n"
        "任职要求\n熟悉 Shell，能够记录故障复盘。\n\n"
        "实习安排\n每周到岗四天，实习至少三个月。"
    )
    assert first.jd_state == "complete"
    assert (second.salary_text, second.experience_text) == ("150–200 元/天", "经验不限")
    assert (missing_jd.jd_text, missing_jd.jd_state) == (None, "missing")
    assert link_only.source_job_id is None
    assert link_only.source_url.endswith("/detail?job=link-only")
    assert requests == [
        f"{search_prefix(keyword)}1", "/logged-in", "/detail?job=same-title", "/detail?job=no-jd",
        f"{search_prefix(keyword)}2", "/missing-identity", "/detail?job=link-only",
    ]


def test_deduplicates_the_same_identity_found_at_two_detail_links(search):
    result, requests = search("别名重复")
    assert (result.details_attempted, result.duplicates, len(result.jobs)) == (2, 1, 1)
    assert requests[1:] == ["/logged-in", "/detail?job=alias"]


@pytest.mark.parametrize(
    ("keyword", "reason"),
    [("没有职位", "empty_results"), ("未知列表", "PAGE_UNRECOGNIZED")],
)
def test_distinguishes_explicit_empty_results_from_unknown_page(search, keyword, reason):
    result, requests = search(keyword)
    assert result.stop_reason == reason
    assert (result.pages_attempted, result.details_attempted) == (1, 0)
    assert not result.jobs and not result.skipped
    assert requests == [f"{search_prefix(keyword)}1"]


def test_stops_when_the_same_batch_reappears_in_a_different_order(search):
    keyword = "页面不前进"
    result, requests = search(keyword)
    assert result.stop_reason == "page_not_advancing"
    assert (result.pages_attempted, result.details_attempted, len(result.jobs)) == (2, 2, 2)
    assert requests == [f"{search_prefix(keyword)}1", "/logged-in", "/detail?job=same-title", f"{search_prefix(keyword)}2"]


def test_stops_when_a_new_detail_link_resolves_to_the_same_batch(search):
    keyword = "别名分页"
    result, requests = search(keyword)
    assert result.stop_reason == "page_not_advancing"
    assert (result.pages_attempted, result.details_attempted, result.duplicates, len(result.jobs)) == (2, 2, 1, 1)
    assert requests == [f"{search_prefix(keyword)}1", "/logged-in", f"{search_prefix(keyword)}2", "/detail?job=alias"]


@pytest.mark.parametrize(
    ("keyword", "pages", "jobs", "reason", "targets"),
    [
        ("持续分页", 2, 10, "max_pages", ["p1", "/detail?job=loop-1", "p2", "/detail?job=loop-2"]),
        ("运维实习生", 5, 1, "max_jobs", ["p1", "/logged-in"]),
        (
            "运维实习生", 5, 4, "max_jobs",
            ["p1", "/logged-in", "/detail?job=same-title", "/detail?job=no-jd", "p2", "/missing-identity"],
        ),
    ],
)
def test_caps_actual_list_and_detail_requests(search, keyword, pages, jobs, reason, targets):
    result, requests = search(keyword, max_pages=pages, max_jobs=jobs)
    assert result.stop_reason == reason
    assert result.pages_attempted <= pages
    assert result.details_attempted <= jobs
    assert requests == [f"{search_prefix(keyword)}{target[1:]}" if target.startswith("p") else target for target in targets]
    if jobs == 4:
        assert result.skipped == {"missing_identity": 1}
        assert len(result.jobs) == 3


@pytest.mark.parametrize(
    ("keyword", "reason", "last_request", "pages", "details"),
    [
        ("风险详情", "SECURITY_CHECK", "/detail?job=risk", 1, 2),
        ("风险列表", "SECURITY_CHECK", "p2", 2, 1),
        ("身份冲突", "PAGE_UNRECOGNIZED", "/detail?job=same-title", 1, 2),
    ],
)
def test_stops_on_risk_or_conflicting_identity_and_preserves_earlier_results(
    search, keyword, reason, last_request, pages, details
):
    result, requests = search(keyword)
    assert result.stop_reason == reason
    assert (result.pages_attempted, result.details_attempted) == (pages, details)
    assert [job.source_job_id for job in result.jobs] == ["fixture-job-001"]
    if last_request == "p2":
        last_request = f"{search_prefix(keyword)}2"
    assert requests == [f"{search_prefix(keyword)}1", "/logged-in", last_request]


@pytest.mark.parametrize(
    "change",
    [
        "document.querySelector('[data-fixture-next]').href = '2'",
        "document.querySelector('[data-fixture-card] a').href = 'https://example.invalid/job'",
        "document.querySelector('[data-fixture-results]').replaceChildren()",
    ],
)
def test_rejects_unverified_links_and_unmarked_empty_lists_before_opening_details(search, change):
    keyword = "运维实习生"
    script = f"document.addEventListener('DOMContentLoaded', () => {{ {change}; }});"
    result, requests = search(keyword, script=script)
    assert result.stop_reason == "PAGE_UNRECOGNIZED"
    assert result.details_attempted == 0
    assert requests == [f"{search_prefix(keyword)}1"]
