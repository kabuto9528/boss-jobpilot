import subprocess
import sys

import pytest
from playwright.sync_api import TimeoutError, sync_playwright

from backend.app.browser.context import persistent_context
from backend.app.browser.fixture import FixturePage, fixture_site
from backend.app.config import PROJECT_ROOT, load_browser_settings
from backend.app.runner.profile_lock import BrowserBusy


def test_chromium_reopens_dedicated_profile(browser_profiles):
    settings, profile = browser_profiles
    with fixture_site() as origin:
        with persistent_context(settings, profile / "first") as context:
            page = FixturePage(context, origin)
            page.navigate()
            page.write_marker("stage-06-local-only")

        with persistent_context(settings, profile / "first") as context:
            page = FixturePage(context, origin)
            page.navigate()
            assert page.read_marker() == "stage-06-local-only"

        with persistent_context(settings, profile / "second") as context:
            page = FixturePage(context, origin)
            page.navigate()
            assert page.read_marker() == ""


def test_project_lock_rejects_same_and_different_profiles(browser_profiles):
    settings, profile = browser_profiles
    probe = """
import os
import sys
from pathlib import Path
from backend.app.browser.context import persistent_context
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import BrowserBusy

settings = load_browser_settings()
os.chdir(settings.profile_root)
try:
    with persistent_context(settings, Path(sys.argv[1])):
        sys.exit('Unexpected Chromium launch')
except BrowserBusy as error:
    print(error.code)
"""
    with persistent_context(settings, profile / "first"):
        for other_profile in (profile / "first", profile / "second"):
            with pytest.raises(BrowserBusy, match="holds the project lock"):
                with persistent_context(settings, other_profile):
                    pytest.fail("A second task started in the same process")

            result = subprocess.run(
                [sys.executable, "-c", probe, str(other_profile)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            assert result.stdout.strip() == "BROWSER_BUSY"

    with persistent_context(settings, profile / "second") as context:
        assert context.pages


def test_residual_chromium_blocks_new_task_before_launch(browser_profiles):
    settings, profile = browser_profiles
    # Launch without the project lock to reproduce a browser surviving its lock owner.
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile / "residual", channel="chromium", headless=True, timeout=settings.timeout_ms
        )
        try:
            for target in (profile / "residual", profile / "other"):
                with pytest.raises(BrowserBusy, match="still using a project browser profile"):
                    with persistent_context(settings, target):
                        pytest.fail("The residual browser was missed")
        finally:
            context.close()

    with persistent_context(settings, profile / "residual") as context:
        assert context.pages


def test_read_timeout_closes_context_and_releases_profile(browser_profiles):
    settings, profile = browser_profiles
    closed = []
    with fixture_site() as origin:
        with pytest.raises(TimeoutError):
            with persistent_context(settings, profile) as context:
                context.on("close", lambda _: closed.append(True))
                page = FixturePage(context, origin)
                page.navigate("missing-value")
                context.set_default_timeout(500)
                page.read_sample()

        assert closed == [True]
        with persistent_context(settings, profile) as context:
            page = FixturePage(context, origin)
            page.navigate()
            assert page.read_sample() == "本地样例"


def test_rejects_profile_outside_the_dedicated_directory():
    settings = load_browser_settings()
    for path in (settings.profile_root, PROJECT_ROOT / "runtime" / "outside-profiles"):
        with pytest.raises(ValueError, match="dedicated profile"):
            with persistent_context(settings, path):
                pytest.fail("A non-dedicated profile opened")
