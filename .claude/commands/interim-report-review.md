<!-- KEEP IN SYNC with .claude/skills/interim-report-review/SKILL.md — 10-node structure, forecast module, comparison-first principle must mirror the skill. -->

Download and interpret a company's latest interim/quarterly report, then compare it point-by-point against the existing 龟龟框架 annual analysis to re-test the investment thesis. Stock: $ARGUMENTS

## Input
- `$ARGUMENTS` = `<stock_code> [report_type] [year]`，report_type 默认 `中报`（可选 一季报/三季报），year 默认当前年。
- 若 `$ARGUMENTS` 为空或代码无效 → 先向用户索取有效股票代码。

## Step 0: 前置检查（对比基准）
- 检查 `output/{code}_{company}/{company}_{code}_分析报告.md` 是否存在。
  - **存在** → 读取其核心结论作为对比基准：一句话结论/仓位、GG/门槛/安全边际、护城河评级、**最大风险**、**结构化止损条件表**、**监控 KPI**、行业口径改写（如银行 OE/FCF/EBITDA 处理）。
  - **不存在** → 告知用户先运行 `/turtle-analysis {code}`；或征得同意后降级为"无基准中报快照"。

## Step 1: 下载中报并抽取文本
1. 调用 **download-annual-report** 技能获取全文 PDF（report_type=中报）。
   - 若 WebSearch 未索引最新中报，直接查 cninfo 公告 API（`category=category_bndbg_szsh`，`seDate=YYYY-06-01~YYYY-09-01`，`stock={code},{orgId}`），选**全文**而非"摘要"。
2. pdfplumber 抽取到 `output/{code}_{company}/interim_report_text_{year}.txt`（逐页 `===PAGE n===`，UTF-8）。

## Step 2: 提取关键指标（Windows：用 .venv/Scripts/python.exe；结果写文件或只 print 数字）
- 从 `interim_report_text_{year}.txt` 用 grep/sed 抽取，**必须覆盖年报止损条件表与监控 KPI 的每一项**（营收/归母/同比、ROE、NIM/毛利率、资产质量、资本充足率、存款成本率、护城河先行指标、分红/回购）。
- 抽取合并资产负债表实额（现金/存放央行/同业/拆出/买入返售/交易性金融资产；向央行借款/拆入/卖出回购/应付债券/同业存放/客户存款/总负债）供第 9 节。
- Tushare `daily_basic` 取最新 close/total_mv/pe_ttm/pb/dv_ttm。

## Step 3: 生成 `{company}_{code}_{year}中报解读.md`（固定 10 节）
元信息（解读日期、数据来源、最新股价/市值/估值 vs 年报分析日、对比基准摘要），然后：
1. 一句话结论（论点成立/动摇/证伪 + 仓位维持/调整 + 信心变化）
2. 核心财务指标对比总表（年报→中报→同比→论点影响；含 TTM 归母）
3. 护城河先行指标：走强/持平/收窄（年报 KPI 逐项 + 预警线 + 机制验证）
4. 年报头号风险的再评估（"最大风险"/"待验证事项"逐条检验 → 反证/证实/降级/升级）
5. 新增/需持续跟踪的风险点（中报暴露的新信号 + 缓冲评估）
6. 穿透回报率重算 GG（新市值 + TTM 基准 + 最新支付率 → 安全边际 + 目标买入价，对照年报）
7. 分配意愿复查（分红率/DPS/中期分红/回购 vs 年报评级与催化剂兑现）
8. 年报止损条件全量复查（结构化止损表逐项填中报实际值 + 触发状态）
9. **预期今年全年数据 + 现金/负债结构**：
   - 9.1 预期项汇总表（**每行"预期值 + 预期理由"**）：预期每股派息 DPS、预期回购、预期股息支付率、预期净利润(归母)、预期真实现金流入
   - 9.2 现金/负债结构实额表：广义现金、狭义现金、有息负债(狭义+广义)、总负债
   - 9.3 EBITDA（银行标注失真/仅形式列示）
   - 9.4 数据可靠性小结（实额/预期/失真 分级 + 理由）
10. 更新后的监控清单（增量）

末尾：综合裁决 ASCII 框（年报→中报关键变化对照 + 仓位裁决）+ 数据来源与免责（注明中报未经审计）。

## 关键原则
- **对比优先**：每个指标回答"印证/动摇年报哪条结论"，不孤立罗列。
- **止损条件是骨架**，穿透回报**必须重算**（股价/TTM 利润/分红率均变化）。
- **预期给理由**：H1 实际 + 历史 H1/全年占比 + 管理层指引，并标注可靠性等级。
- **行业适配**：沿用年报已定的口径改写（银行 EBITDA/广义现金失真处理），保持一致。
