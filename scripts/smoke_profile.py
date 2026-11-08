import argparse
from uuid import uuid4

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import FixturePage, fixture_site
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import BrowserBusy


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a persistent Chromium profile on the local fixture.")
    parser.add_argument("--provider", choices=["fixture"], default="fixture")
    parser.parse_args()

    settings = load_browser_settings()
    profile = settings.profile_root / "fixture-stage-06"
    marker = uuid4().hex
    try:
        with fixture_site() as origin:
            with persistent_context(settings, profile, headless=False) as context:
                page = FixturePage(context, origin)
                page.navigate()
                page.write_marker(marker)

            with persistent_context(settings, profile, headless=False) as context:
                page = FixturePage(context, origin)
                page.navigate()
                if page.read_marker() != marker:
                    raise SystemExit("FAIL: the fixture marker did not survive a Chromium restart.")
    except BrowserBusy as error:
        raise SystemExit(f"{error.code}: {error}") from None

    print(f"Fixture origin: {origin}")
    print(f"Dedicated profile: {profile}")
    print("PASS: visible Chromium started, closed and reopened. The local marker persisted.")


if __name__ == "__main__":
    main()
