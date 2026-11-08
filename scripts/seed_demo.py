import argparse
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.config import load_database_settings, load_scoring_settings
from backend.app.db import create_database_engine
from backend.app.models.application import Application
from backend.app.models.job import Job


JOBS = (
    {
        "source_job_id": "fixture-ops-intern-01",
        "identity_key": "fixture:ops-intern-01",
        "title": "平台运维实习生",
        "company": "青云科技 🚀",
        "city": "上海",
        "salary_text": "180–220 元/天",
        "experience_text": "在校生 / 应届生",
        "jd_text": "参与 Linux 与云平台日常运维。\n要求：熟悉 Python，能阅读中文技术文档。\n团队标记：星际探索 ✨",
        "jd_state": "complete",
        "availability": "active",
        "job_type": "实习",
        "priority": 1,
        "score": 88.0,
        "recommended": True,
        "score_reasons": ["Linux 运维方向匹配", "接受在校生"],
        "scoring_version": "fixture-v1",
    },
    {
        "source_job_id": "fixture-data-intern-02",
        "identity_key": "fixture:data-intern-02",
        "title": "数据平台实习生",
        "company": "星河数据",
        "city": "杭州",
        "salary_text": "200 元/天",
        "experience_text": "经验不限",
        "jd_text": "协助维护数据平台与自动化任务。要求：掌握 SQL、Linux 基础。",
        "jd_state": "complete",
        "availability": "active",
        "job_type": "实习",
        "priority": 1,
        "score": 88.0,
        "recommended": True,
        "score_reasons": ["数据平台方向匹配"],
        "scoring_version": "fixture-v1",
    },
    {
        "source_job_id": "fixture-cloud-intern-03",
        "identity_key": "fixture:cloud-intern-03",
        "title": "云计算实习生",
        "company": "白云软件",
        "city": "苏州",
        "salary_text": "面议",
        "experience_text": "在校生",
        "jd_text": None,
        "jd_state": "missing",
        "availability": "unknown",
        "job_type": "实习",
        "priority": 1,
        "score": None,
        "recommended": False,
        "score_reasons": None,
        "scoring_version": None,
    },
    {
        "source_job_id": "fixture-platform-engineer-04",
        "identity_key": "fixture:platform-engineer-04",
        "title": "高级平台工程师",
        "company": "北辰网络",
        "city": "北京",
        "salary_text": "30–45K·14薪",
        "experience_text": "3–5 年",
        "jd_text": "负责云原生平台建设与稳定性治理。",
        "jd_state": "complete",
        "availability": "active",
        "job_type": "社招",
        "priority": 4,
        "score": 99.0,
        "recommended": False,
        "score_reasons": ["经验要求超出目标范围"],
        "scoring_version": "fixture-v1",
    },
    {
        "source_job_id": "fixture-campus-sre-05",
        "identity_key": "fixture:campus-sre-05",
        "title": "SRE 校招工程师",
        "company": "晨星科技",
        "city": "深圳",
        "salary_text": "18–25K",
        "experience_text": "应届生",
        "jd_text": "参与可观测性、发布平台与故障响应流程建设。",
        "jd_state": "complete",
        "availability": "active",
        "job_type": "校招",
        "priority": 2,
        "score": 74.0,
        "recommended": True,
        "score_reasons": ["基础设施方向匹配"],
        "scoring_version": "fixture-v1",
    },
    {
        "source_job_id": "fixture-ops-intern-low-score-06",
        "identity_key": "fixture:ops-intern-low-score-06",
        "title": "数字化运维实习生",
        "company": "栈桥工程",
        "city": "南京",
        "salary_text": "150–180 元/天",
        "experience_text": "在校生",
        "jd_text": "协助处理运维工单并整理日常文档。优先考虑有 Linux 或 Python 学习经历的同学。",
        "jd_state": "complete",
        "availability": "active",
        "job_type": "实习",
        "priority": 1,
        "score": 42.0,
        "recommended": False,
        "score_reasons": ["基础运维经历较少，匹配分低于推荐阈值"],
        "scoring_version": "fixture-v1",
    },
)


