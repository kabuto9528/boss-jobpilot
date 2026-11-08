from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseConfigError(ValueError):
    pass


class ScoringConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BrowserSettings:
    profile_root: Path
    timeout_ms: int


@dataclass(frozen=True)
class ScoringSettings:
    version: str
    document: dict[str, Any]


def _scoring_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise ScoringConfigError(f"Invalid scoring configuration: {name} must be an integer.")
    return value


def _validate_scoring_patterns(value: object, name: str) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ScoringConfigError(f"Invalid scoring configuration: {name} must be a nonempty list of patterns.")
    try:
        for pattern in value:
            re.compile(pattern, re.IGNORECASE)
    except re.error:
        raise ScoringConfigError(f"Invalid scoring configuration: {name} contains an invalid pattern.") from None


def _validate_scoring_document(document: object) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ScoringConfigError("Invalid scoring configuration: the YAML root must be a mapping.")
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ScoringConfigError("Invalid scoring configuration: version must be a nonempty string.")

    score = document.get("scoring")
    if not isinstance(score, dict):
        raise ScoringConfigError("Invalid scoring configuration: scoring must be a mapping.")
    base = _scoring_int(score.get("base"), "scoring.base")
    minimum = _scoring_int(score.get("minimum"), "scoring.minimum")
    maximum = _scoring_int(score.get("maximum"), "scoring.maximum")
    threshold = _scoring_int(score.get("recommendation_threshold"), "scoring.recommendation_threshold")
    if minimum < 0 or maximum > 100 or minimum >= maximum or not minimum <= base <= maximum or not minimum <= threshold <= maximum:
        raise ScoringConfigError("Invalid scoring configuration: score bounds, base, or recommendation threshold are inconsistent.")

    expected_order = ["internship", "campus", "junior", "social"]
    if document.get("type_order") != expected_order:
        raise ScoringConfigError("Invalid scoring configuration: type_order must be internship, campus, junior, social.")
    priorities = document.get("type_priority")
    if priorities != {"internship": 1, "campus": 2, "junior": 3, "social": 4}:
        raise ScoringConfigError("Invalid scoring configuration: type_priority must preserve the four defined levels.")

    type_rules = document.get("type_rules")
    if not isinstance(type_rules, list) or not type_rules:
        raise ScoringConfigError("Invalid scoring configuration: type_rules must be a nonempty list.")
    configured_types: list[str] = []
    supported_fields = {"title", "experience_text", "jd_text"}
    seen_ids: set[str] = set()
    for index, rule in enumerate(type_rules):
        name = f"type_rules[{index}]"
        if not isinstance(rule, dict) or rule.get("job_type") not in expected_order[:-1]:
            raise ScoringConfigError(f"Invalid scoring configuration: {name} has an invalid job_type.")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
            raise ScoringConfigError(f"Invalid scoring configuration: {name} has a missing or duplicate id.")
        seen_ids.add(rule_id)
        configured_types.append(rule["job_type"])
        signals = rule.get("signals")
        if not isinstance(signals, dict) or not signals:
            raise ScoringConfigError(f"Invalid scoring configuration: {name}.signals must be a mapping.")
        for field_name, patterns in signals.items():
            if field_name not in supported_fields:
                raise ScoringConfigError(f"Invalid scoring configuration: {name} uses an unsupported field.")
            _validate_scoring_patterns(patterns, f"{name}.{field_name}")
    if sorted(configured_types) != sorted(expected_order[:-1]) or len(configured_types) != len(set(configured_types)):
        raise ScoringConfigError("Invalid scoring configuration: add exactly one signal rule for internship, campus, and junior.")

    directions = document.get("directions")
    if not isinstance(directions, dict) or not isinstance(directions.get("rules"), list) or len(directions["rules"]) != 7:
        raise ScoringConfigError("Invalid scoring configuration: directions.rules must define all seven target directions.")
    fallback_count = 0
    for index, rule in enumerate(directions["rules"]):
        name = f"directions.rules[{index}]"
        if not isinstance(rule, dict):
            raise ScoringConfigError(f"Invalid scoring configuration: {name} must be a mapping.")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
            raise ScoringConfigError(f"Invalid scoring configuration: {name} has a missing or duplicate id.")
        seen_ids.add(rule_id)
        if not isinstance(rule.get("label"), str) or not rule["label"]:
            raise ScoringConfigError(f"Invalid scoring configuration: {name}.label is required.")
        points = _scoring_int(rule.get("points"), f"{name}.points")
        if points < 0:
            raise ScoringConfigError(f"Invalid scoring configuration: {name}.points cannot be negative.")
        if rule.get("fallback") is True:
            fallback_count += 1
            if (
                not isinstance(rule.get("when_types"), list)
                or not rule["when_types"]
                or any(kind not in expected_order[:-1] for kind in rule["when_types"])
            ):
                raise ScoringConfigError(f"Invalid scoring configuration: {name}.when_types is required for a fallback.")
        else:
            _validate_scoring_patterns(rule.get("title_patterns"), f"{name}.title_patterns")
            if "exclude_if_any" in rule:
                _validate_scoring_patterns(rule["exclude_if_any"], f"{name}.exclude_if_any")
    if fallback_count != 1:
        raise ScoringConfigError("Invalid scoring configuration: exactly one early-role direction fallback is required.")
    _scoring_int(directions.get("maximum_rules"), "directions.maximum_rules")
    if directions["maximum_rules"] != 1:
        raise ScoringConfigError("Invalid scoring configuration: only one direction rule may score a job.")

    for section_name in ("recruitment", "skills"):
        section = document.get(section_name)
        if not isinstance(section, dict) or not isinstance(section.get("rules"), list) or not section["rules"]:
            raise ScoringConfigError(f"Invalid scoring configuration: {section_name}.rules must be a nonempty list.")
        maximum_points = _scoring_int(section.get("maximum_points"), f"{section_name}.maximum_points")
        if maximum_points < 0:
            raise ScoringConfigError(f"Invalid scoring configuration: {section_name}.maximum_points cannot be negative.")
        for index, rule in enumerate(section["rules"]):
            name = f"{section_name}.rules[{index}]"
            if not isinstance(rule, dict):
                raise ScoringConfigError(f"Invalid scoring configuration: {name} must be a mapping.")
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
                raise ScoringConfigError(f"Invalid scoring configuration: {name} has a missing or duplicate id.")
            seen_ids.add(rule_id)
            if not isinstance(rule.get("label"), str) or not rule["label"]:
                raise ScoringConfigError(f"Invalid scoring configuration: {name}.label is required.")
            points = _scoring_int(rule.get("points"), f"{name}.points")
            if points < 0:
                raise ScoringConfigError(f"Invalid scoring configuration: {name}.points cannot be negative.")
            if section_name == "skills":
                _validate_scoring_patterns(rule.get("patterns"), f"{name}.patterns")
            elif rule.get("job_type") not in expected_order[:-1]:
                raise ScoringConfigError(f"Invalid scoring configuration: {name}.job_type is invalid.")

    experience = document.get("experience")
    if not isinstance(experience, dict):
        raise ScoringConfigError("Invalid scoring configuration: experience must be a mapping.")
    hard_min_years = _scoring_int(experience.get("hard_exclude_min_years"), "experience.hard_exclude_min_years")
    thresholds = experience.get("thresholds")
    if hard_min_years < 1 or not isinstance(thresholds, list) or not thresholds:
        raise ScoringConfigError("Invalid scoring configuration: experience thresholds are missing.")
    for index, threshold_rule in enumerate(thresholds):
        name = f"experience.thresholds[{index}]"
        if not isinstance(threshold_rule, dict):
            raise ScoringConfigError(f"Invalid scoring configuration: {name} must be a mapping.")
        if _scoring_int(threshold_rule.get("years"), f"{name}.years") < 1 or _scoring_int(threshold_rule.get("deduction"), f"{name}.deduction") < 0:
            raise ScoringConfigError(f"Invalid scoring configuration: {name} has invalid years or deduction.")
    senior = experience.get("senior")
    if not isinstance(senior, dict) or _scoring_int(senior.get("deduction"), "experience.senior.deduction") < 0:
        raise ScoringConfigError("Invalid scoring configuration: experience.senior is invalid.")
    _validate_scoring_patterns(senior.get("title_patterns"), "experience.senior.title_patterns")
    _validate_scoring_patterns(senior.get("requirement_patterns"), "experience.senior.requirement_patterns")

    hard_exclusions = document.get("hard_exclusions")
    if not isinstance(hard_exclusions, list) or not hard_exclusions:
        raise ScoringConfigError("Invalid scoring configuration: hard_exclusions must be a nonempty list.")
    for index, rule in enumerate(hard_exclusions):
        name = f"hard_exclusions[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"] or not isinstance(rule.get("label"), str):
            raise ScoringConfigError(f"Invalid scoring configuration: {name} is invalid.")
        if rule["id"] in seen_ids:
            raise ScoringConfigError(f"Invalid scoring configuration: {name} has a duplicate id.")
        seen_ids.add(rule["id"])
        if not any(key in rule for key in ("title_patterns", "jd_patterns")):
            raise ScoringConfigError(f"Invalid scoring configuration: {name} needs title_patterns or jd_patterns.")
        for field_name in ("title_patterns", "jd_patterns"):
            if field_name in rule:
                _validate_scoring_patterns(rule[field_name], f"{name}.{field_name}")
    negation = document.get("negation")
    if not isinstance(negation, dict):
        raise ScoringConfigError("Invalid scoring configuration: negation must be a mapping.")
    for key in ("before_patterns", "after_patterns", "whole_sentence_patterns"):
        if key in negation:
            _validate_scoring_patterns(negation[key], f"negation.{key}")
    return document


