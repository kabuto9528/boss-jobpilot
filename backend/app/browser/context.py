from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from backend.app.config import BrowserSettings
from backend.app.runner.profile_lock import browser_lock, ensure_profiles_idle


@contextmanager
def persistent_context(settings: BrowserSettings, profile: Path, *, headless: bool = True):
    profile = profile.resolve()
    if profile == settings.profile_root or not profile.is_relative_to(settings.profile_root):
        raise ValueError("Use a dedicated profile under the configured project profile directory.")

    with browser_lock():
        ensure_profiles_idle(settings.profile_root)
        profile.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=profile,
                channel="chromium",
                headless=headless,
                timeout=settings.timeout_ms,
            )
            try:
                context.set_default_timeout(settings.timeout_ms)
                context.set_default_navigation_timeout(settings.timeout_ms)
                yield context
            finally:
                context.close()
