from dataclasses import dataclass
import re
from typing import Iterable

from ..config import ScoringSettings, load_scoring_settings
from .parser import NormalizedJob


@dataclass(frozen=True)
class ScoringEvidence:
    rule_id: str
    group: str
    field: str
    snippet: str
    delta: int


@dataclass(frozen=True)
class ScoringResult:
    identity_key: str
    job_type: str
    priority: int
    score: int
    recommended: bool
    reasons: tuple[str, ...]
    evidence: tuple[ScoringEvidence, ...]
    hard_exclusions: tuple[str, ...]
    scoring_version: str


@dataclass(frozen=True)
class _Match:
    field: str
    text: str
    start: int
    end: int

    @property
    def snippet(self) -> str:
        left = self.text.rfind("\n", 0, self.start) + 1
        right_candidates = [position for mark in ("\n", "。", "！", "？", "!", "?", "；", ";")
                            if (position := self.text.find(mark, self.end)) >= 0]
        right = min(right_candidates) if right_candidates else len(self.text)
        value = " ".join(self.text[left:right].split())
        if len(value) <= 120:
            return value
        local_start = max(0, self.start - left - 42)
        local_end = min(len(value), local_start + 110)
        return f"…{value[local_start:local_end]}…"


def _sentence_at(text: str, offset: int) -> tuple[int, int]:
    start = 0
    end = len(text)
    for match in re.finditer(r"[\n\r。！？!?；;]", text):
        if match.end() <= offset:
            start = match.end()
        elif match.start() >= offset:
            end = match.start()
            break
    return start, end


def _is_negated(text: str, start: int, end: int, settings: ScoringSettings) -> bool:
    negation = settings.document["negation"]
    sentence_start, sentence_end = _sentence_at(text, start)
    sentence = text[sentence_start:sentence_end]
    before = text[sentence_start:start]
    after = text[end:sentence_end].lstrip(" \t,，:：、")
    for pattern in negation.get("whole_sentence_patterns", []):
        if re.search(pattern, sentence, re.IGNORECASE):
            return True
    if any(re.search(pattern, before, re.IGNORECASE) for pattern in negation.get("before_patterns", [])):
        return True
    return any(re.match(pattern, after, re.IGNORECASE) for pattern in negation.get("after_patterns", []))


def _find_pattern(text: str | None, patterns: Iterable[str], field: str, settings: ScoringSettings) -> _Match | None:
    if not text:
        return None
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not _is_negated(text, match.start(), match.end(), settings):
                return _Match(field, text, match.start(), match.end())
    return None


def _field_value(job: NormalizedJob, field: str) -> str | None:
    if field == "title":
        return job.title
    if field == "experience_text":
        return job.experience_text
    if field == "jd_text":
        return job.jd_text
    return None


def _signal_match(job: NormalizedJob, signals: dict, settings: ScoringSettings) -> _Match | None:
    for field, patterns in signals.items():
        match = _find_pattern(_field_value(job, field), patterns, field, settings)
        if match:
            return match
    return None


def _add_evidence(
    evidence: list[ScoringEvidence],
    reasons: list[str],
    *,
    rule_id: str,
    group: str,
    match: _Match,
    delta: int,
    reason: str,
) -> None:
    evidence.append(ScoringEvidence(rule_id, group, match.field, match.snippet, delta))
    if delta:
        reasons.append(f"{reason}（{delta:+d}）")


def _credited_group(
    hits: list[tuple[dict, _Match]],
    maximum: int,
    group: str,
    evidence: list[ScoringEvidence],
    reasons: list[str],
) -> int:
    total = 0
    for rule, match in hits:
        credited = min(rule["points"], max(0, maximum - total))
        _add_evidence(
            evidence,
            reasons,
            rule_id=rule["id"],
            group=group,
            match=match,
            delta=credited,
            reason=rule["label"],
        )
        total += credited
    return total


