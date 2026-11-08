# 阶段 7 · 登录状态检测与单职位读取

**2026-11-08（北京时间）｜本地验收通过。** 开工前核对分阶段开发文档和阶段 6 验收记录。阶段 6 清单已通过，开工前复跑为 `12 passed in 23.01s`。项目起点为 `main` 的 `daa4dba`，工作区干净。在盘符根目录、工作区、项目根目录及涉及的子目录未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。 [阶段 6 验收记录](stage-06.md)

## 实现与验收口径

- 复用阶段 6 的 Persistent Context、项目浏览器锁、专用 Profile、超时和退出清理。命令行样例使用 `runtime/profiles/fixture-stage-07`，自动化用例使用独立临时 Profile。
- 读取前后检查可见状态。已登录须有明确的样例会话标记。登录失效返回 `LOGIN_REQUIRED`，已知风险返回对应原因，未知页和无法确认的详情返回 `PAGE_UNRECOGNIZED`。Safe Stop 保留首次停止原因并拦截本会话后续操作。
- 职位编号、标题、公司、城市和完整 JD 都需有唯一可见证据。缺字段、详情容器重复或 JD 加载中时停止，结果为空。样例读取只开放读取与受限导航，页面请求仅放行当前样例地址的 `GET`。

## 实际命令

在项目根目录运行。沿用阶段 6 已验证的本机 Chromium 路径。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Users\young\AppData\Local\boss-jobs-stage-06-playwright'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_profile.py .\backend\tests\test_safe_stop.py -q --tb=short
foreach ($case in @('logged-in','login-required','unknown','missing-jd','missing-identity')) {
    .\.venv\Scripts\python.exe -m scripts.smoke_job --provider fixture --case $case
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_read_one.py .\backend\tests\test_safe_stop.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
git check-ignore -v -- runtime/profiles/fixture-stage-07 runtime/locks/browser.lock
git diff --check
@'
from backend.app.config import load_browser_settings
from backend.app.runner.profile_lock import browser_lock, ensure_profiles_idle
with browser_lock():
    ensure_profiles_idle(load_browser_settings().profile_root)
print("PASS: project lock is available and no Chromium process holds a project profile.")
'@ | .\.venv\Scripts\python.exe -
```

在单独的 PowerShell 进程临时设置开关，验证两个真实模式入口在启动浏览器前拒绝请求。

```powershell
$env:BOSS_REVIEW_ENABLED = 'true'
.\.venv\Scripts\python.exe -m scripts.smoke_job --provider boss --login-only
Write-Output "boss login-only exit=$LASTEXITCODE"
.\.venv\Scripts\python.exe -m scripts.smoke_job --provider boss --url https://example.invalid/job
Write-Output "boss url exit=$LASTEXITCODE"
```

两个入口均返回 `PROVIDER_DISABLED`，退出码为 `2`。本次命令使用占位地址，未打开浏览器。

## 实测结果

- 阶段 7 专项与 Safe Stop 回归为 `19 passed in 33.90s`。后端全量回归为 `35 passed in 47.39s`，包括原有隔离 MySQL 测试。
- 全量测试后重新取得项目锁，确认没有 Chromium 进程占用项目 Profile。
- Python 语法检查和依赖检查通过，`git check-ignore` 确认专用 Profile 与项目锁受 `runtime/` 规则覆盖。`git diff --check` 退出码为 0，仅提示现有换行转换规则。

| 用例 | 实测结果 |
| --- | --- |
| 已登录 | 冒烟返回 `LOGGED_IN`，职位编号为 `fixture-job-001`，JD 共 77 字符。专项测试逐字对照职位编号、运维实习生、示例云科技、武汉和三段完整 JD，保留换行。JD 中的“验证码”和隐藏提示未触发风险。 |
| 登录失效 | `LOGIN_REQUIRED`，后续读取与导航派发均为 0。打开已登录详情后再模拟会话失效，下一次读取在派发前停止。 |
| 可见风险 | 样例安全验证页及已登录详情上弹出的风险提示均返回 `SECURITY_CHECK`。阶段 6 的各风险用例通过回归。 |
| 未知页 | `PAGE_UNRECOGNIZED`。未知页、已登录标记消失或多个可见登录容器并存时，后续读取派发为 0。 |
| 详情证据不足 | 缺 JD、缺职位编号、重复详情容器或 JD 仍在加载均返回 `PAGE_UNRECOGNIZED`，无职位结果。 |
| 提交调用与资源清理 | 五次有界面冒烟均各自只观察到一次预期的样例页面 `GET`，提交调用均为 0，专项测试独立断言请求轨迹。测试确认 Safe Stop 后 Context 关闭，同一测试 Profile 可重新使用。 |

## 清单与真实联调

- [x] 样例区分四类页面状态，未知页面保守停止。
- [x] 样例完整 JD 和缺字段行为符合契约，提交调用为零。
- [x] 真实联调状态单列。**未启用、未验收。** 缺少覆盖自动化读取的平台许可，真实可见页面观察、Selector 核验、用户独立扫码、重开复用和详情比对均待验收。参见 [页面观察记录](../page-observations.md)。

## 剩余问题

- 本机复跑继续使用阶段 6 已验证的 `PLAYWRIGHT_BROWSERS_PATH`。默认浏览器缓存路径的 Windows 兼容性问题沿用阶段 6 的记录。
- 真实能力须在取得许可后按页面观察、Selector 记录、独立手动扫码、重开与详情比对的顺序验收。

**工作止于阶段 7。**
