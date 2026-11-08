# 阶段 9 · Scoring Engine 与实习优先

**2026-11-08（北京时间）｜本地合成数据验收通过。** 开工前读取了阶段 8 验收记录，确认 Parser 本地验收通过；当前 `main` 工作区起始状态干净。检查 `D:\AGENTS.md`、上级目录和项目目录，未发现适用的 `AGENTS.md` 或 `AGENTS.override.md`。评分输入使用阶段 8 的 `NormalizedJob`，测试不启动浏览器、不连接 MySQL，也不调用 AI API。

## 实际命令

从项目根目录运行：

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m scripts.smoke_scoring --fixtures backend/tests/fixtures/scoring
.\.venv\Scripts\python.exe -m pytest .\backend\tests\test_scoring.py -q
.\.venv\Scripts\python.exe -m compileall -q backend scripts
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

## 实测结果

- 冒烟命令退出码 `0`，规则版本 `stage-09.1`，24 个固定合成职位全部与样例预期相符，`failures=[]`。七类目标方向均命中：运维实习 70、Linux 运维实习 68、云运维实习 56、DevOps 实习 61、系统/网络运维实习 56、技术支持实习 56、其他校招/初级方向 52。
- 阶段专项测试 `32 passed in 0.11s`。覆盖四级类型与 Priority、低分实习优先于高分社招、同分稳定排序、同义词去重、招聘和技能组上限、分数上下界、55 分含边界阈值、加扣分、三年以上硬排除、五年以上扣分、高级岗位、销售/付费培训排除、否定语境、缺失或不完整 JD、证据和规则版本、相同输入确定性及无效 YAML 配置拒绝。
- `compileall` 通过；`pip check` 输出 `No broken requirements found.`；`git diff --check` 退出码 `0`。Git 在检查时提示 `config.py` 的 LF 会在后续 Git 操作时转换为 CRLF；未报告空白错误。

## 阶段清单

- [x] 七类方向、排除词和必要语境均有样例覆盖。
- [x] 实习、校招/应届、初级、普通社招四级优先级及同级分数排序通过；同分保持输入顺序。
- [x] 输出类型、Priority、精确 Score、推荐结果、理由、规则 ID、证据字段与片段、分数变化和 `scoring_version`。
- [x] 缺失或不完整 JD 不推荐；无效评分配置会明确报错。
- [x] 阶段 9 验收只使用本地合成数据，与浏览器、MySQL、AI API 隔离。

## 剩余问题

- 真实 BOSS 读取仍为未启用、未验收；本阶段没有用真实页面调参。启用仍需阶段 7/8 的真实验收、已核验页面选择器及相应平台许可。
- 评分结果尚未接入阶段 10 Review 写库与任务闭环；后续阶段再集成。

**工作止于阶段 9。**