def seed_jobs(engine: Engine, jobs=JOBS) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        {
            **job,
            "source": "fixture",
            "source_url": f"http://127.0.0.1:8765/jobs/{job['source_job_id']}",
            "first_seen_at": now,
            "last_seen_at": now,
        }
        for job in jobs
    ]
    statement = insert(Job).values(rows)
    statement = statement.on_duplicate_key_update(
        source_job_id=statement.inserted.source_job_id,
        source_url=statement.inserted.source_url,
        title=statement.inserted.title,
        company=statement.inserted.company,
        city=statement.inserted.city,
        salary_text=statement.inserted.salary_text,
        experience_text=statement.inserted.experience_text,
        jd_text=statement.inserted.jd_text,
        jd_state=statement.inserted.jd_state,
        availability=statement.inserted.availability,
        job_type=statement.inserted.job_type,
        priority=statement.inserted.priority,
        score=statement.inserted.score,
        recommended=statement.inserted.recommended,
        score_reasons=statement.inserted.score_reasons,
        scoring_version=statement.inserted.scoring_version,
        last_seen_at=statement.inserted.last_seen_at,
    )
    with engine.begin() as connection:
        connection.execute(statement)
    return len(rows)


WORKFLOW_TITLES = ("运维支持", "数据维护", "云资源巡检", "平台保障", "可观测性支持", "自动化工单")
WORKFLOW_JOBS = tuple(
    {
        **job,
        "source_job_id": f"workflow-{index}",
        "identity_key": f"fixture:workflow-{index}",
        "title": f"流程样例 · {title}",
    }
    for index, (job, title) in enumerate(zip(JOBS, WORKFLOW_TITLES, strict=True), 1)
)
WORKFLOW_PREVIEW_JOBS = (
    ("eligible-a", "预演候选 A", {}),
    ("eligible-b", "预演候选 B", {}),
    ("eligible-c", "预演候选 C", {"priority": 2}),
    ("low-score", "预演低分对照", {"score": 30, "recommended": False}),
    ("stale", "预演旧规则对照", {"scoring_version": "fixture-v1"}),
    ("inactive", "预演已下线对照", {"availability": "inactive"}),
    ("identity", "预演身份待核实对照", {"source_job_id": None}),
)
WORKFLOW_STATES = (
    ("pending", None),
    ("succeeded", "样例证据：详情显示已投递"),
    ("failed", "样例证据：操作未完成"),
    ("uncertain", "样例证据：缺少确认结果，需要人工核对"),
    ("sending", "样例记录：模拟投递中"),
)


def seed_workflow(engine: Engine) -> tuple[int, int]:
    version = load_scoring_settings().version
    controls = tuple(
        {
            **JOBS[0], "source_job_id": f"workflow-{key}", "identity_key": f"fixture:workflow-{key}",
            "title": f"流程样例 · {title}", "scoring_version": version, **overrides,
        }
        for key, title, overrides in WORKFLOW_PREVIEW_JOBS
    )
    jobs = tuple(
        {
            **job, "scoring_version": version,
            **({"recommended": True, "score": 78} if index == 3 else {}),
        }
        for index, job in enumerate(WORKFLOW_JOBS)
    )
    job_count = seed_jobs(engine, (*jobs, *controls))
    now = datetime.now(UTC).replace(tzinfo=None)
    application_count = 0
    with Session(engine) as session, session.begin():
        for job, (status, evidence) in zip(jobs, WORKFLOW_STATES):
            job_id = session.scalar(select(Job.id).where(
                Job.source == "fixture", Job.identity_key == job["identity_key"],
            ).with_for_update())
            # Re-seeding must not reset records after a user has confirmed them.
            if session.scalar(select(Application.id).where(Application.job_id == job_id).limit(1)) is not None:
                continue
            session.add(Application(
                job_id=job_id, origin="fixture", status=status, evidence_summary=evidence,
                result_code="DEMO_SAMPLE" if evidence else None,
                started_at=None if status == "pending" else now,
                resolved_at=now if status in ("succeeded", "failed") else None,
            ))
            application_count += 1
    return job_count, application_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fixture-only demo records.")
    parser.add_argument("--dataset", choices=("jobs", "workflow"), required=True)
    parser.add_argument("--test-db", action="store_true", help="Use the isolated .env.test database.")
    args = parser.parse_args()

    engine = create_database_engine(load_database_settings(testing=args.test_db))
    try:
        if args.dataset == "workflow":
            count, applications = seed_workflow(engine)
            print(f"Added {applications} workflow sample applications; existing records were preserved.")
        else:
            count = seed_jobs(engine)
        with engine.connect() as connection:
            total = connection.execute(select(func.count()).select_from(Job).where(Job.source == "fixture")).scalar_one()
        print(f"Upserted {count} fixture jobs; fixture total is {total}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
