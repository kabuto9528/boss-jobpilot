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
