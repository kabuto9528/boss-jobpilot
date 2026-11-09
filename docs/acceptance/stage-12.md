# 阶段 12 · Auto、Safe Stop 联合验证与最终验收

**2026-11-09（北京时间）｜阶段 12 本地 fixture 验收通过，第一版基线完成。**

## 前置与隔离

- 读取项目外的分阶段开发文档和 [阶段 11 验收记录](stage-11.md)，检查了现有 Review、任务状态机、投递记录与安全闸。用户确认阶段 11 已验收，本阶段采纳该结论。
- 起点为 `main` 的 `56ca30b`，`git status --short --branch` 显示工作区干净。检查盘符根、父工作区、项目及涉及目录，未找到适用的 `AGENTS.md` 或 `AGENTS.override.md`。
- 验收 API 使用 `127.0.0.1:8010`，Vite 使用 `127.0.0.1:5174`，与开工时已占用的 `:8000`、`:5173` 分开。数据使用 `.env.test` 的 `boss_jobs_test` 和 `boss_app_test`，运行库未写入。验收完毕已停止本阶段启动的两项服务，复核验收端口不再监听，Auto 临时 Profile 残留为 0。
- 默认应用提供 fixture Review 和 fixture Auto 预演。模拟提交由测试显式创建 `create_app(..., fixture_submit_cases=...)`，工厂校验本机隔离库及专用账号，请求还需 `dry_run=false` 和 `confirm_simulation=true`。Playwright 模拟提交使用拦截后直接生成的本地页面和可见回执，页面请求均由拦截器处理。沿用阶段 10/11 的任务槽、投递阻塞唯一键、安全闸和人工核对接口，复用现有表结构。

## 实际验收命令

以下命令从仓库根目录运行。后端测试与 UI 验收服务共用项目执行锁，分开运行。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_auto.py .\backend\tests\test_safe_stop.py .\backend\tests\test_review_e2e.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_jobs_mysql.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

运行中的 Vite 占用了工作区的 Rolldown 原生模块。先在隔离目录安装并构建，再将缺失依赖补回工作区，重跑工作区构建。

```powershell
$front = Join-Path $PWD 'runtime\stage-12\frontend'
New-Item -ItemType Directory -Force -Path $front | Out-Null
Copy-Item -LiteralPath 'frontend\package.json','frontend\package-lock.json','frontend\index.html','frontend\vite.config.js' -Destination $front -Force
Copy-Item -LiteralPath 'frontend\src' -Destination $front -Recurse -Force
npm.cmd --prefix $front ci
npm.cmd --prefix $front run build
robocopy.exe (Join-Path $front 'node_modules') (Join-Path $PWD 'frontend\node_modules') /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP /R:0 /W:0
npm.cmd --prefix .\frontend run build
```

隔离 API 和 Vite 各自使用独立终端。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -c "from backend.app.config import load_database_settings; from backend.app.main import create_app; import uvicorn; app=create_app(load_database_settings(testing=True), control_origins=frozenset(['http://127.0.0.1:5174'])); uvicorn.run(app, host='127.0.0.1', port=8010, workers=1)"
```

```powershell
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8010'
Push-Location .\runtime\stage-12\frontend
node.exe node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174 --strictPort
Pop-Location
```

样例导入、PowerShell 预演与页面交叉核对。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset workflow --test-db
$base = 'http://127.0.0.1:8010'
$before = (Invoke-RestMethod "$base/api/applications?source=fixture").total
$jobs = Invoke-RestMethod "$base/api/jobs?source=fixture&page_size=100"
$ids = @($jobs.items.Where({ $_.identity_key -like 'fixture:workflow-*' }).id)
if ($ids.Count -lt 13) { throw 'Missing preview samples' }
$payload = @{
    mode = 'auto'; provider = 'fixture'; request_key = [guid]::NewGuid().ToString()
    params = @{ job_ids = $ids; max_jobs = 3; dry_run = $true }
} | ConvertTo-Json -Depth 5
$preview = Invoke-RestMethod "$base/api/tasks" -Method Post -ContentType 'application/json' -Body $payload
$deadline = (Get-Date).AddSeconds(12)
do {
    $detail = Invoke-RestMethod "$base$($preview.status_url)"
    if ($detail.status -in 'succeeded','failed','stopped','interrupted') { break }
    if ((Get-Date) -gt $deadline) { throw 'Preview timeout' }
    Start-Sleep -Milliseconds 100
} while ($true)
$after = (Invoke-RestMethod "$base/api/applications?source=fixture").total
if ($detail.status -ne 'succeeded' -or $detail.progress.browser_submit_calls -ne 0 -or $before -ne $after) { throw 'Preview failed' }
.\.venv\Scripts\python.exe -u -m scripts.smoke_auto_preview_ui
```

