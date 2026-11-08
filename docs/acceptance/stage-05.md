# 阶段 5 · Jobs 页面

**2026-11-08（北京时间）｜阶段 5 验收通过。** 阶段 4 验收记录已明确标记为通过。本阶段用本地样例接通职位列表和详情，按清单完成浏览器、API、回归测试和前端构建验收，工作止于阶段 5。

## 前置检查

- 阅读分阶段开发文档和 docs/acceptance/stage-04.md，检查 Vue 页面、管理壳、Jobs API、样例脚本及工作区状态。阶段 4 前置验收已通过，开始时 Git 工作区干净。父目录和项目中未找到适用的 AGENTS.md。
- 复用现有 Vue 管理壳、frontend/src/router/index.js 路由、Axios 客户端和既有列表/详情 API。后端按 Priority、Score 和 ID 排序并分页，前端只展示服务端当前页结果。
- 127.0.0.1:8000 上的既有服务对 /api/jobs 返回 404。为保留该进程，使用当前项目 API 的 127.0.0.1:8001 完成本地页面验收。Vite 的开发代理可配置可选目标，默认仍为 http://127.0.0.1:8000。本机 frontend/.env.development.local 被 .gitignore 忽略，并将代理目标设为 http://127.0.0.1:8001。

## 实施内容

- frontend/src/api/client.js 增加可取消的职位列表和详情请求。frontend/src/views/Jobs.vue 实现来源、关键词、类型、推荐状态和最低分筛选，服务端分页、重置、详情抽屉及加载、空态、错误和重试界面。
- 切换筛选并提交、调整每页条数时会回到第一页。取消过期请求，避免旧结果覆盖新筛选。最低分 0 保持有效。缺失分数显示“未评分”，JD 按纯文本节点呈现并保留换行。
- 列表和详情展示样例来源、职位与公司、地点、薪资、类型、Priority、Score、推荐状态和评分原因。scripts/seed_demo.py 新增低分实习样例，将社招 Priority 调整为文档定义的 4。
- backend/tests/test_jobs_mysql.py 增加低分实习与高分社招的明确顺序断言。该 MySQL 集成测试使用隔离测试库 boss_jobs_test。

## 实际验收命令与结果

重复导入本地样例，并经 Vite 代理查询分页列表：

~~~powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset jobs
.\.venv\Scripts\python.exe -m scripts.seed_demo --dataset jobs
Invoke-RestMethod 'http://127.0.0.1:5173/api/jobs?source=fixture&page=1&page_size=5'
~~~

两次均输出 Upserted 6 fixture jobs; fixture total is 6.。第一页 5 条，第二页 1 条，总数 6。完整列表顺序为：

~~~text
数据平台实习生 > 平台运维实习生 > 数字化运维实习生 > 云计算实习生 > SRE 校招工程师 > 高级平台工程师
~~~

其中 数字化运维实习生 为 P1、42 分，排在 P4、99 分的 高级平台工程师 之前。job_type=实习、recommended=false、min_score=0 的组合筛选返回 1 条。source=boss 返回 0 条。不匹配关键词也在页面中返回空结果。

实际执行的回归、构建与检查命令如下：

~~~powershell
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_jobs_mysql.py .\backend\tests\test_health.py -q -p no:cacheprovider
npm.cmd --prefix .\frontend run build
.\.venv\Scripts\python.exe -m compileall -q backend scripts
git diff --check
~~~

- MySQL Jobs 和健康/就绪测试 11 项通过，用时 3.54 秒。测试库为 boss_jobs_test。
- Vite 8.3.6 生产构建成功，无构建警告。Python compileall 和 git diff --check 的退出码为 0。Git 只提示现有 LF/CRLF 转换规则。

### 浏览器页面检查

打开 http://127.0.0.1:5173/jobs，实际操作与结果如下：

| 操作或状态 | 实测结果 |
| --- | --- |
| 页面首次打开 | 管理壳显示服务正常。默认来源为“本地样例”，6 条职位可读。 |
| 分页 | 默认每页 5 条。打开第 2 页后显示 P4、99 分的社招。低分实习 P1、42 分排在该社招之前。 |
| 来源筛选 | 选择并应用 BOSS 来源后显示空数据提示和对应来源标记。切回本地样例后 6 条职位重新出现。 |
| 关键词筛选 | 输入不匹配的关键词后显示空搜索结果，重置恢复列表。 |
| 其他筛选 | 实习、未推荐、最低分 0 组合后显示唯一匹配的 P1、42 分实习。 |
| 评分与详情 | 列表区分 42 分与缺 JD 的“未评分”。详情抽屉显示公司、城市、薪资、经验、类型、Priority、Score、推荐状态、原因及规则版本。纯文本 JD 保留原有换行和 Unicode 字符。 |
| 加载、错误及重试 | 临时本地接口将列表请求延迟 2 秒，并在第一次请求返回 503。页面实测先显示加载态，再显示错误原因和“重新加载”。点击后第二次请求成功，6 条职位恢复显示。临时进程已停止，本地代理恢复至 127.0.0.1:8001，重新加载后页面正常。 |

## 完成清单

- [x] 列表及详情可查看职位、JD、类型、Priority、Score 和推荐原因。
- [x] 来源、筛选、分页、加载、空态、错误和手动重试均通过实际页面检查。
- [x] 低分实习排在高分社招之前，列表 API 与 MySQL 排序回归断言均通过。
- [x] 样例明确标记为 fixture，重复导入不增加职位。自动化测试仅连接隔离测试库。
- [x] 后端回归测试、前端生产构建、Python 语法检查和 Git 差异检查通过。

## 剩余问题

- 本地 BOSS 来源目前没有样例职位，筛选结果为空。真实 BOSS 页面读取未启用或验收。
- 先前占用 127.0.0.1:8000 的 API 不包含 Jobs 路由。本机 Vite 已通过被忽略的本地代理配置连接当前项目的 127.0.0.1:8001 服务。

**阶段 5 已验收通过，按要求停止在阶段 5。**
