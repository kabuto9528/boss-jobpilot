# 阶段 6 · Playwright Persistent Context 与首批停止保护

**2026-11-08（北京时间）｜本地验收通过。** 已核对《BOSS职位筛选与自动化投递平台——分阶段开发文档》和 `docs/acceptance/stage-05.md`。阶段 5 明确标记为通过。检查盘符根目录、工作区和项目后，未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。开工时工作区含阶段 5 改动，本阶段的文件修改与这些改动分开。

## 实施范围

- 沿用项目的 Python 3.12.6 虚拟环境、`config/app.yaml` 中的 `runtime/profiles` 和 `15000 ms` 超时。Chromium 用绝对路径启动 Persistent Context，专用 Profile 和项目锁都位于 Git 忽略的 `runtime/` 下。
- 用 Windows 文件锁统一限制项目内的浏览器任务。锁与句柄一起释放。启动前检查正在使用项目 Profile 的 Chromium 进程，发现占用时返回 `BROWSER_BUSY`。
- 本地样例服务仅绑定 `127.0.0.1`。同一次冒烟验收保持服务运行，两次启动使用完全相同的来源和 Profile。样例页面在导航和读取、写入前后检查可见风险提示和预期页面标识。触发 Safe Stop 后锁定当前会话的原因，退出时关闭 Context 并释放占用。

## 实际命令和结果

在 PowerShell 7 从项目根目录执行依赖安装。安装临时目录使用项目内已忽略的路径。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
$stageTemp = New-Item -ItemType Directory -Force -Path '.\runtime\stage-06-tmp'
$env:TEMP = $stageTemp.FullName
$env:TMP = $stageTemp.FullName
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m playwright --version
```

依赖与 Chromium 安装成功。Playwright 版本为 `1.64.1`，Chromium 构建为 `1248`（Chrome for Testing `156.0.8078.4`）。首次用默认浏览器缓存执行冒烟和专项测试时，完整 Chromium 在启动前报 `spawn UNKNOWN`。直接启动同一浏览器文件复现 Windows `14001`，应用程序日志的 SideBySide 事件 `33` 记录了版本程序集加载失败。首次专项测试为 `1 passed, 11 failed`，通过项为目录边界检查。

将同一构建的浏览器文件复制到纯 ASCII 缓存路径后，有界面启动成功。随后用以下命令复验。`PLAYWRIGHT_BROWSERS_PATH` 只在运行验收命令的 PowerShell 进程中设置，Profile 继续使用项目配置的目录。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m playwright install chromium --no-shell
.\.venv\Scripts\python.exe -m scripts.smoke_profile --provider fixture
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_profile.py .\backend\tests\test_safe_stop.py -q -rA --tb=short
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q -rA --tb=short
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
git check-ignore -v -- runtime/profiles/fixture-stage-06 runtime/locks/browser.lock
git diff --check
```

- 有界面冒烟通过。该次样例来源为 `http://127.0.0.1:50357`，Profile 为 `D:\boss投递\boss-jobs-platform\runtime\profiles\fixture-stage-06`。关掉 Chromium 再重开，读回本次写入的标记。
- 阶段 6 专项测试 `12 passed in 25.51s`。最终后端全量回归 `23 passed in 28.61s`，包含全部 12 项浏览器测试。原有 MySQL 测试继续使用 `boss_jobs_test`。
- Python 语法检查和 `pip check` 通过。`git check-ignore` 确认 Profile 与锁文件受 `runtime/` 规则覆盖，`git diff --check` 退出码为 0，仅提示现有换行转换规则。
- 全量测试后重新取得项目锁并复查进程，结果为 `PASS: project lock is available and no Chromium process holds a project profile.`

## 验收用例

| 用例 | 实测结果 |
| --- | --- |
| 同一来源和同一 Profile 关闭重开 | 持久标记可读。换用同一项目中的另一专用 Profile，标记为空。 |
| 同进程和独立进程并发请求 | 请求同一 Profile 或另一 Profile 均返回 `BROWSER_BUSY`。第一个 Context 关闭后可再次启动。 |
| 项目锁空闲时有残留 Chromium | 同一 Profile 与另一项目 Profile 的新任务均在启动前被拒绝。残留 Context 关闭后可重新使用。 |
| 本地样例读取异常 | 注入缺失读取目标，以 500 ms 触发实际读取超时，收到 Context 关闭事件。用同一 Profile 重开可正常读取。 |
| Profile 路径边界 | 配置目录本身和目录外路径均被拒绝。测试使用项目目录内的独立临时 Profile。 |
| 五类风险页 | 验证码、安全验证、操作频繁、账号异常和会话失效分别触发 `CAPTCHA_REQUIRED`、`SECURITY_CHECK`、`RATE_LIMITED`、`ACCOUNT_ABNORMAL`、`LOGIN_REQUIRED`。每种情况都尝试追加读取、导航和写入，实际派发动作均为 **0**。Context 关闭后均可复用原 Profile。 |
| 未知页及导航前出现风险 | 未知页触发 `PAGE_UNRECOGNIZED`，后续动作数为 **0**。当前页出现验证码提示时，下一次导航也在派发前被拦截。普通样例同时包含职位正文中的“验证码”和隐藏提示，仍可正常读取。 |

## 完成清单

- [x] 浏览器启动、关闭、复用及并发拒绝均通过。
- [x] 样例风险触发后停止操作并释放资源。
- [x] 所有用例使用专用本地 Profile。

## 剩余问题

- 本机默认浏览器缓存路径上的完整 Chromium 仍存在 Windows 启动兼容性问题。复跑请先设置上文的 `PLAYWRIGHT_BROWSERS_PATH`。
- Safe Stop 在本阶段覆盖当前样例会话。跨任务持久化安全闸按开发文档归阶段 10 验收。

**工作止于阶段 6。**
