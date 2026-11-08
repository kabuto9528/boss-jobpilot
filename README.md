# BOSS 职位筛选与自动化投递平台

Windows 本地项目。阶段 1 建立工具基线、项目结构和配置约定。 [阶段 1 验收记录](docs/acceptance/stage-01.md)

阶段 2 提供 MySQL 连接、`/api/health` 和 `/api/ready`。本机建库、配置、启动命令及实测结果见 [阶段 2 验收记录](docs/acceptance/stage-02.md)。

## Windows 环境基线

| 工具 | 基线 | 本机验证版本 |
| --- | --- | --- |
| Python | 3.12.x | 3.12.6 |
| Node.js | 24.x LTS，用于后续 Vite 8 | 24.18.1（Krypton） |
| npm | 使用 `npm.cmd` | 11.16.0 |
| Git for Windows | 本地仓库及忽略规则验证 | 2.55.0.windows.3 |
| PowerShell | 用于环境自检 | 7.6.9 |

Vite 8 的 Node.js 要求包含 24.x。 [Vite 8 官方发布说明](https://vite.dev/blog/announcing-vite8) · [Node.js 发布状态](https://nodejs.org/en/about/previous-releases)

在 PowerShell 7 中进入项目根目录，运行以下命令。已有 `.venv` 时可直接运行自检。

```powershell
py -3.12 -m venv .venv
& .\scripts\check-env.ps1
```

若 `py` 找不到解释器，可先运行 `python.exe --version`。输出为 Python 3.12.x 时，使用 `python.exe -m venv .venv`。自检脚本直接调用项目的虚拟环境，无需激活。若初始化在临时目录权限处失败，验收记录中有本机处理步骤。

## 配置和目录

- `.env.example` 是运行库模板，真实站点的 Review 和 Auto 开关默认关闭。`.env.test.example` 是隔离测试库模板。配置数据库时分别复制为 `.env` 和 `.env.test`，再填写各自的本机凭据。
- `config/app.yaml` 保存本地样例搜索默认值、页数和职位数、超时、轮询间隔及浏览器 Profile 的相对路径。
- `backend/` 是 Python 包，`backend/requirements.txt` 固定了已验证的依赖版本。`scripts/` 保存本地自检脚本，`docs/acceptance/` 保存阶段验收。
- 浏览器专用 Profile 预留在 `runtime/profiles/`。Git 忽略整个 `runtime/`、实际环境配置、`.venv/` 及构建和缓存产物。
