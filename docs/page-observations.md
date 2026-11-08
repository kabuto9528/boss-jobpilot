# 页面观察记录

## 阶段 7 · 本地单职位样例

2026-11-08（北京时间）在 Playwright Chromium 中核验。页面来自 `127.0.0.1` 样例服务，职位与会话标记均为合成数据。

| 场景与来源 | 可见证据与唯一性 | 失效表现 |
| --- | --- | --- |
| 已登录，`backend/tests/fixtures/job.html` | 唯一 `main[data-fixture-page="job"]`，内有唯一直接子元素 `[data-fixture-session="logged-in"]` | 任一证据缺失、隐藏或重复时停止，返回 `PAGE_UNRECOGNIZED` |
| 登录失效，`backend/tests/fixtures/login.html` | 唯一 `main[data-fixture-page="login"]` 显示重新登录提示 | 返回 `LOGIN_REQUIRED`。多个可见登录容器返回 `PAGE_UNRECOGNIZED` |
| 风险，`backend/tests/fixtures/risk.html` 和职位页注入 | 页面可见的 `[data-fixture-risk]` 优先于已登录标记，唯一已知风险标记返回对应原因 | 未知或重复的风险标记返回 `PAGE_UNRECOGNIZED`。隐藏提示与 JD 中的“验证码”文字可正常读取 |
| 单职位详情，`backend/tests/fixtures/job.html` | 职位页内唯一可见的直接子容器 `[data-fixture-detail]`。容器内用 `[data-fixture-field]` 定位唯一、非空的职位编号、标题、公司、城市和 JD，JD 元素同时携带 `data-fixture-jd="complete"` | 详情容器不唯一、缺字段或 JD 尚在加载时停止，返回 `PAGE_UNRECOGNIZED` |
| 未知页面，样例服务的 `/unknown` | 缺少上述已知页面结构 | 返回 `PAGE_UNRECOGNIZED` |

## 阶段 7 · BOSS 直聘真实页面

**未启用，未验收。** 当前缺少覆盖自动化读取的平台许可。真实可见界面、Selector、用户扫码、关闭重开后的会话复用和单职位详情比对均待核验。

取得许可后，先在获准范围内检查实际可见页面，记录观察日期、场景、适用条件、Selector 的来源与唯一性及失效表现。随后由用户在独立可见会话手动扫码，关闭该会话后重开专用 Profile，核对会话复用和获准读取的一条职位及完整 JD。

## 阶段 8 · 本地搜索、列表与详情样例

2026-11-08（北京时间）使用 Playwright Chromium 核验，页面由回环地址上的样例服务提供。

| 场景与来源 | 可见证据与唯一性 | 失效表现 |
| --- | --- | --- |
| 搜索入口，`/search?keyword=…&page=1` | `backend/tests/fixtures/search.html` 内唯一可见的 `main[data-fixture-page="search"]`，含唯一直接子会话标记和唯一与搜索词一致的 `[data-fixture-field="keyword"]` | 搜索词、容器或会话证据不符时返回 `PAGE_UNRECOGNIZED`。可见风险或登录提示优先分类。 |
| 结果列表与空态 | 主容器的唯一可见直属 `[data-fixture-results]` 含可见直属 `[data-fixture-card]`。每张卡片恰有一个可见直属链接，可选的可见职位编号来自卡片内 `[data-fixture-field="source_job_id"]`。空态需要唯一的直属 `[data-fixture-empty]` 显示「没有符合条件的职位」。 | 列表无卡片、缺少明确空态、空态与结果容器并存、链接不唯一或链接超出样例读取范围时返回 `PAGE_UNRECOGNIZED`。 |
| 翻页 | 主容器内最多一个可见直属 `a[data-fixture-next]`，目标为同一关键词的样例分页 URL。 | 目标异常时返回 `PAGE_UNRECOGNIZED`。已访问的分页 URL、重复的卡片批次或核对后重复的身份批次返回 `page_not_advancing`。 |
| 详情与身份 | 复用阶段 7 的唯一职位容器、已登录标记和可见详情字段。列表提供编号时与详情逐字核对。样例 `/detail?job=…` 由 `job` 参数唯一确定一条职位，支持无可见编号时生成链接身份键。 | 编号冲突或详情结构不明确时返回 `PAGE_UNRECOGNIZED`。缺编号且链接无法证明身份时记 `missing_identity`。缺 JD 时保留可靠身份与 `jd_state=missing`。 |

## 阶段 8 · BOSS 直聘真实页面

**未启用，未验收。** 阶段 7 真实单职位读取仍待验收，缺少覆盖自动化读取的平台许可，真实搜索入口、列表卡片、空态、翻页与详情 Selector 均待现场核验。满足前置条件后，须核验这些可见证据及其失效表现，再按阶段 8 的最小范围命令联调。