## 通过项

| 验收场景 | 实测结果 |
| --- | --- |
| 预演范围与排序 | 从显式职位 ID 范围内去重，按 Priority 升序、Score 降序、ID 降序排序。用对照测试验证了不推荐、低于当前阈值、来源不同、职位不存在、JD 不完整、身份不匹配、已下线、评分过期，以及成功、投递中、待核对、失败未重新排队和候选超限的排除理由。已验明的本地详情 URL 可用作无站点 ID 时的身份。 |
| 预演零投递 | HTTP 预演任务 `#223` 从 13 个流程样例选出 `499, 498, 297`，`browser_submit_calls=0`，fixture 投递总数为 `8 → 8`。任务页提交的 `#224` 按上限 2 选出 `499, 498`，刷新后仍显示相同计划和跳过原因。脚本逐列比对 MySQL 投递表的 8 条记录，内容一致。 |
| 五页交叉核对 | Dashboard fixture 为 23 个职位、16 个推荐，五种投递状态计数与 Jobs、Applications 接口一致，BOSS 职位和投递为 0。Jobs 详情展示可用于预演的 ID。Applications 能筛到待核对对照。Settings 标明 fixture 预演已启用、真实 Auto 未启用。Tasks 展示计划、排除理由及模拟动作计数。 [任务页截图](../../runtime/stage-12/auto-preview.png) |
| 并发与临提交复核 | 并发准入只产生一个活动任务。重复选择同一职位只预留一条阻塞记录，手动待投递请求返回 409。计划生成后将职位取消推荐、补入成功记录或替换当前规则，执行器均在提交前拦截，动作数为 0。 |
| 成功、明确失败与人工重排 | 已有 `pending` 的记录沿用原 ID，浏览器模拟点击前为 `sending`。当前职位的可见回执记为 `FIXTURE_RECEIPT`。页面已显示对应回执时记为 `FIXTURE_ALREADY_SUBMITTED`，动作计数不增加。明确拒绝记为 `failed/FIXTURE_REJECTED`。用户在提交前停止时为 `failed/SUBMIT_CANCELLED`，点击数为 0。失败职位经人工重新建待投递后才重新具备资格，原失败历史仍可查。 |
| 结果待核对 | 仅出现开聊提示、回执缺失或回执属于其他职位时，当次尝试保留为 `uncertain`，后续职位无尝试，来源安全闸锁定。人工解除安全闸后该职位仍不能自动重试，既有记录可附证据人工确认。 |
| 数据库暂时不可写 | 注入结果写入与结算写入故障，执行器停止新动作，故障期间保留 `sending` 和任务槽。写入恢复后原记录转为 `uncertain`，任务为 `stopped/SUBMIT_UNCERTAIN`，错误码为 `DATABASE_WRITE_FAILED`。只重试本地结算写入。 |
| 进程中断与重启 | 在浏览器产生样例成功回执后、数据库结果写入前注入写入故障，关闭样例浏览器后让子进程直接退出。新 API 进程将原 `sending` 转为 `uncertain`，旧任务标记为 `interrupted/PROCESS_RESTART`，安全闸锁定，剩余候选没有投递记录。重启后记录仍可核对，人工解除也不会重放尝试。 |
| 五类风险与未知页 | 分别覆盖 `CAPTCHA_REQUIRED`、`SECURITY_CHECK`、`RATE_LIMITED`、`ACCOUNT_ABNORMAL`、`LOGIN_REQUIRED`，以及未知页、重复按钮、职位身份不符、错误回执和动作后出现安全验证。动作前风险零点击，动作后风险记待核对。各用例均保留先前成功记录，后续候选无尝试，任务终态释放浏览器锁并清理临时 Profile。重启后安全闸仍生效，人工解除不会续跑旧任务。 |
| Review 回归 | Chromium 样例的正常、重复与风险停止路径均为 `browser_submit_calls=0`。投递表行数不变，Review 仍可读取、评分、去重并保存职位。 |

## 失败项与复测

- 预演首轮发现 SQLAlchemy 的失败历史子查询自动关联过度，以及测试清理语句触发 MySQL 1093。显式限定子查询关联并改为按验收生成的职位 ID 清理后，预演复测为 **1 passed in 1.38s**，随后开始模拟提交验证。
- 首轮联合回归为 **24 通过、1 失败**。待核对人工确认测试使用了错误的请求字段，接口按契约返回 422。改用既有的 `evidence_summary` 并复跑。
- 新样例使测试库职位数超过默认每页 20 条。既有 Jobs 测试把默认第一页与所有页的合集比较，首轮全量回归为 **119 通过、1 失败**。断言调整为验证默认页元数据和前 20 条，保留跨页顺序、总数和唯一性校验。Jobs 专项复测为 **7 passed in 1.37s**。
- 工作区首次 `npm ci` 因运行中的 Vite 锁定 Rolldown 模块返回 `EPERM`。用同一锁文件在隔离目录重跑，安装 85 个包，构建通过（548 ms）。补齐工作区缺失依赖后，工作区构建也通过（5.01 s）。

