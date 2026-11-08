"""Verify the Stage 12 preview through the five pages and the isolated MySQL ledger."""

from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select, text

from backend.app.config import load_database_settings
from backend.app.db import create_database_engine
from backend.app.models.application import Application
from scripts.smoke_management_ui import BASE, dashboard_check, expect_status, read


CAPTURES = Path("runtime/stage-12")


def snapshot(engine):
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT DATABASE()")) == "boss_jobs_test"
        return connection.execute(select(Application.__table__).order_by(Application.id)).all()


def run(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{BASE}/dashboard")
    dashboard_check(page, "fixture")
    page.get_by_label("数据来源").select_option("boss")
    dashboard_check(page, "boss")

    page.get_by_role("menuitem", name="职位管理").click()
    page.get_by_label("搜索职位、公司或城市").fill("流程样例 · 预演候选 B")
    page.get_by_role("button", name="筛选", exact=True).click()
    page.get_by_role("button", name="流程样例 · 预演候选 B", exact=True).click()
    jobs = read(page, "jobs?source=fixture&page_size=100")["items"]
    demo = {row["identity_key"]: row for row in jobs if row["identity_key"].startswith("fixture:workflow-")}
    assert len(demo) >= 13
    expected_job_id = demo["fixture:workflow-eligible-b"]["id"]
    expect(page.get_by_text(re.compile(rf"^职位 ID\s+{expected_job_id}$"))).to_be_visible()
    page.keyboard.press("Escape")

    page.get_by_role("menuitem", name="投递记录").click()
    page.get_by_label("投递状态").select_option("uncertain")
    expect(page.locator("[data-status='uncertain']").filter(has_text="流程样例 · 平台保障")).to_be_visible()
    app_total = read(page, "applications?source=fixture")["total"]

    page.get_by_role("menuitem", name="系统设置").click()
    expect(page.get_by_text("真实 Auto 未启用", exact=True)).to_be_visible()
    settings = read(page, "settings")
    assert settings["capabilities"]["fixture"]["auto_preview_enabled"]
    assert not settings["capabilities"]["fixture"]["auto_enabled"]
    assert not settings["capabilities"]["boss"]["auto_enabled"]

    page.get_by_role("menuitem", name="任务中心").click()
    page.get_by_label("职位 ID（空格或逗号分隔）").fill("，".join(str(row["id"]) for row in demo.values()))
    page.get_by_label("预演候选上限").fill("2")
    with page.expect_response(lambda response: response.url.endswith("/api/tasks") and response.request.method == "POST") as accepted:
        page.get_by_role("button", name="创建 Auto 预演").click()
    assert accepted.value.status == 202
    task_id = accepted.value.json()["task_id"]
    task = expect_status(page, task_id, "succeeded")
    assert task["mode"] == "auto" and task["dry_run"] is True
    progress = task["progress"]
    assert progress["browser_submit_calls"] == 0
    assert len(progress["plan"]) == 2
    assert progress["plan"] == sorted(progress["plan"], key=lambda row: (row["priority"], -row["score"], -row["job_id"]))
    assert all(next(row for row in jobs if row["id"] == candidate["job_id"])["recommended"] for candidate in progress["plan"])
    for reason in ("APPLICATION_SUCCEEDED", "APPLICATION_UNCERTAIN", "APPLICATION_SENDING", "NOT_RECOMMENDED",
                   "JD_INCOMPLETE", "SCORING_STALE", "JOB_INACTIVE", "IDENTITY_UNVERIFIED", "MAX_JOBS"):
        assert reason in progress["skipped"], reason
        expect(page.get_by_test_id("auto-skips")).to_contain_text(reason)
    page.reload()
    assert expect_status(page, task_id, "succeeded")["progress"] == progress
    assert page.get_by_test_id("auto-plan").locator("li").evaluate_all(
        "(items) => items.map((item) => Number(item.dataset.jobId))"
    ) == [row["job_id"] for row in progress["plan"]]
    assert read(page, "applications?source=fixture")["total"] == app_total
    page.screenshot(path=CAPTURES / "auto-preview.png", full_page=True, animations="disabled")
    assert not errors, errors
    print(f"Auto preview #{task_id}: plan={[row['job_id'] for row in progress['plan']]}; skips={progress['skipped']}; fixture applications={app_total}")


def main():
    CAPTURES.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(load_database_settings(testing=True))
    try:
        before = snapshot(engine)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chromium", headless=True)
            try:
                run(browser.new_page(viewport={"width": 1440, "height": 1000}))
            finally:
                browser.close()
        assert snapshot(engine) == before
        print(f"MySQL applications: all {len(before)} rows match before and after the preview.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
