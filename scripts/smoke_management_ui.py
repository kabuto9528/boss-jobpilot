"""Exercise the five pages against the seeded, isolated stage-11 Vite/API pair."""

from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


BASE = "http://127.0.0.1:5174"
CAPTURES = Path("runtime/stage-11")
EXPECTED = {"pending": "待投递", "sending": "投递中", "succeeded": "已投递", "failed": "失败", "uncertain": "待核对"}


def read(page, path):
    response = page.request.get(f"{BASE}/api/{path}")
    assert response.ok, f"{path} returned HTTP {response.status}"
    return response.json()


def review(page, keyword):
    page.get_by_label("关键词（换行或逗号分隔）").fill(keyword)
    page.get_by_label("最多页数").fill("1")
    page.get_by_label("最多职位数").fill("5")
    with page.expect_response(lambda response: response.url.endswith("/api/tasks") and response.request.method == "POST") as accepted:
        page.get_by_role("button", name="创建 Review").click()
    assert accepted.value.status == 202
    task_id = accepted.value.json()["task_id"]
    expect(page).to_have_url(re.compile(rf"/tasks\?task={task_id}$"))
    expect(page.locator(f"[data-task-id='{task_id}']")).to_be_visible()
    return task_id


def expect_status(page, task_id, status):
    expect(page.get_by_role("heading", name=f"任务详情 #{task_id}")).to_be_visible()
    expect(page.locator(f"[data-task-status='{status}']")).to_be_visible(timeout=12000)
    return read(page, f"tasks/{task_id}")


def dashboard_check(page, source):
    data = read(page, f"dashboard?source={source}")
    jobs = read(page, f"jobs?source={source}")
    recommended = read(page, f"jobs?source={source}&recommended=true")
    assert (data["jobs_total"], data["jobs_recommended"]) == (jobs["total"], recommended["total"])
    expect(page.locator("[data-metric='jobs-total']")).to_have_text(str(jobs["total"]))
    expect(page.locator("[data-metric='jobs-recommended']")).to_have_text(str(recommended["total"]))
    for status in EXPECTED:
        total = read(page, f"applications?source={source}&status={status}")["total"]
        assert data["applications"][status] == total
        expect(page.locator(f"[data-metric='{status}']")).to_have_text(str(total))
    print(f"Dashboard {source}: jobs={jobs['total']}, recommended={recommended['total']}, applications={data['applications']}")