## 最终结果与清单

- Auto、Safe Stop 和 Review 联合专项 **27 passed in 74.09s**。修正分页断言后，后端全量 **120 passed in 162.00s**。页面冒烟、Vite 工作区构建、`compileall`、`pip check` 和 `git diff --check` 均通过。
- [x] Auto 预演无投递副作用，模拟成功、明确失败、待核对与防重通过。
- [x] 五类风险、页面未知、数据库写入故障和进程中断通过，安全闸跨重启生效，人工解除后旧任务保持终态。
- [x] Review 零提交、投递表行数不变，五页与隔离数据库交叉核对通过。
- [x] 后端全量与前端构建通过，真实 Review 与真实 Auto 的许可及实测状态单列。

## 第一版交付基线

| 阶段 | 已验收基线 |
| --- | --- |
| 1–3 | Windows 工具链、MySQL 连接与健康检查、Vue 管理壳和 API 代理。 [阶段 1](stage-01.md) · [阶段 2](stage-02.md) · [阶段 3](stage-03.md) |
| 4–5 | MySQL 模型、Jobs 查询、筛选分页、详情和纯文本 JD。 [阶段 4](stage-04.md) · [阶段 5](stage-05.md) |
| 6–9 | 专用 Profile、样例登录及风险识别、有界详情读取、稳定身份去重、版本化评分与实习优先。 [阶段 6](stage-06.md) · [阶段 7](stage-07.md) · [阶段 8](stage-08.md) · [阶段 9](stage-09.md) |
| 10–11 | 持久任务队列、单执行器、Review 读取评分入库、五页管理、人工投递登记与确认。 [阶段 10](stage-10.md) · [阶段 11](stage-11.md) |
| 12 | fixture Auto 预演、隔离模拟、幂等与待核对防重、安全闸和中断恢复。验收入口为本节上方命令。 |

## 真实站点验收状态

| 能力 | 许可与现场前置 | 实测及启用状态 |
| --- | --- | --- |
| 真实 BOSS Review | 未获得可核验的自动化读取许可材料。阶段 7/8 的真实页面仍待验收。 | 未连接真实账号、页面或会话。未验收、未启用，API 返回 `403 PROVIDER_DISABLED`。 |
| 真实 BOSS Auto | 未获得可核验的投递许可材料。真实 Review、现场核验的提交动作和成功凭据、用户对本次单个职位的明确确认均未满足。 | 未验收、未启用。没有装配真实提交适配器，API 返回 `403 AUTO_DISABLED`，界面仅提供样例预演。 |

任务页截图中的 BOSS 来源中断任务 `#174` 来自前置阶段在隔离库写入的合成重启用例。

## 一键启动复验

2026-11-09（北京时间）。使用原启动器复现页面可打开、总览接口返回 HTTP 404。本机 Vite 的旧配置把 `/api` 转发至 `127.0.0.1:8001`，而启动器启动的 API 监听 `127.0.0.1:8000`。启动器现在为其 Vite 进程设置正确的代理目标，并通过前端端口成功读取总览后才打开浏览器。端口冲突或启动失败时，仅清理本次启动创建的进程记录。

- 保留旧的前端配置并继承指向 `8001` 的环境变量，执行 `start-local.cmd`。代理后的健康、就绪和五页接口均可用，前端总览与直接访问 `8000` 的响应一致。重复启动复用两个进程，`stop-local.cmd` 释放 `8000`、`5173` 并清理 PID 记录。再次启动后用 Chromium 逐页验证，运行库总览显示 6 条本地样例职位和 3 条推荐。 [启动验收截图](../../runtime/acceptance-recheck/launcher-dashboard.png)
- 后端全量复验 **120 passed in 171.50s**，前端 `npm.cmd --prefix .\frontend run build` 通过。隔离库重跑 `scripts.smoke_management_ui` 和 `scripts.smoke_auto_preview_ui`，通过五页交叉核对、人工确认、Review 正常与停止、安全闸及 Auto 预演。Review 未新增投递记录，Auto 预演提交次数为 0，隔离库 9 条投递记录逐列一致。
- 验收后关闭隔离 API 和 Vite，保留正式本机管理台供复查。真实 BOSS Review 和 Auto 的验收状态见上节。
