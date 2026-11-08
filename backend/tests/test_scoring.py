from pathlib import Path

import pytest
import yaml

from backend.app.config import ScoringConfigError, load_scoring_settings
from backend.app.services.parser import VisibleJob, parse_job
from backend.app.services.scoring import rank_scored_jobs, score_job


FIXTURE_FILE = Path(__file__).parent / "fixtures" / "scoring" / "cases.yaml"
SCORING_SETTINGS = load_scoring_settings()
SCORING_CASES = yaml.safe_load(FIXTURE_FILE.read_text(encoding="utf-8"))["cases"]


def _job(case: dict):
    values = case["input"]
    source_job_id = values["source_job_id"]
    return parse_job(
        VisibleJob(
            source="fixture",
            source_url=f"http://fixture.invalid/detail?job={source_job_id}",
            verified_identity_url=f"/detail?job={source_job_id}",
            source_job_id=source_job_id,
            title=values["title"],
            company="合成样例公司",
            city="武汉",
            experience_text=values.get("experience_text"),
            jd_text=values.get("jd_text"),
            jd_complete=values.get("jd_complete", False),
        )
    )


CASE_BY_ID = {case["id"]: case for case in SCORING_CASES}


@pytest.mark.parametrize("case", SCORING_CASES, ids=lambda case: case["id"])
def test_synthetic_fixture_has_exact_type_score_and_recommendation(case):
    job = _job(case)
    result = score_job(job, SCORING_SETTINGS)
    expected = case["expected"]

    assert result.job_type == expected["job_type"]
    assert result.priority == expected["priority"]
    assert result.score == expected["score"]
    assert result.recommended is expected["recommended"]
    assert list(result.hard_exclusions) == expected["hard_exclusions"]
    assert result.scoring_version == "stage-09.1"
    assert result.identity_key == job.identity_key
    assert result.reasons
    assert all(item.rule_id and item.field and item.snippet is not None for item in result.evidence)
    assert SCORING_SETTINGS.document["scoring"]["base"] + sum(item.delta for item in result.evidence) == result.score


def test_all_seven_directions_are_configured_and_evidenced():
    expected_direction_ids = {
        "ops_internship": "direction.ops_internship",
        "linux_ops_internship": "direction.linux_ops_internship",
        "cloud_ops_internship": "direction.cloud_ops_internship",
        "devops_internship": "direction.devops_internship",
        "network_ops_internship": "direction.system_network_it_ops_internship",
        "technical_support_internship": "direction.technical_support_internship",
        "other_early_role": "direction.other_early_role",
    }
    configured_ids = {rule["id"] for rule in SCORING_SETTINGS.document["directions"]["rules"]}
    assert configured_ids == set(expected_direction_ids.values())
    for case_id, rule_id in expected_direction_ids.items():
        result = score_job(_job(CASE_BY_ID[case_id]), SCORING_SETTINGS)
        assert rule_id in {item.rule_id for item in result.evidence}


def test_specific_linux_direction_is_not_swallowed_by_generic_ops_rule():
    result = score_job(_job(CASE_BY_ID["linux_ops_internship"]), SCORING_SETTINGS)
    assert {item.rule_id for item in result.evidence if item.group == "direction"} == {
        "direction.linux_ops_internship"
    }


def test_duplicate_skill_synonyms_are_credited_once_and_group_caps_apply():
    result = score_job(_job(CASE_BY_ID["linux_ops_internship"]), SCORING_SETTINGS)
    linux_hits = [item for item in result.evidence if item.rule_id == "skill.linux"]
    assert len(linux_hits) == 1
    assert linux_hits[0].delta == 6

    capped = score_job(_job(CASE_BY_ID["upper_group_caps_clamp_to_100"]), SCORING_SETTINGS)
    assert sum(item.delta for item in capped.evidence if item.group == "recruitment") == 20
    assert sum(item.delta for item in capped.evidence if item.group == "skill") == 36
    assert sum(item.delta for item in capped.evidence if item.group == "direction") == 24
    assert capped.score == 100


def test_negated_internship_phrase_does_not_change_social_type_or_direction():
    job = parse_job(
        VisibleJob(
            source="fixture",
            source_url="http://fixture.invalid/detail?job=internship-priority",
            verified_identity_url="/detail?job=internship-priority",
            source_job_id="internship-priority",
            title="运维工程师（实习转正者优先）",
            company="合成样例公司",
            jd_text="负责 Linux 服务器运维。",
            jd_complete=True,
        )
    )
    result = score_job(job, SCORING_SETTINGS)
    assert result.job_type == "social"
    assert "direction.ops_internship" not in {item.rule_id for item in result.evidence}
    assert result.score == 30


def test_unneeded_skill_is_not_counted_as_positive_evidence():
    result = score_job(_job(CASE_BY_ID["explicitly_unneeded_skill_gets_no_credit"]), SCORING_SETTINGS)
    assert "skill.linux" not in {item.rule_id for item in result.evidence}
    assert result.score == 38


def test_priority_sort_beats_score_and_equal_keys_keep_input_order():
    low_intern = parse_job(
        VisibleJob(
            source="fixture", source_url="http://fixture.invalid/i", verified_identity_url="/i",
            source_job_id="tie-intern-1", title="实习生-文员", company="样例公司"
        )
    )
    same_priority_tie = parse_job(
        VisibleJob(
            source="fixture", source_url="http://fixture.invalid/i2", verified_identity_url="/i2",
            source_job_id="tie-intern-2", title="实习生-档案", company="样例公司"
        )
    )
    high_social = parse_job(
        VisibleJob(
            source="fixture", source_url="http://fixture.invalid/s", verified_identity_url="/s",
            source_job_id="high-social", title="运维工程师", company="样例公司",
            jd_text="Linux Shell Python Docker Nginx MySQL 网络 服务器 云计算 DevOps Prometheus Grafana Jenkins Kubernetes",
            jd_complete=True,
        )
    )
    intern_results = [score_job(low_intern, SCORING_SETTINGS), score_job(same_priority_tie, SCORING_SETTINGS)]
    social_result = score_job(high_social, SCORING_SETTINGS)
    assert social_result.job_type == "social"
    assert social_result.score > intern_results[0].score
    assert [result.identity_key for result in rank_scored_jobs([social_result, *intern_results])] == [
        low_intern.identity_key,
        same_priority_tie.identity_key,
        high_social.identity_key,
    ]


def test_repeated_scoring_with_same_rules_is_deterministic():
    job = _job(CASE_BY_ID["upper_group_caps_clamp_to_100"])
    assert score_job(job, SCORING_SETTINGS) == score_job(job, SCORING_SETTINGS)


def test_bad_scoring_configuration_fails_with_clear_validation_error(tmp_path):
    document = yaml.safe_load((Path(__file__).parents[2] / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    document["scoring"]["maximum"] = 40
    path = tmp_path / "bad-scoring.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ScoringConfigError, match="score bounds"):
        load_scoring_settings(path)
