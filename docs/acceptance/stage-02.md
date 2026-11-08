# 阶段 2 · MySQL 8 与 FastAPI 基础连接

**2026-11-08（北京时间）｜阶段 2 验收通过。本机 MySQL 8.0.39 已完成初始化和复验。**

## 前置检查与本机服务

读取了分阶段开发文档、项目现有文件和阶段 1 验收记录。检查了盘符根目录、工作区和项目内的 `AGENTS.md`、`AGENTS.override.md`，未发现适用文件。项目初始状态为 `main...origin/main`，无待提交改动，已有被 Git 忽略的 `.venv/`。沿用阶段 1 的 Python 虚拟环境、配置模板和忽略规则。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
git status --short --branch --ignored
& .\scripts\check-env.ps1
Get-Service -Name 'MySQL*'
Get-Command mysql.exe -ErrorAction SilentlyContinue
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
& $mysql --version
.\.venv\Scripts\python.exe -c 'import socket; socket.create_connection(("127.0.0.1", 3306), timeout=2).close(); print("3306 OPEN")'
& $mysql --no-defaults --protocol=TCP --host=127.0.0.1 --port=3306 --connect-timeout=3 --user=root --skip-password -e 'SELECT VERSION();'
```

- 自检退出码为 `0`，确认 Python 3.12.6、pip 24.2、Node.js 24.18.1 和 PowerShell 7.6.9。
- 当前执行环境无法查询 Windows 服务管理器，`Test-NetConnection` 也遇到 CIM 权限限制。用 TCP 直连确认 `127.0.0.1:3306` 可达。
- MySQL 客户端未加入 PATH。通过安装目录的绝对路径运行，`mysql.exe` 与 `mysqld.exe` 均报告 `8.0.39`。
- 初次检查中，现有服务的无密码管理员登录返回 `ERROR 1045 (28000)`，退出码为 `1`。后续已通过交互输入管理员密码完成初始化，实测结果见下方本机补验。

## 实现与实测

配置在应用启动时按项目根目录加载。运行时读取 `.env`，集成测试显式读取 `.env.test`。两份配置各自校验库名和账号，只接收本机连接地址。SQLAlchemy 用 `URL.create` 传递密码，PyMySQL 连接使用 `utf8mb4`，连接、读写和连接池等待分别设为 2 秒。锁定的 `PyMySQL[rsa]` 依赖支持 `caching_sha2_password` 认证。就绪检查在同步路由执行 `SELECT 1`，连接池在取出连接时检查可用性。数据库异常响应仅包含通用状态字段。 [PyMySQL 安装文档](https://pymysql.readthedocs.io/en/latest/user/installation.html)

```powershell
# 虚拟环境中安装后，以最终锁定文件核对全部依赖
.\.venv\Scripts\python.exe -m pip install --no-index -r .\backend\requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_health.py -q -rs
git check-ignore -v --no-index -- .env .env.test
git check-ignore --no-index -- .env.example .env.test.example
git ls-files -- .env .env.test
git diff --check
```

- 依赖核对退出码 `0`，`pip check` 输出 `No broken requirements found.`。
- 当前执行环境沿用阶段 1 的临时目录处理方式，把 `TEMP` 和 `TMP` 指向虚拟环境内的临时目录。未配置本机 `.env.test` 的工作区运行得到 `3 passed, 1 skipped in 3.11s`，跳过的是隔离测试库实连。配置临时测试库后，同一测试文件得到 `4 passed in 2.76s`。
- `.env` 和 `.env.test` 命中 Git 忽略规则，两份示例未被忽略。实际凭据文件均未纳入版本控制。

### 临时 MySQL 8.0.39 验收

复用本机 `mysqld.exe`，在项目的 `runtime/` 下初始化独立数据目录，仅监听 `127.0.0.1:61729`。首次正常启动遇到 Windows 下的中文绝对数据路径问题。启动时以临时目录为工作目录，改用 `--basedir=.`、`--datadir=data`、`--tmpdir=.`，并从已安装的 MySQL 目录指定消息、插件和字符集路径，成功启动。临时实例采用下文的建库和授权语句，并用临时的两份配置文件测试带特殊字符的独立密码。

实际运行的检查如下。临时密码通过私有客户端配置传给 CLI，CLI 命令中的连接参数与下文复验命令相同，端口为 `61729`。

| 实测项 | 结果 |
| --- | --- |
| `mysql.exe` 执行 `SELECT VERSION(), CURRENT_USER(), DATABASE(), @@character_set_connection, @@character_set_database, @@collation_database; SHOW GRANTS;` | 两个账号均退出 `0`。服务端版本 `8.0.39`，分别认证为 `boss_app@127.0.0.1` 和 `boss_app_test@127.0.0.1`。库名分别为 `boss_jobs` 和 `boss_jobs_test`，连接及库字符集均为 `utf8mb4`，库排序规则均为 `utf8mb4_0900_ai_ci`。 |
| `SHOW GRANTS` | 两个账号均只有全局 `USAGE` 和各自库的 `SELECT, INSERT, UPDATE, DELETE`。没有额外的全局或 DDL 权限。 |
| 两个账号分别执行 `USE <另一套库>;` | 均退出 `1`，MySQL 错误 `1044`，拒绝跨库。 |
| 两个账号分别在自己的临时库尝试 `CREATE TABLE stage02_probe (id INT);` | 均退出 `1`，MySQL 错误 `1142`，拒绝建表。 |
| 用两份配置分别创建 SQLAlchemy 引擎，执行 `SELECT 1` | 两次均返回 `1`。 |
| 使用临时测试库执行 `python -m pytest backend/tests/test_health.py -q -p no:cacheprovider` | `4 passed in 2.76s`。 |

使用 Uvicorn 加载 `backend.app.main:app`，监听 `127.0.0.1:8000`，通过 HTTP 访问以下路径。随后仅停止临时数据库，在同一个 API 进程上复测。

| 数据库状态 | 请求 | 实测响应 |
| --- | --- | --- |
| 临时数据库在线 | `GET /api/health` | `200 {"status":"ok"}` |
| 临时数据库在线 | `GET /api/ready` | `200 {"status":"ready"}` |
| 临时数据库停止 | `GET /api/health` | `200 {"status":"ok"}` |
| 临时数据库停止 | `GET /api/ready` | `503 {"status":"unavailable"}`，约 2.09 秒 |

验收响应和记录均无密码或连接串。临时 API 和数据库进程已停止，临时目录和凭据已清理。清理后确认 `61729` 和 `8000` 已不可达，现有服务的 `3306` 仍可达。

## 本机 MySQL 8.0.39 补验

管理员通过隐藏输入在 `127.0.0.1:3306` 登录。执行 `SELECT VERSION(), CURRENT_USER(), @@global.partial_revokes, @@global.mandatory_roles`，结果为 `8.0.39`、`root@localhost`、`0` 和空值。下方同名对象查询均返回空。创建两套库后，在初始化会话执行 `SET SESSION generated_random_password_length = 32`，用 `IDENTIFIED WITH caching_sha2_password BY RANDOM PASSWORD` 为两套账号分别生成密码，再按下方语句授权。管理员会话结束后，分别由两份模板建立本机 `.env` 与 `.env.test`。

| 检查 | 实测结果 |
| --- | --- |
| MySQL CLI 执行 `SELECT VERSION(), CURRENT_USER(), DATABASE(), @@character_set_connection, @@character_set_database, @@collation_database, CURRENT_ROLE(); SHOW GRANTS;` | 两次退出码均为 `0`。`boss_app@127.0.0.1` 连接 `boss_jobs`，`boss_app_test@127.0.0.1` 连接 `boss_jobs_test`。连接和库的字符集均为 `utf8mb4`，库排序规则均为 `utf8mb4_0900_ai_ci`，当前角色均为 `NONE`。 |
| 核对两套账号的 `SHOW GRANTS` | 每套仅有全局 `USAGE` 和对应库的 `SELECT, INSERT, UPDATE, DELETE`，无全局操作或 DDL 权限。 |
| 使用 `.env` 和 `.env.test` 分别建立 SQLAlchemy 连接 | 两次 `SELECT 1` 均返回 `1`，两库各有 `0` 张表。两账号执行 `USE` 切换到另一套库均被拒绝，错误码 `1044`。 |
| Uvicorn 加载 `backend.app.main:app`，监听 `127.0.0.1:8000` | `/api/health` 返回 `200 {"status":"ok"}`，`/api/ready` 返回 `200 {"status":"ready"}`。验证后结束 API 进程。 |
| `.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_health.py -q -rA` | `4 passed in 3.27s`。隔离的不可达配置中，`/api/health` 返回 `200`，`/api/ready` 返回 `503` 和通用状态字段。 |

CLI 使用了临时选项文件传入各自的应用密码，验证后已删除该文件。两份本机配置的密码彼此独立，配置文件均命中 Git 忽略规则。

## 本机初始化和复验命令

以下初始化命令供新环境使用。当前已完成初始化，可直接从应用账号复验命令开始。MySQL 在终端提示时读取管理员密码。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
& $mysql --no-defaults --protocol=TCP --host=127.0.0.1 --port=3306 --user=root --password
```

