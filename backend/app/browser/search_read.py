from dataclasses import dataclass, field
from typing import Callable

from playwright.sync_api import BrowserContext

from backend.app.browser.fixture import FixtureJobPage
from backend.app.browser.fixture_search_pages import DETAIL_TARGET, PAGE_NUMBER, search_prefix
from backend.app.browser.safe_stop import SafeStop, StopReason
from backend.app.services.parser import JobParseError, NormalizedJob, VisibleJob, parse_job


@dataclass(frozen=True)
class _Candidate:
    target: str
    source_job_id: str | None


class _FixtureSearchPage(FixtureJobPage):
    _search_main = 'main[data-fixture-page="search"]'
    _search_markers = (_search_main, f'{_search_main} > [data-fixture-session="logged-in"]')

    def list_page(self, target: str, keyword: str) -> tuple[list[_Candidate], str | None]:
        self._check()
        self._open(target, self._search_markers)
        return self._act(lambda: self._read_list(keyword))

    def detail_page(self, candidate: _Candidate) -> VisibleJob:
        self._check()
        self._open(candidate.target, self._required_markers)
        return self._act(lambda: self._read_candidate(candidate))

    def _read_list(self, keyword: str) -> tuple[list[_Candidate], str | None]:
        main = self._page.locator(f"{self._search_main}:visible")
        if self._field(main, "keyword") != keyword:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        results = main.locator(":scope > [data-fixture-results]:visible")
        empty = main.locator(":scope > [data-fixture-empty]:visible").all_inner_texts()
        next_links = main.locator(":scope > a[data-fixture-next]:visible").all()
        if empty == ["没有符合条件的职位"] and results.count() == 0 and not next_links:
            return [], None
        if results.count() != 1 or empty or len(next_links) > 1:
            self._stop(StopReason.PAGE_UNRECOGNIZED)

        next_target = None
        if next_links:
            next_target = next_links[0].get_attribute("href") or ""
            prefix = search_prefix(keyword)
            if not next_target.startswith(prefix) or not PAGE_NUMBER.fullmatch(next_target[len(prefix):]):
                self._stop(StopReason.PAGE_UNRECOGNIZED)

        cards = results.locator(":scope > [data-fixture-card]:visible").all()
        if not cards:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        candidates = []
        for card in cards:
            links = card.locator(":scope > a:visible").all()
            if len(links) != 1:
                self._stop(StopReason.PAGE_UNRECOGNIZED)
            target = links[0].get_attribute("href") or ""
            if target not in {"/logged-in", "/missing-identity"} and not DETAIL_TARGET.fullmatch(target):
                self._stop(StopReason.PAGE_UNRECOGNIZED)
            candidates.append(_Candidate(target, self._field(card, "source_job_id")))
        return candidates, next_target

    def _read_candidate(self, candidate: _Candidate) -> VisibleJob:
        detail = self._detail_container()
        source_job_id = self._field(detail, "source_job_id")
        if candidate.source_job_id is not None and candidate.source_job_id != source_job_id:
            self._stop(StopReason.PAGE_UNRECOGNIZED)
        jd_text, jd_complete = self._read_jd(detail)
        # The local /detail route identifies a single job by its query key.
        # The temporary loopback port is a transport detail, so it stays out of the identity.
        identity_url = candidate.target if DETAIL_TARGET.fullmatch(candidate.target) else None
        return VisibleJob(
            source="fixture",
            source_url=self._page.url,
            source_job_id=source_job_id,
            verified_identity_url=identity_url,
            title=self._field(detail, "title"),
            company=self._field(detail, "company"),
            city=self._field(detail, "city"),
            salary_text=self._field(detail, "salary_text"),
            experience_text=self._field(detail, "experience_text"),
            jd_text=jd_text,
            jd_complete=jd_complete,
        )


