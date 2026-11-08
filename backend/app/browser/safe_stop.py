from enum import StrEnum

from playwright.sync_api import Page


class StopReason(StrEnum):
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    SECURITY_CHECK = "SECURITY_CHECK"
    RATE_LIMITED = "RATE_LIMITED"
    ACCOUNT_ABNORMAL = "ACCOUNT_ABNORMAL"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PAGE_UNRECOGNIZED = "PAGE_UNRECOGNIZED"


class SafeStop(RuntimeError):
    def __init__(self, reason: StopReason):
        super().__init__(reason.value)
        self.reason = reason


def classify_fixture_page(
    page: Page, required_markers: tuple[str, ...] = ('main[data-fixture-page="profile"]',)
) -> StopReason | None:
    notices = page.locator("[data-fixture-risk]:visible").all()
    if notices:
        if len(notices) == 1:
            try:
                return StopReason(notices[0].get_attribute("data-fixture-risk"))
            except ValueError:
                pass
        return StopReason.PAGE_UNRECOGNIZED
    login_pages = page.locator('main[data-fixture-page="login"]:visible').count()
    if login_pages:
        return StopReason.LOGIN_REQUIRED if login_pages == 1 else StopReason.PAGE_UNRECOGNIZED
    if any(page.locator(f"{selector}:visible").count() != 1 for selector in required_markers):
        return StopReason.PAGE_UNRECOGNIZED
    return None
