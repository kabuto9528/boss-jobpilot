from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import TypeVar
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Locator, Route

from backend.app.browser.fixture_search_pages import render_search_fixture
from backend.app.browser.safe_stop import SafeStop, StopReason, classify_fixture_page
from backend.app.config import PROJECT_ROOT


FIXTURES = PROJECT_ROOT / "backend" / "tests" / "fixtures"
RISK_MESSAGES = {
    StopReason.CAPTCHA_REQUIRED: "请完成验证码或滑块验证",
    StopReason.SECURITY_CHECK: "需要安全验证",
    StopReason.RATE_LIMITED: "操作频繁",
    StopReason.ACCOUNT_ABNORMAL: "账号异常",
    StopReason.LOGIN_REQUIRED: "会话已失效，请重新登录",
}
CASES = {"normal", "missing-value", "unknown", *RISK_MESSAGES}
JOB_CASES = {
    "logged-in": None,
    "missing-jd": "jd_text",
    "missing-identity": "source_job_id",
}
JOB_FIELDS = ("source_job_id", "title", "company", "city")
T = TypeVar("T")


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        case = self.path.removeprefix("/")
        if case in RISK_MESSAGES:
            template = (FIXTURES / "risk.html").read_text(encoding="utf-8")
            html = template.format(reason=case, message=RISK_MESSAGES[case])
        elif case in {"normal", "missing-value"}:
            template = (FIXTURES / "profile.html").read_text(encoding="utf-8")
            sample = '<p id="fixture-value">本地样例</p>' if case == "normal" else ""
            html = template.replace("<!-- sample-value -->", sample)
        elif case == "unknown":
            html = "<!doctype html><title>Unknown fixture</title><p>Unknown fixture</p>"
        elif case == "login-required":
            html = (FIXTURES / "login.html").read_text(encoding="utf-8")
        elif case in JOB_CASES:
            html = (FIXTURES / "job.html").read_text(encoding="utf-8")
            if field := JOB_CASES[case]:
                html = html.replace(f'data-fixture-field="{field}"', "hidden")
        else:
            html = render_search_fixture(self.path, FIXTURES)
            if html is None:
                self.send_error(404)
                return

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@contextmanager
def fixture_site():
    with ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


class _GuardedFixturePage:
    def __init__(self, context: BrowserContext, origin: str):
        address = urlsplit(origin)
        if not address.port or origin != f"http://127.0.0.1:{address.port}":
            raise ValueError("Use a loopback HTTP origin for the local fixture.")
        self._origin = origin
        self._page = context.pages[0]
        self._expected_url = "about:blank"
        self._current_markers = self._required_markers
        self._reason: StopReason | None = None
        self._actions = 0
        context.route("**/*", self._route)

    @property
    def actions(self) -> int:
        return self._actions

    def navigate(self, case: str) -> None:
        self._check()
        if case not in self._cases:
            raise ValueError("Select a known local fixture case.")
        self._open(f"/{case}", self._required_markers)

    def _open(self, target: str, markers: tuple[str, ...]) -> None:
        self._expected_url = f"{self._origin}{target}"
        self._current_markers = markers
        self._actions += 1
        response = self._page.goto(self._expected_url, wait_until="domcontentloaded")
        if response is None or not response.ok:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        self._check()

    def _act(self, operation: Callable[[], T]) -> T:
        self._check()
        if self._expected_url == "about:blank":
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        self._actions += 1
        result = operation()
        self._check()
        return result

    def _check(self) -> None:
        if self._reason is not None:
            raise SafeStop(self._reason)
        if self._page.url != self._expected_url:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        if self._expected_url != "about:blank":
            reason = classify_fixture_page(self._page, self._current_markers)
            if reason is not None:
                self._stop(reason)

    def _stop(self, reason: StopReason) -> None:
        self._reason = reason
        raise SafeStop(reason)

    def _route(self, route: Route) -> None:
        if route.request.method == "GET" and route.request.url == self._expected_url:
            route.continue_()
        else:
            route.abort()


class FixturePage(_GuardedFixturePage):
    _cases = CASES
    _required_markers = ('main[data-fixture-page="profile"]',)

    def navigate(self, case: str = "normal") -> None:
        super().navigate(case)

    def read_sample(self) -> str:
        return self._act(lambda: self._page.locator("#fixture-value").inner_text())

    def read_marker(self) -> str:
        return self._act(lambda: self._page.locator("#fixture-marker").input_value())

    def write_marker(self, marker: str) -> None:
        self._act(lambda: self._page.locator("#fixture-marker").fill(marker))


@dataclass(frozen=True)
class FixtureJob:
    source_job_id: str
    title: str
    company: str
    city: str
    jd_text: str


class FixtureJobPage(_GuardedFixturePage):
    _cases = {*JOB_CASES, "login-required", "unknown", *RISK_MESSAGES}
    _main = 'main[data-fixture-page="job"]'
    _required_markers = (_main, f'{_main} > [data-fixture-session="logged-in"]')

    def read_job(self) -> FixtureJob:
        return self._act(self._read_detail)

    def _read_detail(self) -> FixtureJob:
        detail = self._detail_container()
        jd_text, jd_complete = self._read_jd(detail)
        if not jd_complete or not jd_text:
            self._stop(StopReason.PAGE_UNRECOGNIZED)

        fields = {field: self._field(detail, field) for field in JOB_FIELDS}
        if any(value is None for value in fields.values()):
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        return FixtureJob(**fields, jd_text=jd_text)

    def _detail_container(self) -> Locator:
        detail = self._page.locator(f"{self._main}:visible > [data-fixture-detail]:visible")
        if detail.count() != 1:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        return detail

    def _field(self, container: Locator, name: str) -> str | None:
        values = container.locator(f'[data-fixture-field="{name}"]:visible').all_inner_texts()
        if len(values) > 1:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        return (values[0].strip() or None) if values else None

    def _read_jd(self, detail: Locator) -> tuple[str | None, bool]:
        text = self._field(detail, "jd_text")
        complete = detail.locator('[data-fixture-field="jd_text"][data-fixture-jd="complete"]:visible')
        return text, complete.count() == 1
