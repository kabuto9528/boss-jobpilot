# 阶段 4 · 数据库模型与 Jobs API

**2026-11-08（北京时间）｜阶段 4 验收通过。** 阶段 3 前置验收已通过；运行库和测试库均完成迁移，MySQL 集成测试及运行库 Jobs API 验收通过。所有自动化数据库写入仅使用 `boss_jobs_test`；运行库中的演示职位均标记为 `fixture`。本次工作止于阶段 4。

## 前置检查

- 阅读分阶段开发文档、`docs/acceptance/stage-03.md`、`docs/acceptance/stage-02.md`，并检查项目后端配置、现有代码、数据库和 Git 状态。
- 阶段 3 记录为 **通过**。仓库起始版本为 `07a09dd Add Vue admin shell and API status checks`；当时工作区干净。本阶段保留该版本内容，仅增加后端数据库模型、迁移、Jobs API、样例脚本、测试和本验收记录。
- 在 `D:\`、`D:\boss投递\` 和项目目录检查适用 `AGENTS.md`；未发现文件。
- 沿用现有 `.env` 与 `.env.test` 连接。数据库均为 MySQL `8.0.39`、`utf8mb4`、`utf8mb4_0900_ai_ci`，目标分别为 `boss_jobs` 与 `boss_jobs_test`。迁移前两个库均为空表状态。
- 管理员在本机 PowerShell 对两个已核对的库应用迁移。未在命令或验收记录中保存密码。之后用各自应用账号复核表、约束和安全闸记录。

## 实施内容

- `backend/migrations/001_initial.sql` 创建 `tasks`、`jobs`、`applications`、`automation_guard`；使用 InnoDB、`utf8mb4`、UTC `DATETIME(6)`。包含外键、唯一约束、状态检查、职位来源和身份唯一键、任务活动槽生成列、投递阻塞记录生成列及 `fixture` / `boss` 安全闸初始行。
- `backend/app/models/` 提供四张表的 SQLAlchemy 映射，迁移与 ORM 的字段、约束、索引、生成列表达式和 MySQL 表选项对应。
- `backend/app/schemas/jobs.py`、`backend/app/services/jobs.py`、`backend/app/api/jobs.py` 提供列表筛选、总数、分页、稳定排序、详情读取和 `JOB_NOT_FOUND` 404；应用入口已注册路由。
- `scripts/seed_demo.py` 只创建 `fixture` 来源职位，按 `(source, identity_key)` 幂等 upsert。样例包括中文及补充 Unicode 字符 `🚀`、`✨`。
- `backend/tests/test_jobs_mysql.py` 中的 7 个集成测试固定加载 `.env.test` 并连接 `boss_jobs_test`，覆盖重复导入、表结构与约束、生成列唯一槽、外键、Unicode、筛选、稳定排序、分页、404 和参数边界。约束写入用例在事务回滚。

## 迁移结果

管理员按本机验收步骤分别运行迁移后，使用 `.env.test` 与 `.env` 配置复核：

| 数据库 | 连接 | 表 | 约束 | 安全闸行 |
| --- | --- | --- | --- | --- |
| `boss_jobs_test` | MySQL 8.0.39，`utf8mb4` / `utf8mb4_0900_ai_ci` | `jobs`、`applications`、`tasks`、`automation_guard` 均存在 | 22 项；包含唯一键、外键与 CHECK 约束 | `fixture`、`boss` |
| `boss_jobs` | MySQL 8.0.39，`utf8mb4` / `utf8mb4_0900_ai_ci` | `jobs`、`applications`、`tasks`、`automation_guard` 均存在 | 22 项；包含唯一键、外键与 CHECK 约束 | `fixture`、`boss` |

## 实际验收命令与结果

```powershell
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_jobs_mysql.py .\backend\tests\test_health.py -q -p no:cacheprovider
```

结果：**11 passed in 3.17s**（Jobs MySQL 集成测试 7 项、现有健康/就绪测试 4 项）。测试配置通过 `load_database_settings(testing=True)` 固定指向 `boss_jobs_test`；没有测试写入 `boss_jobs`。

运行库样例导入命令执行两次：

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset jobs
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset jobs
```

两次均输出 `Upserted 5 fixture jobs; fixture total is 5.`。运行库核对到 5 个不同 fixture 身份键；中文和补充 Unicode 文本读回一致。测试库中的测试样例也仅属于 `fixture` 来源。

默认 API 端口 `8000` 已被一个旧服务占用：`/api/health` 与 `/api/ready` 返回 `200`，但 `/api/jobs` 返回 `404`。为避免停止未知进程，在本机回环地址 `127.0.0.1:8001` 启动当前代码进行 HTTP 验收，验收后已停止该进程：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

从 HTTP 请求实测结果：

- `GET /api/jobs?source=fixture&page=1&page_size=2`：`200`，总数 5，返回 2 条。
- 对样例职位请求 `GET /api/jobs/{job_id}`：`200`，职位字段和完整 JD 返回正确；`🚀`、`✨` 精确读回。
- 组合 `q`、`job_type`、`recommended`、`min_score` 筛选：`200`，匹配 2 条。
- `page_size=2` 分页得到 `2 + 2 + 1` 条；拼接 ID 与单页完整结果一致，无重复，重复请求排序一致。
- 请求不存在的职位：`404`，业务错误码为 `JOB_NOT_FOUND`。
- 参数边界 `page=0`、`page_size=101`、无效 `source`：均返回 `422`。

其他检查：模型表可用 MySQL 方言编译，FastAPI OpenAPI 包含列表与详情路径；Python `compileall` 通过；`git diff --check` 退出码为 `0`，仅有 `backend/app/main.py` 的 LF/CRLF 转换提示。

## 完成清单

- [x] 两库迁移完成，业务表分开，外键、唯一约束、生成列和安全闸行存在。
- [x] 重复导入、UTF-8 与补充 Unicode 文本、筛选、分页、稳定排序、缺失职位 404 通过。
- [x] 自动化测试仅写入测试库；运行库演示职位均为 `fixture` 来源。

## 剩余问题

- `127.0.0.1:8000` 上仍有旧 API 进程，当前未提供 Jobs 路由。阶段 4 的新 API 已在 `127.0.0.1:8001` 完成 HTTP 实测；进入阶段 5 前，应让管理前端代理指向使用当前代码的 API，或由用户确认后替换 `8000` 上的旧进程。
- 真实 BOSS 来源未启用；本阶段仅验收本地 fixture。

**阶段 4 已验收通过，按要求停止在阶段 4，未开始阶段 5。**
