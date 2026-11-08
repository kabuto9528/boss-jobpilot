# 阶段 11 · Dashboard、Applications、Tasks 与 Settings

**2026-11-09（北京时间）｜本地 fixture 管理后台验收通过。**

## 前置与隔离

- 开工前读取了项目外的分阶段开发文档、仓库内的 `docs/acceptance/stage-10.md`、五页管理台、Review 接口和工作区状态；检查了项目与上级目录，未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。
- 阶段 10 已通过本地 fixture 的任务与 Review 闭环验收，满足阶段 11 的本地前置条件。真实 BOSS Review 的许可及阶段 7/8 真实页面前置仍未验收，保持禁用。本次未连接真实 BOSS 网站、账号或会话。
- 开始检查时，阶段 9/10 内容尚未提交。实施期间仓库出现了已有的阶段 9/10 基线提交 `1324f0f`；保留这些内容并在其上完成阶段 11。本阶段没有提交或推送，也没有新增数据库迁移。
- 已有服务占用 `:8000` 与 `:5173`，因此验收使用 API `127.0.0.1:8010`、Vite `127.0.0.1:5174`、`.env.test` 的 `boss_jobs_test` 和 fixture 浏览器。验收数据未写入运行库。继续复用既有任务契约、Jobs 页面和单进程执行器。

## 实际运行命令

在仓库根目录运行。测试及页面验收共用项目级执行锁，需分开运行。以下浏览器目录是本机已有的阶段 6 Chromium 安装目录。

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_management_api.py -q
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
npm.cmd --prefix .\frontend run build
git diff --check
```

启动隔离 API：

```powershell
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -c "from backend.app.config import load_database_settings; from backend.app.main import create_app; import uvicorn; app=create_app(load_database_settings(testing=True), control_origins=frozenset(['http://127.0.0.1:5174'])); uvicorn.run(app, host='127.0.0.1', port=8010, workers=1)"
```

另一个 PowerShell 启动 Vite：

```powershell
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8010'
npm.cmd --prefix .\frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