def load_scoring_settings(path: Path | None = None) -> ScoringSettings:
    config_path = path or PROJECT_ROOT / "config" / "scoring.yaml"
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError):
        raise ScoringConfigError("Check the YAML syntax and location of config/scoring.yaml.") from None
    validated = _validate_scoring_document(document)
    return ScoringSettings(version=validated["version"], document=validated)


def load_browser_settings() -> BrowserSettings:
    try:
        document = yaml.safe_load((PROJECT_ROOT / "config" / "app.yaml").read_text(encoding="utf-8-sig"))
        browser = document["browser"]
        relative_profile_root = Path(browser["profile_dir"])
        timeout_ms = browser["timeout_ms"]
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        raise ValueError("Check the browser configuration in config/app.yaml.") from None

    runtime_root = PROJECT_ROOT / "runtime"
    profile_root = (PROJECT_ROOT / relative_profile_root).resolve()
    if (
        relative_profile_root.is_absolute()
        or not profile_root.is_relative_to(runtime_root)
        or profile_root == runtime_root
        or type(timeout_ms) is not int
        or timeout_ms <= 0
    ):
        raise ValueError("Configure a project runtime profile directory and a positive browser timeout.")
    return BrowserSettings(profile_root, timeout_ms)


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)


def load_database_settings(*, testing: bool = False) -> DatabaseSettings:
    filename, database, user = (
        (".env.test", "boss_jobs_test", "boss_app_test")
        if testing
        else (".env", "boss_jobs", "boss_app")
    )
    try:
        with (PROJECT_ROOT / filename).open(encoding="utf-8-sig") as config_file:
            values = dotenv_values(stream=config_file, interpolate=False)
        port = int(values.get("DB_PORT") or "")
    except (OSError, ValueError):
        raise DatabaseConfigError(f"Check the database configuration in {filename}.") from None

    host = values.get("DB_HOST")
    password = values.get("DB_PASSWORD")
    if (
        host not in ("127.0.0.1", "localhost")
        or not 1 <= port <= 65535
        or values.get("DB_NAME") != database
        or values.get("DB_USER") != user
        or not password
        or password in ("replace_with_app_password", "replace_with_test_password")
    ):
        raise DatabaseConfigError(f"Check the database configuration in {filename}.")

    return DatabaseSettings(host, port, database, user, password)
