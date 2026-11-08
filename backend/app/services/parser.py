from dataclasses import dataclass
from hashlib import sha256
from typing import Literal


@dataclass(frozen=True)
class VisibleJob:
    source: Literal["fixture", "boss"]
    source_url: str
    title: str | None
    company: str | None
    source_job_id: str | None = None
    # Set only by the reader when the URL uniquely identifies a job across reads.
    verified_identity_url: str | None = None
    city: str | None = None
    salary_text: str | None = None
    experience_text: str | None = None
    jd_text: str | None = None
    jd_complete: bool = False


@dataclass(frozen=True)
class NormalizedJob:
    source: Literal["fixture", "boss"]
    source_job_id: str | None
    identity_key: str
    source_url: str
    title: str
    company: str
    city: str | None
    salary_text: str | None
    experience_text: str | None
    jd_text: str | None
    jd_state: Literal["complete", "partial", "missing"]
    availability: Literal["unknown"] = "unknown"


class JobParseError(ValueError):
    def __init__(self, reason: Literal["missing_identity", "missing_fields"]):
        super().__init__(reason)
        self.reason = reason


def _line(text: str | None) -> str | None:
    return " ".join((text or "").split()) or None


def parse_job(visible: VisibleJob) -> NormalizedJob:
    source_job_id = (visible.source_job_id or "").strip() or None
    if source_job_id is not None:
        identity_key = f"{visible.source}:{source_job_id}"
    elif visible.verified_identity_url:
        digest = sha256(visible.verified_identity_url.encode("utf-8")).hexdigest()
        identity_key = f"url:{digest}"
    else:
        raise JobParseError("missing_identity")

    title = _line(visible.title)
    company = _line(visible.company)
    if title is None or company is None:
        raise JobParseError("missing_fields")

    jd_text = "\n".join(_line(line) or "" for line in (visible.jd_text or "").splitlines()).strip() or None
    jd_state: Literal["complete", "partial", "missing"] = "missing"
    if jd_text is not None:
        jd_state = "complete" if visible.jd_complete else "partial"

    return NormalizedJob(
        source=visible.source,
        source_job_id=source_job_id,
        identity_key=identity_key,
        source_url=visible.source_url,
        title=title,
        company=company,
        city=_line(visible.city),
        salary_text=_line(visible.salary_text),
        experience_text=_line(visible.experience_text),
        jd_text=jd_text,
        jd_state=jd_state,
    )
