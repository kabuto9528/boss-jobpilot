from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend.app.config import load_browser_settings


@pytest.fixture
def browser_profiles():
    settings = load_browser_settings()
    settings.profile_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="stage-06-test-", dir=settings.profile_root) as directory:
        yield settings, Path(directory)
