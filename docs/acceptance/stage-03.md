# 阶段 3 · Vue 管理壳与前后端通信

**2026-11-08（北京时间）｜阶段 3 验收通过。** 阶段 2 已在本机验收记录中通过；本阶段只建立前端管理壳和状态通信，没有进入阶段 4。

## 前置检查

- 阅读了 `D:\boss投递\BOSS职位筛选与自动化投递平台——分阶段开发文档.md`、本记录和 `docs/acceptance/stage-02.md`。阶段 2 记录明确标为通过。
- 检查了 `D:\AGENTS.md`、工作区根目录以及 `docs/`、`docs/acceptance/` 下的适用指引，未发现 `AGENTS.md`。检查前端目录时，仓库尚无前端脚手架。
- 初始工作区为 `main...origin/main`，没有未提交改动。沿用已有 FastAPI 健康/就绪接口、Python 虚拟环境和 `.gitignore`。
- 现有后端契约：`GET /api/health` 返回 `200 {"status":"ok"}`；`GET /api/ready` 在数据库可用时返回 `200 {"status":"ready"}`，连接检查失败时返回 `503 {"status":"unavailable"}`。
- 本机前端工具：Node.js `v24.18.1`、npm `11.16.0`。安装时锁定的依赖版本列在下方。

## 实施内容

- 在 `frontend/` 建立 Vue 3 + Vite 脚手架，提交 `package-lock.json` 以固定依赖。
- 使用 Element Plus 实现左侧管理导航、当前页面标题、连接状态、手动重查和服务异常提示；只注册管理壳当前使用的 Element Plus 组件。
- 使用 Vue Router 建立 `/dashboard`、`/jobs`、`/applications`、`/tasks`、`/settings` 五个占位页。业务数据和操作留待后续阶段。
- Axios 以相对路径 `/api` 请求健康和就绪接口。Vite 开发服务器固定绑定 `127.0.0.1:5173`，启用严格端口检查，并将 `/api` 代理到 `http://127.0.0.1:8000`。
- 管理壳每 5 秒重查连接状态。健康检查失败显示“后端服务不可用”；健康通过但就绪接口返回 `503` 显示“数据库不可用”；两个接口均成功显示“服务正常”。

## 实际验收命令与结果

从 `frontend/` 执行锁文件安装、依赖核对和生产构建：

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd ls --depth=0
npm.cmd run build
```

- `npm ci` 退出码 `0`，从锁文件安装 85 个包，用时 44 秒。
- `npm ls --depth=0` 显示：`@vitejs/plugin-vue@6.0.10`、`axios@1.21.0`、`element-plus@2.14.8`、`vite@8.3.6`、`vue-router@4.6.4`、`vue@3.5.45`。
- `npm run build` 退出码 `0`。Vite `8.3.6` 转换 1664 个模块并成功生成构建产物；最终 JS 为 `280.31 kB`（gzip `102.82 kB`），CSS 为 `367.09 kB`（gzip `49.65 kB`），无构建警告。

分别启动已有后端与 Vite 开发服务器：

```powershell
# 在项目根目录
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1

# 在 frontend/ 目录
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

通过前端地址读取代理接口：

```powershell
$health = Invoke-RestMethod 'http://127.0.0.1:5173/api/health'
$ready = Invoke-RestMethod 'http://127.0.0.1:5173/api/ready'
"health=$($health | ConvertTo-Json -Compress)"
"ready=$($ready | ConvertTo-Json -Compress)"
```

实测输出：

```text
health={"status":"ok"}
ready={"status":"ready"}
```

在浏览器打开 `http://127.0.0.1:5173` 后，实测依次点击五个菜单，分别进入 `/dashboard`、`/jobs`、`/applications`、`/tasks` 和 `/settings`，标题及占位内容均与页面匹配。顶部状态为“服务正常”。前端 Axios 也已成功读取两个接口。

### 不可用、区分和恢复

- **后端不可用：**停止本次启动的 Uvicorn 进程。前端轮询后显示“后端服务不可用”和“无法连接后端服务”的提示；重新启动同一后端后，无需重载页面，状态自动恢复为“服务正常”。
- **数据库不可用：**用不可达端口 `61729` 启动隔离的临时 FastAPI 实例，不修改 `.env`，不连接或写入数据库：

  ```powershell
  $appCode = "from backend.app.config import DatabaseSettings; from backend.app.main import create_app; import uvicorn; uvicorn.run(create_app(DatabaseSettings('127.0.0.1', 61729, 'boss_jobs', 'boss_app', 'unreachable')), host='127.0.0.1', port=8000, workers=1)"
  .\.venv\Scripts\python.exe -c $appCode
  ```

  此时健康接口仍为 `200`、就绪接口为 `503`；浏览器显示“数据库不可用”，并说明后端 API 可访问但数据库检查未通过。结束临时实例并恢复正常 API 后，页面自动回到“服务正常”。
- 所有本阶段启动的后端最终均已切回正常配置，两个 API 端口没有保留临时不可达数据库配置。

## 完成清单

- [x] Vue 3、Element Plus 和 Axios 已接入管理壳。
- [x] 五个路由入口可在浏览器中切换。
- [x] Vite `/api` 代理可读取健康和就绪接口。
- [x] 页面可区分服务不可用与数据库不可用；故障提示及恢复状态均已实测。
- [x] `npm ci` 锁文件安装及生产构建通过。
- [x] `git diff --check` 无空白错误；现有忽略规则覆盖 `frontend/node_modules` 与 `frontend/dist`。

## 剩余问题

没有阶段 3 阻塞项。五个页面目前是计划内占位页，Jobs 列表、任务操作、统计与设置数据仍未接入；这些属于后续阶段范围。未运行后端测试套件，本阶段按清单完成了前端构建、浏览器导航、代理接口、故障区分及恢复实测。
