Run a Cash Metrics white-box analysis (现金指标白盒总表) on stock: $ARGUMENTS

## 目的

产出一张**可对着财报逐格复现**的现金指标总表，供用户填入多公司对比总表。覆盖：
- 净利润、现金（狭义/广义）、交易性金融资产、有息负债（4分项）、总负债
- EBITDA（Tushare 口径 + 白盒还原）与估值倍数
- 真金白银现金流 AA（真实可支配现金结余，沿用龟龟因子3口径）
- 净现金（狭义/广义）、回收期（EV/AA 矩阵）
- 承诺值/预期值分红回购（优先复用 business-analysis 产出）

口径定义与复现步骤见 `strategies/cash_metrics/计算逻辑说明.md`。

## Prerequisite（建议）
- §1–§4（现金/负债、EBITDA、真金白银AA、回收期）仅需 Tushare，无前置依赖。
- §5（承诺/预期分红回购）优先复用 business-analysis 已从年报拆好的数据。**建议先跑 `/business-analysis {code}`**，这样 §5 能自动读到 `qualitative_report.md` 的分红承诺，无需重复读年报 PDF。未跑也可运行，§5 走兜底降级。

## Input Validation
- `$ARGUMENTS` 可以是**股票代码**（600887 / 000858.SZ / 00700.HK / AAPL）**或中文/英文公司名**（如"分众传媒""伊利"）。
- 名称→代码的解析在 Step 0 完成。若无法解析（既非有效代码、也匹配不到公司），询问用户提供有效代码/名称后再继续。

## Execution Instructions

### Step 0: 输入解析（名称 → 代码 → 输出目录）

`$ARGUMENTS` 传进来的可能是代码，也可能是公司名。按以下顺序解析出 `{code}`（Tushare 代码）和 `{code}_{company}` 输出目录：

1. **已是代码**（形如 6位数字、`.SZ`/`.SH`/`.HK`/`.US` 后缀、或纯字母 US ticker）→ 直接作 `{code}`，交给 `config.validate_stock_code` 归一化。
2. **是公司名 —— 目录优先（最稳）**：在 `output/` 下按名称匹配已有目录（如"分众传媒"→ `output/002027_分众传媒/`，"伊利"→ `output/600887_伊利股份/`，支持部分匹配）。命中 → 从目录名拆出 `{code}` 和 `{company}`，直接复用该目录，**无需联网**。
3. **是公司名但无匹配目录** → 用你的知识/联网确定其 A股/港股/美股代码（如"贵州茅台"→ 600519），得到 `{code}`；`{company}` 用规范简称。
4. **仍无法确定** → 停下，请用户给出准确代码。

> 后续所有 `{code}` / `{code}_{company}` 占位符均以 Step 0 的解析结果替换。`cash_metrics_engine.py --code` 只接受代码，务必传解析后的 `{code}`（不是原始中文名）。

### Step 1: Python White-box Computation (确定性、可复现)

```bash
python scripts/cash_metrics_engine.py --code {code} --output-dir output/{code}_{company}/
```

- 从 Tushare 重新采集原始数据（与 valuation_engine 一致），填充 §1-§17 到 _store
- 沿用龟龟因子3 公式计算，但每个中间量输出「原始行项值 + 算式代入 + 结果」
- 输出：`output/{code}_{company}/cash_metrics.md`
- 该文件的 §1-§4 为纯 Python 可复现部分；§5 为待补充占位（Step 2 原地编辑填入）

### Step 2: 补充承诺/预期分红回购（优先复用 business-analysis 已拆好的年报数据）

> **每次运行都执行 Step 2**：Step 1 会重新生成 `cash_metrics.md` 并把 §5 重置为占位表，因此 Step 2 每次都要重新填 §5（数据源随 business-analysis 更新，重填即取最新）。

Step 1 的 §5 是占位表。**核心原则：年报数据 business-analysis 已经拆好了，不要重复读 PDF/搜网。**
按以下**数据源优先级降级链**取承诺/回购信息，命中即用，不再往下走：

**2A: 首选 —— `output/{code}_{company}/qualitative_report.md`（固定名，business-analysis 标准产出）**
- 读末尾结构化字段：
  - `distribution_signal:` —— 分红/回购意向摘要（承诺值主来源，如"锁定 2025-2027 分红≥75%、每股≥1.22元"）
  - `capital_allocation_record:` —— 回购注销/资本配置记录
  - `payout_willingness:`（若有）—— 分配意愿强/中/弱
- 读正文 D4（管理层）/D5（MD&A）的股东回报规划、回购注销明细
- 命中 → 直接填 §5，跳到 2D

**2B: 次选 —— `{公司}_{代码}_分析报告.md` 或 `phase3_quantitative.md`（turtle 全量/定量产出）**
- 读"步骤10 分配意愿"块：股息承诺、承诺场合、支付率序列、均值M/标准差N、注销型回购O、稀释净效果
- 命中 → 直接填 §5，跳到 2D

**2C: 兜底 —— 仅当 2A/2B 文件均不存在时，才读年报 PDF/搜网**
- glob `output/{code}_{company}/` 下 `*{latest_fiscal_year}*年报*.pdf` / `*年度报告*.pdf` / `*annual*.pdf`（latest_fiscal_year = 当前日历年−1）
- 用户提供 PDF 路径/URL → 直接用
- 无 PDF → `/download-annual-report {stock_code}` 下载；仍失败 → WebSearch 利润分配政策/回购公告
- 全部失败 → §5 标注"⚠️ 无 business-analysis 产出且年报不可读，承诺值需人工填；建议先跑 /business-analysis {code}"

**2D: 填写 §5（区分承诺 vs 预期，不编造）**
- **承诺值** ← 年报明确承诺（如"三年分红≥75%、每股≥1.22元"）；无明确承诺 → 标"无明确金额承诺（历史稳定高分红）"
- **预期值** ← 历史支付率（来自 business-analysis 产出或年报）× AA/当前盈利 推算，标注"测算值，非承诺"
- **回购性质** ← 注销型（计股东回报）vs 激励型（会再稀释回来）——从分析产出的回购描述判定

**2E: 原地编辑输出**
- 用 Edit 工具直接修改 Step 1 生成的 `output/{code}_{company}/cash_metrics.md`，仅替换 §5 占位表为填好的承诺/预期内容（§1–§4 不动）。不再生成中间文件。

## Error Recovery
- cash_metrics_engine.py 失败 → 检查 TUSHARE_TOKEN，重试
- HK/US 部分接口无权限（如 hk_balancesheet）→ 对应板块自动降级为空，不中止；标注数据不可用
- §5 数据源降级链（2A→2B→2C）任一命中即用；全部失败 → §5 标"需人工填 + 建议先跑 /business-analysis"，不影响 §1-§4
- 始终产出最终报告，即使部分数据缺失

## Output
- **唯一产物**：output/{code}_{company}/cash_metrics.md（Step 1 生成 §1–§4，Step 2 原地填 §5）
  - 参数速览（供填表：净利润/广义现金/狭义现金/有息负债/总负债/EBITDA/真实现金流(最近一年AA)/AA_2y/AA_all）
  - 白盒明细（§1现金与负债 / §2 EBITDA与估值倍数 / §3真金白银AA / §4回收期 / §5承诺预期）

Usage:
- 用代码：`/cash-metrics 600887`、`/cash-metrics 00700.HK`、`/cash-metrics AAPL`
- 用名称：`/cash-metrics 分众传媒`、`/cash-metrics 伊利`（Step 0 自动解析为代码，已有 output/ 目录时直接复用）
