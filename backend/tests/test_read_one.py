import pytest

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import FixtureJob, FixtureJobPage, fixture_site
from backend.app.browser.safe_stop import SafeStop, StopReason


def test_reads_single_visible_job_and_full_jd(browser_profiles):
    settings, profile = browser_profiles
    with fixture_site() as origin, persistent_context(settings, profile) as context:
        requests = []
        context.on("request", lambda request: requests.append((request.method, request.url)))
        reader = FixtureJobPage(context, origin)
        reader.navigate("logged-in")
        assert reader.read_job() == FixtureJob(
            source_job_id="fixture-job-001",
            title="运维实习生",
            company="示例云科技",
            city="武汉",
            jd_text=(
                "岗位职责\n维护 Linux 服务，排查验证码服务的运行告警。\n\n"
                "任职要求\n熟悉 Shell，能够记录故障复盘。\n\n"
                "实习安排\n每周到岗四天，实习至少三个月。"
            ),
        )
        assert reader.actions == 2
        assert requests == [("GET", f"{origin}/logged-in")]


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("login-required", StopReason.LOGIN_REQUIRED),
        ("unknown", StopReason.PAGE_UNRECOGNIZED),
        (StopReason.SECURITY_CHECK, StopReason.SECURITY_CHECK),
        ("missing-jd", StopReason.PAGE_UNRECOGNIZED),
        ("missing-identity", StopReason.PAGE_UNRECOGNIZED),
    ],
)
def test_stops_without_returning_a_job_or_dispatching_followup(case, reason, browser_profiles):
    settings, profile = browser_profiles
    closed = []
    with fixture_site() as origin:
        with pytest.raises(SafeStop) as stopped:
            with persistent_context(settings, profile) as context:
                context.on("close", lambda _: closed.append(True))
                requests = []
                context.on("request", lambda request: requests.append((request.method, request.url)))
                reader = FixtureJobPage(context, origin)
                try:
                    reader.navigate(case)
                    reader.read_job()
                except SafeStop:
                    actions_at_stop = reader.actions
                    for retry in (reader.read_job, lambda: reader.navigate("logged-in")):
                        with pytest.raises(SafeStop) as refused:
                            retry()
                        assert refused.value.reason == reason
                    assert reader.actions == actions_at_stop
                    assert requests == [("GET", f"{origin}/{case}")]
                    raise
        assert stopped.value.reason == reason
        assert closed == [True]
        with persistent_context(settings, profile) as context:
            reader = FixtureJobPage(context, origin)
            reader.navigate("logged-in")
            assert reader.read_job().source_job_id == "fixture-job-001"


@pytest.mark.parametrize(
    ("change", "reason", "read_dispatched"),
    [
        (
            "document.querySelector('main').dataset.fixturePage = 'login'",
            StopReason.LOGIN_REQUIRED,
            0,
        ),
        (
            "document.querySelector('[data-fixture-session]').hidden = true",
            StopReason.PAGE_UNRECOGNIZED,
            0,
        ),
        (
            "document.body.insertAdjacentHTML('beforeend', "
            "'<main data-fixture-page=login>重新登录</main>'.repeat(2))",
            StopReason.PAGE_UNRECOGNIZED,
            0,
        ),
        (
            "document.querySelector('aside').hidden = false",
            StopReason.SECURITY_CHECK,
            0,
        ),
        (
            "document.querySelector('article').after(document.querySelector('article').cloneNode(true))",
            StopReason.PAGE_UNRECOGNIZED,
            1,
        ),
        (
            "document.querySelector('[data-fixture-jd]').dataset.fixtureJd = 'loading'",
            StopReason.PAGE_UNRECOGNIZED,
            1,
        ),
    ],
    ids=[
        "session-expired",
        "missing-login-marker",
        "ambiguous-login",
        "risk-overlay",
        "ambiguous-detail",
        "loading-jd",
    ],
)
def test_checks_current_page_before_returning_detail(change, reason, read_dispatched, browser_profiles):
    settings, profile = browser_profiles
    with fixture_site() as origin, persistent_context(settings, profile) as context:
        reader = FixtureJobPage(context, origin)
        reader.navigate("logged-in")
        assert reader.read_job().source_job_id == "fixture-job-001"
        context.pages[0].evaluate(change)
        before_read = reader.actions
        with pytest.raises(SafeStop) as stopped:
            reader.read_job()
        assert stopped.value.reason == reason
        assert reader.actions - before_read == read_dispatched
        actions_at_stop = reader.actions
        with pytest.raises(SafeStop) as refused:
            reader.read_job()
        assert refused.value.reason == reason
        assert reader.actions == actions_at_stop
