import argparse
import json
from dataclasses import asdict

from playwright.sync_api import Error as PlaywrightError

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import fixture_site
from backend.app.browser.safe_stop import StopReason
from backend.app.browser.search_read import read_fixture_search
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import BrowserBusy


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a bounded job list from the local fixture.")
    parser.add_argument("--provider", choices=("fixture", "boss"), default="fixture")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-jobs", type=int, required=True)
    args = parser.parse_args()

    if args.provider == "boss":
        parser.exit(2, "PROVIDER_DISABLED: platform permission, Stage 7 live acceptance and verified selectors are required.\n")
    if not args.keyword.strip() or min(args.max_pages, args.max_jobs) < 1:
        parser.error("Provide a nonempty keyword and positive page and job limits.")

    settings = load_browser_settings()
    profile = settings.profile_root / "fixture-stage-08"
    try:
        with fixture_site() as origin, persistent_context(settings, profile, headless=False) as context:
            result = read_fixture_search(
                context, origin, keyword=args.keyword, max_pages=args.max_pages, max_jobs=args.max_jobs
            )
    except BrowserBusy as error:
        raise SystemExit(f"{error.code}: {error}") from None
    except PlaywrightError:
        raise SystemExit("BROWSER_ERROR: check the local Chromium installation and profile.") from None

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    if result.stop_reason in set(StopReason):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