_NUMBER_WORDS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _to_number(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBER_WORDS.get(value, 0)


def _years_in_text(text: str, *, exact_bare_year: bool) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    number = r"(?:\d{1,2}|[一二两三四五六七八九十])"
    range_pattern = re.compile(
        rf"(?<!\d)(?P<low>{number})\s*(?:年)?\s*[-–—~至到]\s*(?P<high>{number})\s*年",
        re.IGNORECASE,
    )
    ranges = list(range_pattern.finditer(text))
    for match in ranges:
        found.append((_to_number(match.group("low")), match.start(), match.end()))

    explicit = re.compile(
        rf"(?<![\d\-–—~至到])(?:(?:至少|不少于|不低于)\s*)?(?P<years>{number})\s*年"
        rf"(?P<suffix>以上|及以上|或以上|起|相关经验|经验)?",
        re.IGNORECASE,
    )
    for match in explicit.finditer(text):
        if any(match.start() < end and match.end() > start for _, start, end in ranges):
            continue
        suffix = match.group("suffix")
        if suffix or exact_bare_year:
            found.append((_to_number(match.group("years")), match.start(), match.end()))
    return found


def _required_years(job: NormalizedJob, settings: ScoringSettings) -> tuple[int, _Match] | None:
    candidates: list[tuple[int, _Match]] = []
    for field, text in (("experience_text", job.experience_text),):
        if not text:
            continue
        for years, start, end in _years_in_text(text, exact_bare_year=True):
            if not _is_negated(text, start, end, settings):
                candidates.append((years, _Match(field, text, start, end)))

    if job.jd_text:
        requirement_heading = re.compile(r"任职要求|岗位要求|职位要求|任职资格|招聘条件|经验要求|工作经验", re.IGNORECASE)
        requirement_language = re.compile(r"要求|需要|需具备|必须|至少|不少于|不低于", re.IGNORECASE)
        preference_language = re.compile(r"优先|加分|优待", re.IGNORECASE)
        section_active = False
        offset = 0
        for line in job.jd_text.splitlines():
            stripped = line.strip()
            if not stripped:
                section_active = False
                offset += len(line) + 1
                continue
            if requirement_heading.search(stripped):
                section_active = True
            required_context = section_active or bool(requirement_language.search(stripped))
            if required_context and not preference_language.search(stripped):
                for years, start, end in _years_in_text(stripped, exact_bare_year=True):
                    if not _is_negated(stripped, start, end, settings):
                        candidates.append((years, _Match("jd_text", job.jd_text, offset + start, offset + end)))
            offset += len(line) + 1

    return max(candidates, key=lambda item: item[0], default=None)


def _trusted_identity(job: NormalizedJob) -> bool:
    if job.source_job_id:
        return job.identity_key == f"{job.source}:{job.source_job_id}"
    return bool(re.fullmatch(r"url:[0-9a-f]{64}", job.identity_key))


def _hard_exclusion_match(job: NormalizedJob, rule: dict, settings: ScoringSettings) -> _Match | None:
    for field, key in (("title", "title_patterns"), ("jd_text", "jd_patterns")):
        patterns = rule.get(key)
        if patterns:
            match = _find_pattern(_field_value(job, field), patterns, field, settings)
            if match:
                return match
    return None


def score_job(job: NormalizedJob, rules: ScoringSettings | None = None) -> ScoringResult:
    settings = rules or load_scoring_settings()
    document = settings.document
    evidence: list[ScoringEvidence] = []
    reasons: list[str] = []

    type_hits: dict[str, tuple[dict, _Match]] = {}
    for rule in document["type_rules"]:
        match = _signal_match(job, rule["signals"], settings)
        if match:
            type_hits[rule["job_type"]] = (rule, match)

    job_type = next((kind for kind in document["type_order"] if kind in type_hits), "social")
    priority = document["type_priority"][job_type]
    if job_type == "social":
        type_match = _Match("title", job.title, 0, len(job.title))
        type_rule_id = "type.social.default"
        type_reason = "未发现明确的实习、校招或初级招聘标签，归为普通社招"
    else:
        type_rule, type_match = type_hits[job_type]
        type_rule_id = type_rule["id"]
        type_reason = f"类型判定为{ {'internship': '实习', 'campus': '校招或应届', 'junior': '初级'}[job_type] }（{type_match.field}证据）"
    evidence.append(ScoringEvidence(type_rule_id, "type", type_match.field, type_match.snippet, 0))
    reasons.append(type_reason)

    direction_rules = document["directions"]["rules"]
    direction_hits: list[tuple[dict, _Match]] = []
    for rule in direction_rules:
        if rule.get("fallback"):
            continue
        match = _find_pattern(job.title, rule["title_patterns"], "title", settings)
        if match and rule.get("exclude_if_any") and any(
            re.search(pattern, job.title, re.IGNORECASE) for pattern in rule["exclude_if_any"]
        ):
            match = None
        if match:
            direction_hits.append((rule, match))
    if direction_hits:
        direction_rule, direction_match = max(direction_hits, key=lambda item: item[0]["points"])
    else:
        direction_rule = next((rule for rule in direction_rules if rule.get("fallback") and job_type in rule["when_types"]), None)
        direction_match = type_hits[job_type][1] if direction_rule and job_type in type_hits else None
    direction_points = 0
    if direction_rule and direction_match:
        direction_points = direction_rule["points"]
        _add_evidence(
            evidence, reasons, rule_id=direction_rule["id"], group="direction", match=direction_match,
            delta=direction_points, reason=f"岗位方向：{direction_rule['label']}"
        )

    recruitment_rules = document["recruitment"]["rules"]
    recruitment_hits = [
        (rule, type_hits[rule["job_type"]][1])
        for rule in recruitment_rules
        if rule["job_type"] in type_hits
    ]
    recruitment_points = _credited_group(
        recruitment_hits, document["recruitment"]["maximum_points"],
        "recruitment", evidence, reasons,
    )

    skill_rules = document["skills"]["rules"]
    skill_hits: list[tuple[dict, _Match]] = []
    for rule in skill_rules:
        match = _find_pattern(job.title, rule["patterns"], "title", settings)
        if match is None:
            match = _find_pattern(job.jd_text, rule["patterns"], "jd_text", settings)
        if match:
            skill_hits.append((rule, match))
    skill_points = _credited_group(
        skill_hits, document["skills"]["maximum_points"], "skill", evidence, reasons
    )

    penalty_points = 0
    hard_exclusions: list[str] = []
    year_result = _required_years(job, settings)
    experience_config = document["experience"]
    if year_result:
        required_years, year_match = year_result
        applicable = [rule for rule in experience_config["thresholds"] if required_years >= rule["years"]]
        if applicable:
            threshold_rule = max(applicable, key=lambda rule: rule["years"])
            deduction = threshold_rule["deduction"]
            penalty_points += deduction
            rule_id = f"penalty.experience.{threshold_rule['years']}plus"
            evidence.append(ScoringEvidence(rule_id, "penalty", year_match.field, year_match.snippet, -deduction))
            reasons.append(f"明确要求至少 {threshold_rule['years']} 年经验（-{deduction}）")
        if required_years >= experience_config["hard_exclude_min_years"]:
            exclusion_id = "exclude.experience_3plus"
            hard_exclusions.append(exclusion_id)
            evidence.append(ScoringEvidence(exclusion_id, "hard_exclusion", year_match.field, year_match.snippet, 0))
            reasons.append("明确要求三年以上经验，禁止推荐")

    senior = experience_config["senior"]
    senior_match = _find_pattern(job.title, senior["title_patterns"], "title", settings)
    if senior_match is None:
        senior_match = _find_pattern(job.jd_text, senior["requirement_patterns"], "jd_text", settings)
    if senior_match:
        deduction = senior["deduction"]
        penalty_points += deduction
        evidence.append(ScoringEvidence("penalty.senior_role", "penalty", senior_match.field, senior_match.snippet, -deduction))
        reasons.append(f"标题或硬性要求指向高级岗位（-{deduction}）")
        exclusion_id = "exclude.senior_role"
        hard_exclusions.append(exclusion_id)
        evidence.append(ScoringEvidence(exclusion_id, "hard_exclusion", senior_match.field, senior_match.snippet, 0))

    for rule in document["hard_exclusions"]:
        match = _hard_exclusion_match(job, rule, settings)
        if match:
            hard_exclusions.append(rule["id"])
            evidence.append(ScoringEvidence(rule["id"], "hard_exclusion", match.field, match.snippet, 0))
            reasons.append(f"硬排除：{rule['label']}，禁止推荐")

    score_config = document["scoring"]
    raw_score = score_config["base"] + direction_points + recruitment_points + skill_points - penalty_points
    score = max(score_config["minimum"], min(score_config["maximum"], raw_score))
    if score != raw_score:
        evidence.append(ScoringEvidence("score.clamp", "boundary", "score", str(raw_score), score - raw_score))
        reasons.append(f"分数按配置边界截断（{score_config['minimum']}–{score_config['maximum']}）")

    has_complete_jd = job.jd_state == "complete" and bool((job.jd_text or "").strip())
    has_trusted_identity = _trusted_identity(job)
    has_relevance_evidence = direction_points > 0 or skill_points > 0
    if has_complete_jd:
        reasons.append("JD 完整")
    else:
        reasons.append("JD 缺失或不完整，禁止推荐")
    if has_trusted_identity:
        reasons.append("职位身份键有效")
    else:
        reasons.append("职位身份键无效，禁止推荐")
    if score >= score_config["recommendation_threshold"]:
        reasons.append(f"分数达到推荐阈值 {score_config['recommendation_threshold']}")
    else:
        reasons.append(f"分数低于推荐阈值 {score_config['recommendation_threshold']}")
    if has_relevance_evidence:
        reasons.append("命中目标岗位方向或可解释的运维技能证据")
    else:
        reasons.append("未命中目标岗位方向或运维技能证据，禁止推荐")
    if not hard_exclusions:
        reasons.append("未触发硬排除")

    recommended = (
        score >= score_config["recommendation_threshold"]
        and has_complete_jd
        and has_trusted_identity
        and has_relevance_evidence
        and not hard_exclusions
    )
    if recommended:
        reasons.append("满足本地推荐条件")

    return ScoringResult(
        identity_key=job.identity_key,
        job_type=job_type,
        priority=priority,
        score=score,
        recommended=recommended,
        reasons=tuple(reasons),
        evidence=tuple(evidence),
        hard_exclusions=tuple(hard_exclusions),
        scoring_version=settings.version,
    )


def rank_scored_jobs(results: Iterable[ScoringResult]) -> list[ScoringResult]:
    """Sort by job-type priority, then score; Python's stable sort preserves input order on ties."""
    return sorted(results, key=lambda result: (result.priority, -result.score))
