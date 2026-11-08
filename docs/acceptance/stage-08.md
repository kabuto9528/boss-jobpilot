# 阶段 8 · 列表读取、详情遍历与 Parser

**2026-11-08（北京时间）｜本地验收通过。** 开工时 `main` 位于 `f2d55aa`，工作区干净。检查盘符根目录、上级工作区、项目根目录及项目子目录，未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。实施前确认阶段 7 本地验收通过，复跑单职位读取与 Safe Stop，结果为 `19 passed in 34.34s`。 [阶段 7 验收记录](stage-07.md)

## 实际命令

从项目根目录运行，沿用阶段 6 和阶段 7 验证的本机 Chromium 路径。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_read_one.py .\backend\tests\test_safe_stop.py -q --tb=short
.\.venv\Scripts\python.exe -m scripts.smoke_search --provider fixture --keyword '运维实习生' --max-pages 2 --max-jobs 5
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_parser.py .\backend\tests\test_search_read.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q --tb=short
.\.venv\Scripts\python.exe -m scripts.smoke_search --provider fixture --keyword '风险详情' --max-pages 2 --max-jobs 5
Write-Output "risk search exit=$LASTEXITCODE"
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
git check-ignore -v -- runtime/profiles/fixture-stage-08 runtime/locks/browser.lock
git diff --check
@'
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import browser_lock, ensure_profiles_idle
with browser_lock():
    ensure_profiles_idle(load_browser_settings().profile_root)
print("PASS: project lock is available and no Chromium process holds a project profile.")
'@ | .\.venv\Scripts\python.exe -
```

在单独的 PowerShell 进程临时设置开关，核对真实入口拒绝请求与本地参数校验。

```powershell
$env:BOSS_REVIEW_ENABLED = 'true'
.\.venv\Scripts\python.exe -m scripts.smoke_search --provider boss --keyword '运维实习生' --max-pages 1 --max-jobs 3
Write-Output "boss search exit=$LASTEXITCODE"
.\.venv\Scripts\python.exe -m scripts.smoke_search --provider fixture --keyword '运维实习生' --max-pages 0 --max-jobs 3
Write-Output "invalid limit exit=$LASTEXITCODE"
```

## 实测结果

- 正常冒烟退出码为 `0`，输出 JSON。`pages_attempted=2`、`details_attempted=5`、`duplicates=1`、`skipped={"missing_identity":1}`、`stop_reason=exhausted`，共 4 个规范化职位对象。身份键依次为 `fixture:fixture-job-001`、`fixture:fixture-job-002`、`fixture:fixture-job-003`、`url:a52dc5282cef0396aec50229db2186b2904e43fe335a4ce83da4cd048c97d6e5`。
- 阶段 8 专项为 `21 passed in 28.42s`，后端全量回归为 `56 passed in 101.20s`，含阶段 7 读取和隔离 MySQL 测试。语法检查、依赖检查与 `git diff --check` 通过。专用 Profile 和浏览器锁由 `runtime/` 忽略规则覆盖，实测可重新取得项目锁，且没有 Chromium 进程占用项目 Profile。
- 真实入口在启动浏览器前返回 `PROVIDER_DISABLED`，退出码为 `2`。零页上限的本地调用同样在启动浏览器前被参数校验拒绝，退出码为 `2`。

| 用例 | 实测结果 |
| --- | --- |
| 跨页重复、同名不同身份 | 两页间重复的 `fixture-job-001` 仅访问一次详情。`fixture-job-001` 与 `fixture-job-002` 的标题和公司相同，均输出。不同详情链接经核对指向同一编号时只输出一条。 |
| 缺 JD、缺身份与文本规范化 | `fixture-job-003` 保留，`jd_text=null` 且 `jd_state=missing`。有 JD 片段但无完整标记时，Parser 输出 `partial`。缺身份且链接无法验证时记 `missing_identity` 并跳过。`/detail?job=link-only` 可生成链接身份键，测试确认变更本地端口不改变键，变更 `job` 参数会改变键。完整 JD 保留段落，薪资和经验保留可见文本。 |
| 空结果、未知结构与身份冲突 | 明确空态返回 `empty_results`，尝试 1 页、0 条详情。无空态标记的空列表、异常链接或未知页返回 `PAGE_UNRECOGNIZED`。卡片与详情编号冲突也返回该原因，保留此前已解析的结果。 |
| 风险中止 | 详情风险冒烟输出 `SECURITY_CHECK`，尝试 1 页、2 条详情，保留 1 个先前结果，退出码为 `1`。专项测试覆盖第二页列表风险和详情风险，请求轨迹在风险页终止。 |
| 页面不前进 | 相同卡片批次换序，或不同链接核对后得到相同身份批次，均在第 2 页返回 `page_not_advancing`，未访问第 3 页。 |
| 页数上限 | 持续提供下一页的样例在 2 页、2 条详情后返回 `max_pages`，未发起第 3 页请求。 |
| 职位数上限 | 上限为 1 时只尝试 1 条详情，未翻页。上限为 4 时在第 2 页尝试到缺身份职位即用完额度，返回 `max_jobs`，未访问第 5 条详情。职位额度按详情尝试计数，覆盖缺字段与风险详情。 |
| 只读范围 | 正常双页场景的浏览器请求轨迹为 2 个列表 `GET` 与 5 个详情 `GET`，提交调用为 0。样例测试逐项核对预期路径与方法。 |

## 清单与真实联调

- [x] 合成用例覆盖重复、空结果、缺字段、身份冲突及不前进。
- [x] 页数和职位数上限生效，风险状态可在中途终止。
- [x] 真实页面未经核验时保持真实列表能力关闭。**真实状态为未启用、未验收。** [页面观察记录](../page-observations.md)

## 剩余问题

- 本机复跑沿用已验证的 `PLAYWRIGHT_BROWSERS_PATH`。样例 `source_url` 记录本次临时服务地址，链接身份键使用稳定的详情路径和身份查询参数。
- 真实联调仍需要覆盖自动化读取的平台许可、已通过的阶段 7 真实验收，以及对真实搜索入口、列表、翻页和详情 Selector 的现场核验。

**工作止于阶段 8，产物为规范化职位对象和读取统计。**
