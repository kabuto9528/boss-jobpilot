from dataclasses import replace

import pytest

from backend.app.services.parser import JobParseError, VisibleJob, parse_job


VISIBLE = VisibleJob(
    source="fixture",
    source_url="http://127.0.0.1:30001/detail?job=ops-a",
    verified_identity_url="/detail?job=ops-a",
    source_job_id=" Ab-C ",
    title=" 运维　 实习生 ",
    company=" 示例科技\t ",
    city="  武汉  ",
    salary_text="150–200   元/天",
    experience_text=" \t",
    jd_text="\r\n 岗位职责\r\n维护  Linux\r\n\r\n 任职要求\r\n熟悉\tShell\r\n",
    jd_complete=True,
)


def test_normalizes_visible_fields_and_preserves_jd_paragraphs():
    job = parse_job(VISIBLE)
    assert job.source == "fixture"
    assert job.source_url == VISIBLE.source_url
    assert job.source_job_id == "Ab-C"
    assert job.identity_key == "fixture:Ab-C"
    assert (job.title, job.company, job.city) == ("运维 实习生", "示例科技", "武汉")
    assert (job.salary_text, job.experience_text) == ("150–200 元/天", None)
    assert job.jd_text == "岗位职责\n维护 Linux\n\n任职要求\n熟悉 Shell"
    assert job.jd_state == "complete"
    assert job.availability == "unknown"


def test_identity_prefers_case_sensitive_ids_and_preserves_distinct_url_keys():
    first = parse_job(VISIBLE)
    other_id = parse_job(replace(VISIBLE, source_job_id="ab-c"))
    assert first.title == other_id.title and first.company == other_id.company
    assert first.identity_key != other_id.identity_key

    link_only = replace(VISIBLE, source_job_id=None)
    fallback = parse_job(link_only)
    new_port = parse_job(replace(link_only, source_url=VISIBLE.source_url.replace("30001", "30002")))
    other_url = parse_job(replace(
        link_only,
        source_url=VISIBLE.source_url.replace("ops-a", "ops-b"),
        verified_identity_url="/detail?job=ops-b",
    ))
    assert fallback.source_job_id is None
    assert fallback.identity_key.startswith("url:")
    assert fallback.identity_key == new_port.identity_key
    assert fallback.identity_key != other_url.identity_key


@pytest.mark.parametrize(
    ("jd", "complete", "expected", "state"),
    [(None, False, None, "missing"), (" \r\n ", True, None, "missing"), (" 可见片段 ", False, "可见片段", "partial")],
)
def test_reports_missing_and_partial_jd(jd, complete, expected, state):
    job = parse_job(replace(VISIBLE, jd_text=jd, jd_complete=complete))
    assert (job.jd_text, job.jd_state) == (expected, state)
    assert job.identity_key == "fixture:Ab-C"


def test_skips_unverified_identity_and_missing_required_fields():
    with pytest.raises(JobParseError, match="^missing_identity$"):
        parse_job(replace(VISIBLE, source_job_id=" ", verified_identity_url=None))
    with pytest.raises(JobParseError, match="^missing_fields$"):
        parse_job(replace(VISIBLE, company=" "))
