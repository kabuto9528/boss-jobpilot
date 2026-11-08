from dataclasses import dataclass
from html import escape
import json
from typing import Callable

from playwright.sync_api import BrowserContext, Route

from .safe_stop import SafeStop, StopReason, classify_fixture_page


MAIN = 'main[data-fixture-page="submit"]'
BUTTON = 'button[type="button"][data-fixture-submit]:visible'


@dataclass(frozen=True)
class SubmitResult:
    status: str
    code: str
    evidence: str


class FixtureSubmitPage:
    """Simulates a submission in Chromium using only intercepted fixture pages."""

    def __init__(self, context: BrowserContext, cases: dict[int, str]):
        self.page = context.pages[0]
        self.cases = cases
        self.submit_calls = 0
        self._url = ""
        self._html = ""
        context.route("**/*", self._route)

    def open(self, job_id: int, identity: str) -> None:
        self.job_id = job_id
        self.identity = identity
        self._url = f"http://127.0.0.1/stage-12-submit/{job_id}"
        self._html = self._render(self.cases.get(job_id, "success"))
        response = self.page.goto(self._url, wait_until="domcontentloaded")
        if response is None or not response.ok:
            raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
        self._inspect()

    def submit(self, should_stop: Callable[[], bool]) -> SubmitResult:
        receipt = self._inspect()
        if receipt is not None:
            if receipt.status != "succeeded":
                raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
            return SubmitResult("succeeded", "FIXTURE_ALREADY_SUBMITTED", receipt.evidence)
        if should_stop():
            return SubmitResult("failed", "SUBMIT_CANCELLED", "本地样例：提交前收到停止请求")
        self.submit_calls += 1
        self.page.locator(MAIN).locator(BUTTON).click()
        return self._inspect(after_click=True) or SubmitResult(
            "uncertain", "SUBMIT_UNCERTAIN", "本地样例：提交动作已尝试，当前职位缺少明确回执",
        )

    def _inspect(self, *, after_click: bool = False) -> SubmitResult | None:
        reason = classify_fixture_page(self.page, (MAIN,))
        if reason:
            raise SafeStop(reason)
        main = self.page.locator(f"{MAIN}:visible")
        if self.page.url != self._url or main.get_attribute("data-identity") != self.identity:
            raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
        receipts = main.locator("[data-fixture-receipt]:visible")
        count = receipts.count()
        if count == 0:
            if not after_click:
                button = main.locator(BUTTON)
                if button.count() != 1 or button.inner_text() != "模拟提交简历" or not button.is_enabled():
                    raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
            return None
        if count != 1 or receipts.get_attribute("data-job-id") != str(self.job_id):
            raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
        if receipts.get_attribute("data-fixture-receipt") == "success" and receipts.inner_text() == self._receipt_text:
            return SubmitResult("succeeded", "FIXTURE_RECEIPT", f"本地样例：{self._receipt_text}")
        if receipts.get_attribute("data-fixture-receipt") == "rejected" and receipts.inner_text() == "提交被明确拒绝":
            return SubmitResult("failed", "FIXTURE_REJECTED", "本地样例：当前职位提交被明确拒绝")
        raise SafeStop(StopReason.PAGE_UNRECOGNIZED)

    @property
    def _receipt_text(self) -> str:
        return f"职位 {self.job_id} 已投递 · 回执 FIXTURE-{self.job_id}"

    def _render(self, case: str) -> str:
        if case in StopReason:
            return self._notice(case)
        if case == "unknown":
            return "<p>未知样例页面</p>"
        button = "<button type='button' data-fixture-submit>模拟提交简历</button>"
        if case == "duplicate":
            button += button
        success = self._receipt("success", self._receipt_text)
        initial = success if case == "already" else button
        response = {
            "success": success,
            "rejected": self._receipt("rejected", "提交被明确拒绝"),
            "wrong_receipt": self._receipt("success", self._receipt_text, job_id=self.job_id + 1),
            "post_risk": self._notice(StopReason.SECURITY_CHECK),
            "uncertain": "<p>沟通已开启</p>",
        }.get(case, "")
        identity = "unverified" if case == "wrong_identity" else self.identity
        return (
            f'<main data-fixture-page="submit" data-identity="{escape(identity)}">{initial}</main>'
            "<script>const b = document.querySelector('[data-fixture-submit]');"
            f"b?.addEventListener('click', () => {{b.outerHTML = {json.dumps(response)};}});</script>"
        )

    def _receipt(self, kind: str, text: str, *, job_id: int | None = None) -> str:
        return f"<p data-fixture-receipt='{kind}' data-job-id='{job_id or self.job_id}'>{escape(text)}</p>"

    @staticmethod
    def _notice(reason: str) -> str:
        if reason == StopReason.LOGIN_REQUIRED:
            return '<main data-fixture-page="login">会话已失效，请重新登录</main>'
        return f'<p data-fixture-risk="{escape(reason)}">{escape(reason)}</p>'

    def _route(self, route: Route) -> None:
        if route.request.method == "GET" and route.request.url == self._url:
            route.fulfill(content_type="text/html; charset=utf-8", body=self._html)
        else:
            route.abort()