@dataclass
class SearchResult:
    jobs: list[NormalizedJob] = field(default_factory=list)
    pages_attempted: int = 0
    details_attempted: int = 0
    duplicates: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "exhausted"


class SearchCancelled(RuntimeError):
    pass


def read_fixture_search(
    context: BrowserContext,
    origin: str,
    *,
    keyword: str,
    max_pages: int,
    max_jobs: int,
    should_stop: Callable[[], bool] | None = None,
    on_job: Callable[[NormalizedJob], None] | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
) -> SearchResult:
    keyword = " ".join(keyword.split())
    if not keyword:
        raise ValueError("A search keyword is required.")
    if any(type(limit) is not int or limit < 1 for limit in (max_pages, max_jobs)):
        raise ValueError("Page and job limits must be positive integers.")

    page = _FixtureSearchPage(context, origin)
    result = SearchResult()
    try:
        result.stop_reason = _walk(
            page,
            result,
            keyword,
            max_pages,
            max_jobs,
            should_stop=should_stop,
            on_job=on_job,
            on_progress=on_progress,
        )
    except SafeStop as stopped:
        result.stop_reason = stopped.reason.value
    except SearchCancelled:
        result.stop_reason = "USER_STOPPED"
    return result


def _walk(
    page: _FixtureSearchPage,
    result: SearchResult,
    keyword: str,
    max_pages: int,
    max_jobs: int,
    *,
    should_stop: Callable[[], bool] | None,
    on_job: Callable[[NormalizedJob], None] | None,
    on_progress: Callable[[str, dict], None] | None,
) -> str:
    def checkpoint() -> None:
        if should_stop is not None and should_stop():
            raise SearchCancelled()

    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(
                phase,
                {
                    "pages_attempted": result.pages_attempted,
                    "details_attempted": result.details_attempted,
                    "jobs_found": len(result.jobs),
                    "duplicates": result.duplicates,
                    "skipped": dict(result.skipped),
                },
            )

    visited_pages = set()
    batches = set()
    resolved_batches = set()
    visited_details: dict[str, str | None] = {}
    identity_by_target: dict[str, str] = {}
    identities = set()
    target = f"{search_prefix(keyword)}1"

    while result.pages_attempted < max_pages:
        checkpoint()
        if target in visited_pages:
            return "page_not_advancing"
        visited_pages.add(target)
        result.pages_attempted += 1
        report("reading")
        candidates, next_target = page.list_page(target, keyword)
        if not candidates:
            return "empty_results" if result.pages_attempted == 1 else "exhausted"
        batch = frozenset(candidates)
        if batch in batches:
            return "page_not_advancing"
        batches.add(batch)

        for candidate in candidates:
            checkpoint()
            if candidate.target in visited_details:
                if candidate.source_job_id is not None and candidate.source_job_id != visited_details[candidate.target]:
                    raise SafeStop(StopReason.PAGE_UNRECOGNIZED)
                result.duplicates += 1
                continue
            if result.details_attempted == max_jobs:
                return "max_jobs"
            result.details_attempted += 1
            report("reading")
            visible = page.detail_page(candidate)
            visited_details[candidate.target] = visible.source_job_id
            try:
                job = parse_job(visible)
            except JobParseError as error:
                result.skipped[error.reason] = result.skipped.get(error.reason, 0) + 1
                continue
            identity_by_target[candidate.target] = job.identity_key
            if job.identity_key in identities:
                result.duplicates += 1
                continue
            identities.add(job.identity_key)
            result.jobs.append(job)
            if on_job is not None:
                on_job(job)
            report("writing")

        resolved_batch = frozenset(
            identity_by_target.get(candidate.target, candidate.target) for candidate in candidates
        )
        if resolved_batch in resolved_batches:
            return "page_not_advancing"
        resolved_batches.add(resolved_batch)
        if next_target is None:
            return "exhausted"
        if result.details_attempted == max_jobs:
            return "max_jobs"
        target = next_target
    return "max_pages"
