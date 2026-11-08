import argparse

from playwright.sync_api import Error as PlaywrightError

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import FixtureJobPage, fixture_site
from backend.app.browser.safe_stop import SafeStop, StopReason
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import BrowserBusy


EXPECTED_STOPS = {
    "login-required": StopReason.LOGIN_REQUIRED,
    "unknown": StopReason.PAGE_UNRECOGNIZED,
    "missing-jd": StopReason.PAGE_UNRECOGNIZED,
    "missing-identity": StopReason.PAGE_UNRECOGNIZED,
}


def run_case(case: str) -> None:
    settings = load_browser_settings()
    profile = settings.profile_root / "fixture-stage-07"
    with fixture_site() as origin, persistent_context(settings, profile, headless=False) as context:
        requests = []
        context.on("request", lambda request: requests.append((request.method, request.url)))
        page = FixtureJobPage(context, origin)
        try:
            page.navigate(case)
            job = page.read_job()
        except SafeStop as stopped:
            if stopped.reason != EXPECTED_STOPS.get(case):
                raise SystemExit(f"FAIL: unexpected Safe Stop {stopped.reason}.") from None
            actions_at_stop = page.actions
            try:
                page.read_job()
            except SafeStop as refused:
                if refused.reason != stopped.reason or page.actions != actions_at_stop:
                    raise SystemExit("FAIL: the reader did not preserve the stop.") from None
            else:
                raise SystemExit("FAIL: the follow-up read was allowed.")
            summary = f"{stopped.reason}; follow-up reads=0"
        else:
            if case in EXPECTED_STOPS:
                raise SystemExit("FAIL: the incomplete or unsafe page returned a job.")
            summary = f"LOGGED_IN; job={job.source_job_id}; jd_chars={len(job.jd_text)}"

        if requests != [("GET", f"{origin}/{case}")]:
            raise SystemExit("FAIL: the reader made an unexpected browser request.")
    print(f"PASS: fixture {case}; {summary}; submit calls=0")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify single-job reading on the local fixture.")
    parser.add_argument("--provider", choices=("fixture", "boss"), default="fixture")
    parser.add_argument("--case", choices=("logged-in", *EXPECTED_STOPS), default="logged-in")
    boss_options = parser.add_mutually_exclusive_group()
    boss_options.add_argument("--login-only", action="store_true")
    boss_options.add_argument("--url")
    args = parser.parse_args()

    if args.provider == "boss":
        parser.exit(2, "PROVIDER_DISABLED: platform permission and verified page evidence are required.\n")
    if args.login_only or args.url is not None:
        parser.error("Use --case for the local fixture.")

    try:
        run_case(args.case)
    except BrowserBusy as error:
        raise SystemExit(f"{error.code}: {error}") from None
    except PlaywrightError:
        raise SystemExit("BROWSER_ERROR: check the local Chromium installation and profile.") from None


if __name__ == "__main__":
    main()
