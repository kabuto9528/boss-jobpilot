# 阶段 10 · 后台 Task 与 Review 完整闭环

**2026-11-08（北京时间）｜本地 fixture Review 闭环验收通过；真实 BOSS Review 未验收。**

## 前置检查与隔离

- 已读取 `D:\boss投递\BOSS职位筛选与自动化投递平台——分阶段开发文档.md` 的阶段 10 清单，并读取阶段 9 验收记录。阶段 9 标记为本地合成数据验收通过。
- 工作区起始于 `main`，存在阶段 9 的未提交评分代码、配置、样例和验收记录；这些文件已保留。检查 `D:\AGENTS.md`、工作区和项目目录，未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。
- 验收 API、自动化测试均使用 `.env.test` 的 `boss_jobs_test`，确认 `tasks`、`jobs`、`applications`、`automation_guard` 表存在。未用 `.env` 正式库；验收前后 `applications` 行数均为 0。
- 阶段 8 记录说明真实 BOSS 读取仍未启用、未验收；当前也没有可核验的平台许可。因此未访问真实 BOSS 页面。API 对 `provider=boss` 返回 `403 PROVIDER_DISABLED`，对 `mode=auto` 返回 `409 AUTO_NOT_AVAILABLE`，且均不创建任务。

## 实现范围

- `POST /api/tasks` 写入任务后返回 `202`、`task_id` 和 `status_url`。`request_key` 相同且请求体相同会复用原任务；同键不同请求返回 `409 REQUEST_KEY_REUSED`。数据库活动槽唯一索引与 API 冲突检查共同限制单个活动任务。
- 应用 lifespan 先持有项目级 `task-runner.lock`，再启动唯一后台线程；第二个 API 进程无法取得执行锁。任务创建只负责短事务写入和唤醒执行器。`GET /api/tasks` 提供历史，`GET /api/tasks/{id}` 提供阶段和进度，`POST /api/tasks/{id}/stop` 支持排队停止和运行中协作停止。
- 重启时遗留的 `queued`、`running`、`stop_requested` 均标记为 `interrupted`，不自动重放，并释放活动槽。真实来源的运行中断会锁定 `boss` 安全闸；风险 Safe Stop 会锁定任务来源。浏览器读取在每页、每个详情之间检查停止请求。
- Review 复用阶段 8 的 fixture 搜索和 Parser、阶段 9 的 `score_job`。职位按身份键去重，逐条在短事务内 MySQL upsert；重复 Review 保留原 `first_seen_at`，更新 `last_seen_at`、评分、规则证据和 `last_task_id`。
- 读取遇到 `SafeStop` 会停止后续读取、保留此前已读职位并设置 `automation_guard`。写库异常会立刻退出浏览器读取。Review 的浏览器请求记录器统计非 GET 写请求；正常、停止、风险和失败样例中的 `browser_submit_calls` 均为 0。
- Jobs 表格保留评分与理由展示，Review 评分记录和 JD 可从职位详情抽屉查看；增加 `data-job-id` 便于稳定定位职位行。完整 Tasks 页面仍属阶段 11 范围。

## 实际运行命令

因为 `127.0.0.1:8000` 和 `:5173` 开始时已有监听，本次隔离验收使用 API `:8010`、Vite `:5174`；只停止了本次启动的两个服务。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -c "from backend.app.config import load_database_settings; from backend.app.main import create_app; import uvicorn; uvicorn.run(create_app(load_database_settings(testing=True)), host='127.0.0.1', port=8010, workers=1)"
```

另一个 PowerShell 窗口启动前端：

```powershell
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8010'
npm.cmd --prefix .\frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

慢样例使用 `mode=review`、`provider=fixture`、`params.keywords=['慢读取']`、`max_pages=1`、`max_jobs=5`。本地 fixture 将该搜索页延迟 2 秒，用于观察提交与后台执行分离。完整后端验收命令：

```powershell
$base = 'http://127.0.0.1:8010'
$body = @{ mode='review'; provider='fixture'; request_key=[guid]::NewGuid().ToString(); params=@{ keywords=@('慢读取'); city=''; max_pages=1; max_jobs=5 } } | ConvertTo-Json -Depth 5 -Compress
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$response = Invoke-WebRequest -UseBasicParsing -Uri "$base/api/tasks" -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$timer.Stop()
$accepted = $response.Content | ConvertFrom-Json
"HTTP $($response.StatusCode), elapsed_ms=$($timer.ElapsedMilliseconds), task_id=$($accepted.task_id)"
Invoke-RestMethod "$base$($accepted.status_url)"
```