在 MySQL 会话内，先核对服务版本、同名库和同名账号。

```sql
SELECT VERSION();
SHOW VARIABLES LIKE 'partial_revokes';

SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME IN ('boss_jobs', 'boss_jobs_test');

SELECT User, Host, plugin, account_locked
FROM mysql.user
WHERE User IN ('boss_app', 'boss_app_test');
```

如有同名对象，先确认归属，并用 `SHOW GRANTS FOR '用户名'@'主机';` 核对已有授权。确认对应的库和账号缺失后，才执行相应的创建语句。把 SQL 中的两处密码占位符分别替换为两组不同的本机专用密码。下面的 `GRANT` 适用于 `partial_revokes=OFF`，用 `\_` 将下划线按字面匹配。若查询结果为 `ON`，将两条 `GRANT` 中反引号内的库名分别写成 `boss_jobs` 与 `boss_jobs_test`。[MySQL GRANT 文档](https://dev.mysql.com/doc/refman/8.0/en/grant.html)

```sql
CREATE DATABASE IF NOT EXISTS boss_jobs CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS boss_jobs_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'boss_app'@'127.0.0.1' IDENTIFIED WITH caching_sha2_password BY '<运行库专用密码>';
CREATE USER 'boss_app_test'@'127.0.0.1' IDENTIFIED WITH caching_sha2_password BY '<测试库专用密码>';
GRANT SELECT, INSERT, UPDATE, DELETE ON `boss\_jobs`.* TO 'boss_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE ON `boss\_jobs\_test`.* TO 'boss_app_test'@'127.0.0.1';
```

退出管理员会话。复制缺失的配置文件，在本地编辑各自的 `DB_PASSWORD`。可用单引号包住含空格或 `#` 的值。保存后启动 API。

```powershell
if (-not (Test-Path -LiteralPath '.\.env')) { Copy-Item -LiteralPath '.\.env.example' -Destination '.\.env' }
if (-not (Test-Path -LiteralPath '.\.env.test')) { Copy-Item -LiteralPath '.\.env.test.example' -Destination '.\.env.test' }
# 编辑 .env 和 .env.test 后再运行
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

另开 PowerShell 7 窗口复验。两个 CLI 命令分别在终端提示时输入对应的应用账号密码。

```powershell
Set-Location -LiteralPath 'D:\boss投递\boss-jobs-platform'
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
$query = 'SELECT VERSION(), CURRENT_USER(), DATABASE(), @@character_set_connection, @@character_set_database, @@collation_database; SHOW GRANTS;'
& $mysql --no-defaults --protocol=TCP --host=127.0.0.1 --port=3306 --user=boss_app --password --default-character-set=utf8mb4 boss_jobs -e $query
& $mysql --no-defaults --protocol=TCP --host=127.0.0.1 --port=3306 --user=boss_app_test --password --default-character-set=utf8mb4 boss_jobs_test -e $query
(Invoke-WebRequest 'http://127.0.0.1:8000/api/health').StatusCode
(Invoke-WebRequest 'http://127.0.0.1:8000/api/ready').StatusCode
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_health.py -q
```

复验应得到两个 HTTP `200` 和 `4 passed`。测试文件使用隔离配置复验数据库不可达时的 `503`。

## 完成清单

- [x] 临时实例的运行库和测试库均为 `utf8mb4`，各用独立的专用账号。
- [x] 临时实例上的 CLI 与 SQLAlchemy 均连接成功，两个账号均无全局或 DDL 权限。
- [x] 正常和数据库不可用时的 HTTP 状态已实测，自动化测试覆盖缺配置、不可达、测试配置隔离与正常就绪。
- [x] 配置及测试输出经过脱敏，Git 忽略实际凭据文件。
- [x] 现有 MySQL 服务的两套库及专用账号已初始化，CLI、SQLAlchemy、HTTP 和隔离测试均已复验。
