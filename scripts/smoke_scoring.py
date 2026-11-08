import argparse
import json
from pathlib import Path

import yaml

from backend.app.config import ScoringConfigError, load_scoring_settings
from backend.app.services.parser import VisibleJob, parse_job
from backend.app.services.scoring import score_job


def _load_case_job(values: dict):
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Score synthetic normalized jobs with local YAML rules.")
    parser.add_argument("--fixtures", required=True, help="Fixture directory or cases.yaml path")
    args = parser.parse_args()

    fixture_path = Path(args.fixtures)
    if fixture_path.is_dir():
        fixture_path /= "cases.yaml"
    try:
        cases = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))["cases"]
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        parser.error("Could not read a scoring fixture file containing a cases list.")

    try:
        settings = load_scoring_settings()
    except ScoringConfigError as error:
        parser.error(str(error))
    outputs = []
    failures = []
    for case in cases:
        try:
            job = _load_case_job(case["input"])
            result = score_job(job, settings)
            expected = case["expected"]
            actual = {
                "job_type": result.job_type,
                "priority": result.priority,
                "score": result.score,
                "recommended": result.recommended,
                "hard_exclusions": list(result.hard_exclusions),
            }
            for key, expected_value in expected.items():
                if actual.get(key) != expected_value:
                    failures.append({"case": case["id"], "field": key, "expected": expected_value, "actual": actual.get(key)})
            outputs.append({
                "case": case["id"],
                "job_type": result.job_type,
                "priority": result.priority,
                "score": result.score,
                "recommended": result.recommended,
                "hard_exclusions": list(result.hard_exclusions),
                "scoring_version": result.scoring_version,
            })
        except (KeyError, TypeError, ValueError) as error:
            failures.append({"case": case.get("id", "unknown"), "error": str(error)})

    print(json.dumps({"version": settings.version, "case_count": len(cases), "failures": failures, "results": outputs}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