同一个 `$body` 原样重发验证幂等；使用新 `request_key` 的另一请求验证活动槽返回 `409`。状态轮询直到 `succeeded`、`failed`、`stopped` 或 `interrupted`。

全量测试应在停止上述 API 和 Vite 服务、释放项目执行锁后运行。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
npm.cmd --prefix .\frontend run build
git diff --check
```

## 实测结果

- 慢样例最终有效 HTTP 实测：`POST /api/tasks` 返回 **202，168 ms**，任务 `task_id=122`。相同请求键重发返回相同 ID；另一请求键在占槽期间返回 **409**。轮询观察到 `running → succeeded`，最终进度为 1 页、1 条详情、1 个职位入库、`browser_submit_calls=0`。任务运行期间 `/api/health` 返回 `ok`，`/api/ready` 返回 `ready`。
- 首次单独启动验收服务时漏设已验证的 `PLAYWRIGHT_BROWSERS_PATH`：请求仍于 178 ms 返回 202，但后台任务 `task_id=33` 以浏览器启动错误失败。为 Uvicorn 补设阶段 8 的浏览器路径后，重跑得到以上成功结果；未修改评分或读取代码来掩盖该环境错误。失败记录仅留在 `boss_jobs_test`。
- 使用独立 headless Chromium 打开 `http://127.0.0.1:5174/jobs`，按职位过滤并精确核对本次任务写入：职位行 `id=95`、`last_task_id=122`、身份键 `fixture:fixture-job-001`、标题“运维实习生”、评分 66。行内展示评分理由；打开详情后显示 `stage-09.1` 和完整 JD，临时 Profile 已清理，`applications` 行数为 0。页面截图保存在 `runtime/stage10-jobs-review.png`。
- `test_task_lifecycle.py` 覆盖慢样例快速响应、同键幂等、单槽冲突、用户停止、单进程执行锁、重启时 queued 与遗留运行任务中断（不重放）、写库故障后停止继续读取和 Profile 清理、BOSS 与 Auto 禁用。真实来源安全闸通过向隔离测试库插入合成的遗留任务行验证；没有真实页面、账号或浏览器操作。
- `test_review_e2e.py` 覆盖读取→解析→评分→职位写入→Jobs API；重复执行后 4 个身份行的 ID 不变、`first_seen_at` 不变、`last_seen_at` 更新。风险详情样例保留 1 个先前职位后以 `SECURITY_CHECK` 停止并暂停 fixture 来源。上述闭环用例均断言 `browser_submit_calls=0`、`applications` 行数前后不变。
- 全量后端：**96 passed in 112.72s**。`compileall` 通过，`pip check` 输出 `No broken requirements found.`，Vite build 通过（449 ms），`git diff --check` 退出码 0。Git 仅报告现有 LF 文件后续可能转为 CRLF 的提示，没有空白错误。

## 阶段清单

- [x] 慢样例提交快速返回，状态轮询可用，任务运行时健康与就绪接口可访问。
- [x] 单活动槽、同键幂等、用户停止、单进程执行锁、旧活动任务重启中断且不重放、风险停止和写库故障停止读取。
- [x] Review 从读取到评分、身份去重、短事务写入，并在 Jobs 页面与详情中可见。
- [x] 重复 Review 不增加身份行；真实投递调用计数为 0，`applications` 表无变化。
- [ ] 真实 BOSS Review：**前置条件未满足，未执行**。需先有阶段 7/8 真实验收记录、已核验真实页面选择器与明确的平台许可。

## 剩余问题

- 真实 BOSS Review 仍关闭。获得许可并完成阶段 7/8 真实前置验收后，另行做获准范围的小批次验证；本次阶段 10 不使用真实账号、页面或浏览器会话。
- 风险停止后的安全闸没有本阶段的设置页面解锁入口；需人工检查后再由后续设置能力解除。完整 Tasks 管理页面也按阶段计划留在阶段 11。
- 工作区仍包含阶段 9 的未提交变更；阶段 10 文件同样尚未提交。验收没有清理这些工作区内容。

**阶段 10 本地 fixture 验收完成；工作止于阶段 10。**