在另一窗口导入样例并验收。命令中的 `--test-db` 只写隔离库；浏览器脚本会创建测试任务和人工投递记录。

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset workflow --test-db
$base = 'http://127.0.0.1:5174/api'
Invoke-RestMethod "$base/dashboard?source=fixture"
Invoke-RestMethod "$base/applications?source=fixture"
Invoke-RestMethod "$base/settings"
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
.\.venv\Scripts\python.exe -u -m scripts.smoke_management_ui
```

## 页面联调

脚本用 Chromium 真实点击五页、通过 Vite 转发访问 API，并监听浏览器的任务轮询。截图保存在 `runtime/stage-11/`：[总览](../../runtime/stage-11/dashboard.png)、[职位](../../runtime/stage-11/jobs.png)、[职位详情](../../runtime/stage-11/jobs-detail.png)、[投递记录](../../runtime/stage-11/applications.png)、[任务](../../runtime/stage-11/tasks.png)、[设置](../../runtime/stage-11/settings.png)。

| 页面 | 检查和结果 |
|---|---|
| Dashboard | 切换 fixture / BOSS；将页面中的职位总数、推荐数与 Jobs 查询核对，并逐个状态与 Applications 查询核对。首次导入后 fixture 为 16 个职位、9 个推荐、五种投递状态各 1 条；BOSS 职位、推荐和投递均为 0。推荐卡片跳转到同来源的推荐职位筛选。接口测试另外插入两来源对照，验证当前和最近任务也按来源隔离，同一职位的多条投递历史按尝试记录分别计数。 |
| Jobs | 从 Tasks 打开同来源的职位，按关键词筛选，确认本次 Review 写入职位的 `last_task_id`、评分规则版本和纯文本 JD；从职位详情打开 Applications 并预选当前职位。 |
| Applications | 五种状态均可分别筛选和展示，待核对使用醒目标记；从预选职位建立人工待投递，填写核对依据后保存为失败。无依据时无法保存。接口测试覆盖待核对确认已投递、禁止从投递中或终态再次确认，以及并发提交只新增一条、并发确认只成功一次、失败后重新建立待投递且保留历史。 |
| Tasks | 从页面创建慢 Review，提交返回 HTTP 202；进行中刷新仍恢复原任务、进度和停止入口。成功任务写入 1 条职位，用户停止任务进入 `stopped/USER_STOPPED`。在终态、以及运行中离开任务页后，均观察超过配置的 2 秒轮询间隔，未收到新的任务详情轮询。离开后回到任务页可从历史读到终态。 |
| Settings | 核对默认关键词、页数和职位上限、2 秒轮询、15 秒浏览器超时、规则版本 `stage-09.1`、推荐阈值 55、评分权重、来源能力和安全闸。风险样例以 `SECURITY_CHECK` 停止并锁定 fixture；勾选人工确认前不能解除。解除后旧任务仍停止，任务总数没有增加；下一次新 Review 可以完成。BOSS 显示未检测、无检查时间。 |

- 首次导入新增 6 个 workflow 样例职位和 5 条投递记录；再次导入新增投递为 0，人工记录保留。Review 期间样例来源投递总数不变，检查到的成功和用户停止任务均报告 `browser_submit_calls=0`。
- 在已导入样例的测试库重跑时，发现 workflow 初版职位名称会命中阶段 4 的两个既有精确结果用例。为 workflow 样例采用独立职位名后重新导入，保留原记录与状态，再运行全量测试。
- 浏览器只提供 Review 表单，BOSS 来源不可选，Auto 标记为禁用。后端对 fixture 和 BOSS 的 Auto 请求均返回 `409 AUTO_NOT_AVAILABLE` 且任务数不变，真实 Review 返回 `403 PROVIDER_DISABLED`。写接口校验本机允许的浏览器 Origin 和 JSON；不允许的来源返回 403。
- Settings 使用字段白名单，未返回数据库连接字段、凭据、Profile 路径、会话信息或原始规则文档。测试注入额外的模拟敏感字段，确认响应不会带出它们。安全闸接口拒绝在有活动任务时解除，也拒绝确认页面上过期的风险记录。
- 验收中检查到 MySQL 的 `CURRENT_TIMESTAMP` 按本机会话时区写入，已有 Worker 显式写入的时间使用 UTC。任务和投递 API 现将两类字段统一序列化成带 UTC 时区的时间，浏览器再按本地时区显示；未改写现存时间列。

## 最终结果

- `test_management_api.py`：**5 passed in 2.94s**。完成样例名称隔离后，后端全量 **101 passed in 88.69s**。前端构建成功（488 ms），`compileall`、`pip check` 和 `git diff --check` 通过；Git 仅提示部分文件未来可能转为 CRLF。
- 三条阶段清单中的读取接口经 Vite 代理均返回 HTTP 200。最终页面验收开始时 fixture 为 16 个职位、9 个推荐、7 条投递记录（1 待投递、1 投递中、1 已投递、3 失败、1 待核对）；额外失败行来自此前隔离验收中的人工登记。BOSS 的职位和投递计数均为 0。
- 最终浏览器脚本退出码 0。人工记录 `#120` 由待投递转为失败并保留依据；Review `#177` 刷新后继续轮询到完成、`#178` 人工停止、`#179` 在进入终态前离开任务页，返回后显示完成。风险任务 `#180` 锁定安全闸，解除后仍为已停止；新任务 `#181` 成功。整个 Review 组没有新增投递记录。
- 验收完成后停止了本次启动的 `:8010` 和 `:5174` 服务，复核两端口不再监听，已有 `:8000`、`:5173` 进程仍在。

## 阶段清单

- [x] 五页齐全，样例来源、统计与状态一致。
- [x] Review 可从页面创建、查看和停止；刷新恢复，终态和离开页面停止轮询。
- [x] 人工待投递和确认通过；Auto 在前后端均禁用。
- [x] 管理接口测试、后端回归和前端构建通过；Settings 响应未暴露凭据与浏览器会话信息。

## 剩余事项

- 真实 BOSS Review 仍未验收。真实和样例 Auto 执行、Auto 预演、设置在线写入、WebSocket 和账号管理均未在本阶段实现。
- 登录状态当前只显示 fixture 无需登录、BOSS 未检测；无真实检查时间。测试库内可能保留前置阶段的合成 BOSS 任务历史，这些记录不代表访问过真实站点。
- 任务页显示最近 20 条历史，可通过任务 ID 链接查看单条历史；总览只展示同来源最近 5 条。

**工作止于阶段 11。**
