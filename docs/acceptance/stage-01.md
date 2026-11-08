# 阶段 1 · 项目初始化与环境基线

**验收通过** · 2026-11-08（北京时间）

项目根目录为 `D:\boss投递\boss-jobs-platform`。启动时工作区只有《分阶段开发文档》和《分阶段提示词》两份 Markdown，目标目录不存在。按开发文档第 4 节建立独立项目，并初始化本地 Git 仓库的 `main` 分支，用于验证忽略规则。

## 工作区与工具检查

```powershell
Set-Location -LiteralPath 'D:\boss投递'
Get-ChildItem -Force
Get-Content -LiteralPath '.\BOSS职位筛选与自动化投递平台——分阶段开发文档.md' -Encoding UTF8
rg --files --hidden -g 'AGENTS.md' -g 'AGENTS.override.md' -g '!.git' -g '!.venv' 'D:\boss投递'
Test-Path -LiteralPath '.\boss-jobs-platform'
git status --short --branch
Get-Command py,node,npm.cmd,git
py -0p
py -3.12 --version
node --version
node -p 'process.release.lts || "not LTS"'
npm.cmd --version
git --version
Get-ExecutionPolicy -List
```

- 检查了盘符根目录、工作区和目标位置的 `AGENTS.md` 与 `AGENTS.override.md`，并用 `rg` 搜索工作区。未发现适用文件。
- 目标目录检查返回 `False`。父工作区的 Git 查询返回 `fatal: not a git repository (or any of the parent directories): .git`（退出码 `1`）。
- `py.exe` 位于 `C:\WINDOWS\py.exe`。`py -0p` 输出 `No installed Pythons found!`（退出码 `0`）。`py -3.12 --version` 输出 `No installed Python found!`（退出码 `112`）。
- `node --version` 输出 `v24.18.1`，LTS 名称为 `Krypton`。`npm.cmd --version` 输出 `11.16.0`，`git --version` 输出 `git version 2.55.0.windows.3`。四项退出码均为 `0`。
- PowerShell 7 的 `LocalMachine` 为 `RemoteSigned`，其余作用域为 `Undefined`。Node.js 24 LTS 满足选定的 Vite 8 基线。 [Vite 8 官方发布说明](https://vite.dev/blog/announcing-vite8) · [Node.js 发布状态](https://nodejs.org/en/about/previous-releases)

## 项目与虚拟环境初始化

启动器失败后，先枚举了 `python.exe`。首次取路径时同时取到解释器和 Windows 应用别名，PowerShell 将两个路径合成了一个命令名并报错。加上 `Select-Object -First 1` 后，实际运行的解释器为 `D:\Users\young\AppData\Local\Programs\Python\Python312\python.exe`。

```powershell
$stagePython = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
& $stagePython --version
& $stagePython -c 'import sys, venv; print(sys.executable); print(sys.version_info[:2]); print(venv.__file__)'
New-Item -ItemType Directory -Path '.\boss-jobs-platform'
Set-Location -LiteralPath '.\boss-jobs-platform'
Get-ChildItem -Force
git init -b main
& $stagePython -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -I -m ensurepip --upgrade --default-pip
```

- 基础解释器输出 `Python 3.12.6` 与 `(3, 12)`，`venv` 从 Python 3.12 安装目录的 `Lib\venv\__init__.py` 导入。两项退出码均为 `0`。
- 新建目录后检查为空。`git init -b main` 输出 `Initialized empty Git repository in D:/boss投递/boss-jobs-platform/.git/`。
- 首次 `venv` 创建退出码为 `1`，报 `ensurepip ... returned non-zero exit status 1`。生成的虚拟环境解释器能返回 `Python 3.12.6`。单独运行 `ensurepip` 仍退出 `1`，输出 `PermissionError: [Errno 13] Permission denied`，出错路径是默认临时目录下的 `pip-24.2-py3-none-any.whl`。

在单独的 PowerShell 进程中，把本次运行的临时目录设在项目虚拟环境下，再执行创建命令补齐 pip 和激活脚本。临时目录为空后已移除。

```powershell
$stageTemp = Join-Path (Get-Location).Path '.venv\.bootstrap-tmp'
New-Item -ItemType Directory -Path $stageTemp | Out-Null
$env:TEMP = $stageTemp
$env:TMP = $stageTemp
$env:PYTHONUTF8 = '1'
$stagePython = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
& $stagePython -m venv .venv
.\.venv\Scripts\python.exe -I -X utf8 -m pip --version
if (-not (Get-ChildItem -LiteralPath $stageTemp -Force)) { Remove-Item -LiteralPath $stageTemp }
```

```text
TEMP=D:\boss投递\boss-jobs-platform\.venv\.bootstrap-tmp
venv creation retry exit=0
pip 24.2 from D:\boss投递\boss-jobs-platform\.venv\Lib\site-packages\pip (python 3.12)
pip exit=0
Empty temporary directory removed.
```

## Windows 环境自检

```powershell
# PowerShell 7，项目根目录
& .\scripts\check-env.ps1
.\.venv\Scripts\python.exe -I -X utf8 -m pip check
.\.venv\Scripts\python.exe -B -X utf8 -c 'import backend.app, scripts, sys; print(sys.prefix); print(sys.base_prefix); print(backend.app.__name__, scripts.__name__)'
```

```text
Project root: D:\boss投递\boss-jobs-platform
Windows: Microsoft Windows NT 10.0.26200.0
PowerShell: 7.6.9
Python 3.12.6
Python executable: D:\boss投递\boss-jobs-platform\.venv\Scripts\python.exe
pip 24.2 from D:\boss投递\boss-jobs-platform\.venv\Lib\site-packages\pip (python 3.12)
Node.js: v24.18.1 (Krypton) - D:\Node\node.exe
npm: 11.16.0
git version 2.55.0.windows.3
Environment check passed.
check-env exit=0

No broken requirements found.
pip check exit=0
D:\boss投递\boss-jobs-platform\.venv
D:\Users\young\AppData\Local\Programs\Python\Python312
backend.app scripts
package import exit=0
```

在父目录复验入口，确认脚本按自身位置定位项目。

```powershell
Set-Location -LiteralPath 'D:\boss投递'
& .\boss-jobs-platform\scripts\check-env.ps1
powershell.exe -NoProfile -File '.\boss-jobs-platform\scripts\check-env.ps1'
powershell.exe -NoProfile -Command '$PSVersionTable.PSVersion.ToString(); Get-ExecutionPolicy -List | Format-Table -AutoSize'
```

- PowerShell 7 从父目录运行，自检输出的项目根目录和工具版本与前一次相同，退出码为 `0`。
- Windows PowerShell `5.1.26100.9711` 的各策略作用域均为 `Undefined`，调用脚本时出现 `running scripts is disabled on this system` 与 `UnauthorizedAccess`（退出码 `1`）。本阶段采用已通过的 PowerShell 7 入口。
- 附带工具枚举未在 `PATH` 中找到 `mysql` 或 `mysqlsh`。`Get-Service -Name '*mysql*' -ErrorAction SilentlyContinue` 返回 `Cannot open Service Control Manager on computer '.'`。数据库环境归阶段 2 验收。

## 配置模板与 Git 忽略规则

在项目根目录读取两份模板并检查库名、账号、密码占位符和真实站点开关。

```powershell
$stageRuntime = Get-Content -LiteralPath '.\.env.example' -Encoding UTF8 |
    Where-Object { $_ -match '^[A-Z_]+=' } | ConvertFrom-StringData
$stageTest = Get-Content -LiteralPath '.\.env.test.example' -Encoding UTF8 |
    Where-Object { $_ -match '^[A-Z_]+=' } | ConvertFrom-StringData
if ($stageRuntime.DB_NAME -ne 'boss_jobs' -or $stageRuntime.DB_USER -ne 'boss_app' -or
    $stageTest.DB_NAME -ne 'boss_jobs_test' -or $stageTest.DB_USER -ne 'boss_app_test') {
    throw 'Database templates differ from the design.'
}
if ($stageRuntime.DB_PASSWORD -ne 'replace_with_app_password' -or
    $stageTest.DB_PASSWORD -ne 'replace_with_test_password' -or
    $stageRuntime.BOSS_REVIEW_ENABLED -ne 'false' -or $stageRuntime.BOSS_AUTO_ENABLED -ne 'false') {
    throw 'Credential placeholders or disabled switches are missing.'
}
'Database templates and disabled switches: PASS'
foreach ($stagePrivate in @('.env', '.env.test', 'runtime', 'frontend')) {
    if (Test-Path -LiteralPath $stagePrivate) { throw "Unexpected stage 1 path: $stagePrivate" }
    "$stagePrivate absent"
}
```

```text
Database templates and disabled switches: PASS
.env absent
.env.test absent
runtime absent
frontend absent
```

```powershell
$stageIgnored = @(
    '.env', '.env.test', '.env.local', 'backend/.env',
    'runtime/profiles/demo', 'runtime/locks/demo.lock', 'runtime/logs/demo.log',
    '.venv/Scripts/python.exe', 'frontend/node_modules/demo', 'frontend/dist/index.html',
    'backend/__pycache__/demo.pyc', 'backend/.pytest_cache/demo'
)
git check-ignore -v --no-index -- @stageIgnored
git check-ignore --no-index -- .env.example .env.test.example config/app.yaml
git ls-files --others --exclude-standard -- .env.example .env.test.example config/app.yaml
git status --short --branch --ignored
```

```text
.gitignore:2:.env                  .env
.gitignore:3:.env.*                .env.test
.gitignore:3:.env.*                .env.local
.gitignore:2:.env                  backend/.env
.gitignore:9:/runtime/             runtime/profiles/demo
.gitignore:9:/runtime/             runtime/locks/demo.lock
.gitignore:9:/runtime/             runtime/logs/demo.log
.gitignore:8:/.venv/               .venv/Scripts/python.exe
.gitignore:16:node_modules/        frontend/node_modules/demo
.gitignore:18:dist/                frontend/dist/index.html
.gitignore:12:__pycache__/         backend/__pycache__/demo.pyc
.gitignore:14:.pytest_cache/       backend/.pytest_cache/demo
ignore exit=0; matches=12/12
template ignore check exit=1 (expected 1)
.env.example
.env.test.example
config/app.yaml
```

输出中的列间制表符已对齐为空格。模板检查返回 `1` 表示指定路径均未被忽略，`git ls-files` 也列出了三个可纳入版本控制的文件。`git status` 显示 `No commits yet on main`，并以 `!! .venv/` 标记实际虚拟环境。

## 完成清单

- [x] 核对现有文件、项目和目录规则，按约定建立独立骨架。
- [x] 项目虚拟环境使用 Python 3.12.6，pip 与项目包导入实测通过。Node.js 24.18.1 为选定的 Vite 8 环境基线。
- [x] 运行库和测试库模板分开，密码为占位符，真实站点开关默认关闭。
- [x] Git 验证环境配置、浏览器 Profile、运行锁、日志、虚拟环境、构建产物和缓存的忽略规则，示例配置可纳入版本控制。
- [x] PowerShell 7 自检通过，命令、实际输出和失败项已记录。