def run(page):
    polls = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: polls.append(request.url) if request.method == "GET" and re.search(r"/api/tasks/\d+$", request.url) else None)
    page.goto(f"{BASE}/dashboard")
    expect(page.get_by_role("heading", name="总览")).to_be_visible()
    expect(page.get_by_text("服务正常")).to_be_visible()
    dashboard_check(page, "fixture")
    page.screenshot(path=CAPTURES / "dashboard.png", full_page=True, animations="disabled")
    page.get_by_label("数据来源").select_option("boss")
    expect(page).to_have_url(re.compile(r"source=boss"))
    dashboard_check(page, "boss")
    page.get_by_label("数据来源").select_option("fixture")
    page.get_by_role("link", name=re.compile("推荐职位")).click()
    expect(page).to_have_url(re.compile(r"/jobs\?source=fixture&recommended=true"))
    expect(page.get_by_label("推荐筛选")).to_have_value("true")
    expect(page.get_by_role("heading", name="职位管理")).to_be_visible()

    page.get_by_role("menuitem", name="投递记录").click()
    expect(page.get_by_role("heading", name="投递记录")).to_be_visible()
    for status, label in EXPECTED.items():
        page.get_by_label("投递状态").select_option(status)
        row = page.locator(f"[data-status='{status}']").filter(has_text="流程样例").first
        expect(row.get_by_text(label, exact=True)).to_be_visible()
    page.get_by_label("投递状态").select_option("")
    expect(page.locator("[data-status='uncertain']").first).to_be_visible()
    page.screenshot(path=CAPTURES / "applications.png", full_page=True, animations="disabled")

    page.get_by_role("menuitem", name="职位管理").click()
    page.get_by_label("搜索职位、公司或城市").fill("流程样例 · 自动化工单")
    page.get_by_role("button", name="筛选", exact=True).click()
    page.get_by_role("button", name="流程样例 · 自动化工单", exact=True).click()
    page.get_by_role("link", name="建立待投递记录").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("选择职位").locator("option:checked")).to_contain_text("自动化工单")
    dialog.get_by_role("button", name="建立待投递", exact=True).click()
    expect(page.get_by_text("已建立待投递记录。")).to_be_visible()
    row = page.locator("[data-status='pending']").filter(has_text="自动化工单")
    app_id = row.get_attribute("data-application-id")
    expect(row.get_by_text("人工登记", exact=True)).to_be_visible()
    row.get_by_role("button", name="人工确认").click()
    dialog.get_by_label("确认结果").select_option("failed")
    expect(dialog.get_by_role("button", name="保存人工确认")).to_be_disabled()
    dialog.get_by_label("核对依据").fill("本地样例人工核对：确认未完成投递")
    dialog.get_by_role("button", name="保存人工确认").click()
    expect(page.locator(f"[data-application-id='{app_id}'][data-status='failed']")).to_contain_text("确认未完成投递")
    print(f"Applications: all five fixture labels shown; manual record #{app_id} moved pending -> failed with evidence")

    page.get_by_role("menuitem", name="任务中心").click()
    expect(page.get_by_test_id("auto-disabled")).to_have_text("真实 Auto 未启用")
    expect(page.locator("option[value='boss']")).to_have_js_property("disabled", True)
    count_before_review = read(page, "applications?source=fixture")["total"]
    completed = review(page, "慢读取")
    expect(page.locator("[data-task-status='running'], [data-task-status='queued']")).to_be_visible()
    before_reload = len(polls)
    page.reload()
    expect(page.get_by_role("heading", name=f"任务详情 #{completed}")).to_be_visible()
    expect(page.locator("[data-task-status='running'], [data-task-status='queued']")).to_be_visible()
    expect(page.get_by_role("button", name="创建 Review")).to_be_disabled()
    data = expect_status(page, completed, "succeeded")
    assert data["progress"]["jobs_saved"] == 1 and data["progress"]["browser_submit_calls"] == 0
    assert any(url.endswith(f"/api/tasks/{completed}") for url in polls[before_reload:]), "active task was not polled after reload"
    number = len(polls)
    interval = read(page, "settings")["poll_interval_ms"]
    page.wait_for_timeout(interval + 350)
    assert len(polls) == number, "terminal task still polled"
    page.screenshot(path=CAPTURES / "tasks.png", full_page=True, animations="disabled")

    page.get_by_role("link", name="查看此来源的职位").click()
    page.get_by_label("搜索职位、公司或城市").fill("运维实习生")
    page.get_by_role("button", name="筛选", exact=True).click()
    job = next(job for job in read(page, "jobs?source=fixture&q=运维实习生")["items"] if job["last_task_id"] == completed)
    row = page.locator(f"[data-job-id='{job['id']}']")
    row.get_by_role("button", name="查看详情").click()
    expect(page.get_by_text("职位描述（纯文本）")).to_be_visible()
    expect(page.get_by_text(job["scoring_version"], exact=True)).to_be_visible()
    expect(page.locator(".job-description")).to_have_text(read(page, f"jobs/{job['id']}")["jd_text"])
    page.get_by_role("dialog", name="职位详情").screenshot(path=CAPTURES / "jobs-detail.png", animations="disabled")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="职位详情")).to_be_hidden()
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=CAPTURES / "jobs.png", animations="disabled")

    page.get_by_role("menuitem", name="任务中心").click()
    stopped = review(page, "慢读取")
    for _ in range(30):
        if read(page, f"tasks/{stopped}")["status"] == "running":
            break
        page.wait_for_timeout(40)
    else:
        raise AssertionError("did not observe running before Stop")
    page.get_by_role("button", name="停止任务").click()
    data = expect_status(page, stopped, "stopped")
    assert data["stop_reason"] == "USER_STOPPED" and data["progress"]["browser_submit_calls"] == 0

    left = review(page, "慢读取")
    expect(page.locator("[data-task-status='running'], [data-task-status='queued']")).to_be_visible()
    page.get_by_role("menuitem", name="总览").click()
    expect(page.get_by_role("heading", name="总览")).to_be_visible()
    number = len(polls)
    page.wait_for_timeout(interval + 350)
    assert len(polls) == number, "navigating away did not stop polling"
    page.get_by_role("menuitem", name="任务中心").click()
    expect_status(page, left, "succeeded")
    print(f"Tasks: #{completed} restored while active after reload; #{stopped} stopped by user; #{left} left while active; no polling after terminal or departure")

    risky = review(page, "风险详情")
    assert expect_status(page, risky, "stopped")["stop_reason"] == "SECURITY_CHECK"
    page.get_by_role("menuitem", name="系统设置").click()
    expect(page.get_by_role("heading", name="系统设置")).to_be_visible()
    settings = read(page, "settings")
    expect(page.get_by_text(settings["scoring"]["version"], exact=True)).to_be_visible()
    page.get_by_text("展开评分权重和扣分").click()
    expect(page.get_by_text("技能匹配", exact=False)).to_be_visible()
    guard = page.locator("[data-guard='fixture']")
    expect(guard.locator("[data-guard-state='blocked']")).to_have_text("已锁定")
    expect(page.locator("[data-guard='boss']")).to_contain_text("未检测")
    page.screenshot(path=CAPTURES / "settings.png", full_page=True, animations="disabled")
    before_ack = read(page, "tasks")["total"]
    guard.get_by_role("button", name="解除安全闸").click()
    expect(dialog.get_by_role("button", name="确认解除")).to_be_disabled()
    dialog.get_by_role("checkbox").check()
    dialog.get_by_role("button", name="确认解除").click()
    expect(guard.locator("[data-guard-state='clear']")).to_have_text("未锁定")
    assert read(page, "tasks")["total"] == before_ack
    assert read(page, f"tasks/{risky}")["status"] == "stopped"
    page.get_by_role("menuitem", name="任务中心").click()
    next_task = review(page, "慢读取")
    expect_status(page, next_task, "succeeded")
    assert read(page, "applications?source=fixture")["total"] == count_before_review
    assert not errors, errors
    print(f"Settings: #{risky} locked the fixture guard, acknowledgement did not restart it, next Review #{next_task} succeeded; no Review application rows added")


def main():
    CAPTURES.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium", headless=True)
        try:
            run(browser.new_page(viewport={"width": 1440, "height": 1000}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
