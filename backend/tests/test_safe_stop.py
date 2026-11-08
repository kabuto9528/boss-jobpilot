import pytest

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import FixturePage, fixture_site
from backend.app.browser.safe_stop import SafeStop, StopReason


@pytest.mark.parametrize("reason", list(StopReason), ids=lambda reason: reason.value)
def test_safe_stop_prevents_followup_actions_and_releases_profile(reason, browser_profiles):
    settings, profile = browser_profiles
    case = "unknown" if reason == StopReason.PAGE_UNRECOGNIZED else reason.value
    closed = []

    with fixture_site() as origin:
        with pytest.raises(SafeStop) as stopped:
            with persistent_context(settings, profile) as context:
                context.on("close", lambda _: closed.append(True))
                page = FixturePage(context, origin)
                page.navigate()
                assert page.read_sample() == "本地样例"

                try:
                    page.navigate(case)
                except SafeStop:
                    actions_at_stop = page.actions
                    for action in (page.read_sample, page.navigate, lambda: page.write_marker("unexpected")):
                        with pytest.raises(SafeStop) as refused:
                            action()
                        assert refused.value.reason == reason
                    assert page.actions - actions_at_stop == 0
                    raise

        assert stopped.value.reason == reason
        assert closed == [True]
        with persistent_context(settings, profile) as context:
            page = FixturePage(context, origin)
            page.navigate()
            assert page.read_sample() == "本地样例"


def test_risk_visible_before_navigation_blocks_navigation(browser_profiles):
    settings, profile = browser_profiles
    with fixture_site() as origin, persistent_context(settings, profile) as context:
        page = FixturePage(context, origin)
        page.navigate()
        # Reveal the hidden sample notice to simulate a risk appearing on the current page.
        context.pages[0].locator("[data-fixture-risk]").evaluate("notice => { notice.hidden = false; }")
        actions_at_stop = page.actions
        with pytest.raises(SafeStop) as stopped:
            page.navigate()
        assert stopped.value.reason == StopReason.CAPTCHA_REQUIRED
        assert page.actions - actions_at_stop == 0
