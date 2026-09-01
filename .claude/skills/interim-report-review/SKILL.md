# Interim Report Review — Skill Definition（中报/季报解读）

## Skill Info
- **Name**: interim-report-review
- **Description**: 下载并解读某公司最新中报/季报，与该公司已有的年报分析报告（龟龟框架）逐条对比，检验投资论点是否成立，并输出更新裁决 + 预期数据模块。
- **Slash Command**: `/interim-report-review <stock_code> [report_type] [year]`
- **典型输出**: `output/{code}_{company}/{company}_{code}_{year}中报解读.md`

## 何时使用
- output 目录中**已存在**该公司的年报级分析报告（`{company}_{code}_分析报告.md`，由 `/turtle-analysis` 产出）；
- 用户想用**最新一期定期报告（中报/一季报/三季报）**来复查旧结论、更新投资裁决。
- 若无年报分析报告：提示先运行 `/turtle-analysis {code}`，或降级为纯中报快照（无对比基准）。

## Dependencies
- **download-annual-report skill**：获取中报 PDF（支持 A股/H股，cninfo/雪球/同花顺）。
- **已有年报分析报告**：作为对比基准（核心结论、GG、门槛、止损条件、监控 KPI、护城河评级、最大风险）。
- **Python venv**：`.venv/`（`tushare`、`pdfplumber`）。优先 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`。
- **Tushare Pro**：`TUSHARE_TOKEN`（取最新股价/市值/PE/PB/股息率，重算穿透回报）。

## Windows 注意（见 memory/MEMORY.md）
- 用 `.venv/Scripts/python.exe` 而非 `python3`；stdout 中文可能 gbk 报错 → **计算脚本结果写文件或只打印数字/ASCII**；PDF 用 pdfplumber 抽取到 `interim_report_text_{year}.txt` 再 grep/sed 分析，勿直接 print 大段中文。

---

## Pipeline（4 步）

### Step 0 — 前置检查
- 确认 `output/{code}_{company}/{company}_{code}_分析报告.md` 存在 → 作为对比基准（**读取其：一句话结论、GG/门槛/安全边际、护城河评级、最大风险、结构化止损条件表、监控 KPI**）。
- 无则告知用户先跑 `/turtle-analysis`，或征得同意后降级为无基准快照。

### Step 1 — 下载中报并抽取文本
1. 调用 `download-annual-report` 技能，report_type=中报（或 一季报/三季报），year 默认当前年。
   - 中报例年 8 月下旬披露；若 WebSearch 未索引，**直接查 cninfo 公告 API**：
     ```bash
     curl -s 'http://www.cninfo.com.cn/new/hisAnnouncement/query' \
       -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' -H 'User-Agent: Mozilla/5.0' \
       --data-urlencode 'stock={code},{orgId}' --data-urlencode 'tabName=fulltext' \
       --data-urlencode 'pageSize=30' --data-urlencode 'pageNum=1' --data-urlencode 'column=sse' \
       --data-urlencode 'category=category_bndbg_szsh' --data-urlencode 'seDate=YYYY-06-01~YYYY-09-01'
     ```
     选**全文**（非"摘要"），拿 `finalpage/YYYY-MM-DD/xxxx.PDF`。
2. 抽取全文到 `interim_report_text_{year}.txt`（pdfplumber，逐页 `===PAGE n===` 标记，UTF-8）。

### Step 2 — 提取关键指标（对齐年报止损条件/KPI）
用 grep/sed 从文本抽取，**必须覆盖年报止损条件表和监控 KPI 的每一项**：
- **利润表**：营业收入、净利息收入/非利息净收入（银行）、归母净利润、扣非、经营现金流净额，及各自同比。
- **盈利/护城河**：ROAE/ROAA、NIM/净利差（银行）、成本收入比、毛利率/净利率（非银行）。
- **资产质量（银行）**：不良率、拨备覆盖率、信用成本、房地产/零售/信用卡不良、逾期占比、不良生成率。
- **资本/负债**：核心一级资本充足率、总资产/总负债、客户存款、存款成本率、活期占比。
- **护城河先行指标**：客户数、AUM、财富管理/托管手续费、私行客户等（按行业调整）。
- **分红**：中期分红率、DPS、分红总额、回购。
- **资产负债表实额**（供现金/负债结构表）：现金、存放央行、同业、拆出、买入返售、交易性金融资产；向央行借款、拆入、卖出回购、应付债券、同业存放、客户存款、总负债。
- **股价**：`.venv/Scripts/python.exe` 取 Tushare daily_basic 最新 close/total_mv/pe_ttm/pb/dv_ttm。

### Step 3 — 生成中报解读报告
按下方**固定 10 节结构**写 `{company}_{code}_{year}中报解读.md`。核心是**逐条对比**，不是重新分析。

---

## 报告固定结构（10 节 + 元信息）

> 银行/非银行均适用；制造业口径失真项（银行的 EBITDA/广义现金/λ）按 turtle 框架标注 N/A 或改写。

**报告元信息**：解读日期、数据来源（中报 PDF + Tushare）、最新股价/市值/PE/PB/股息率（vs 年报分析日）、对比基准（年报结论摘要）。

1. **一句话结论**：论点成立/动摇/证伪？维持/调整仓位？信心增强/减弱？（对比年报裁决）
2. **核心财务指标对比总表**：年报值 → 中报值 → 同比 → 论点影响（✅/⚠️/❌）。含 TTM 归母（供穿透回报重算）。
3. **护城河先行指标：走强/持平/收窄**：年报监控 KPI 逐项 + 预警线 + 判定；验证护城河机制（如银行：资产端收益率降幅 vs 负债成本降幅）。
4. **年报头号风险的再评估**：把年报"最大风险""待验证事项"逐条用中报数据检验 → 反证/证实/降级/升级。
5. **新增/需持续跟踪的风险点**：中报暴露的新信号（含负面），给数据 + 缓冲评估。
6. **穿透回报率重算（GG）**：新市值 + TTM 归母基准 + 支付率 M（用中报最新分红率）→ GG、安全边际、目标买入价，与年报 GG 对照。
7. **分配意愿复查**：分红率/DPS/中期分红/回购，对比年报"分配意愿"评级与催化剂兑现情况。
8. **年报止损条件全量复查**：结构化止损表 8 项（或行业适配项）逐条填中报实际值 + 触发状态。
9. **预期今年全年数据 + 现金/负债结构**（见下方子结构）。
10. **更新后的监控清单（增量）**：较年报的监控重点变化。

**末尾**：综合裁决（ASCII 框，含年报→中报关键变化对照 + 仓位裁决）；数据来源与免责。

### 第 9 节子结构（预期数据模块）
- **9.1 预期项汇总表**（每行含"预期值 + 预期理由/推算依据"）：
  预期今年每股派息 DPS、预期今年回购、预期今年股息支付率 M、预期今年净利润（归母）、预期今年真实现金流入。
  推算方法：H1 实际 × 历史 H1/全年占比（或简单年化）；支付率用中报最新明示值；回购查是否有授权/计划。
- **9.2 现金/负债结构实额表**（报告期末，直接取合并资产负债表）：
  广义现金、狭义现金、有息负债（狭义主动负债 + 广义含同业存放）、总负债。
- **9.3 EBITDA**（预期全年）：非银行正常算；**银行标注失真、仅形式列示、不可用于决策**。
- **9.4 数据可靠性小结**：区分 实额(高)/预期(中高)/仅形式列示(失真)，逐项标注理由。

---

## 关键原则
1. **对比优先**：每个中报指标都要回答"这印证还是动摇了年报的哪条结论"，而非孤立罗列。
2. **止损条件是骨架**：年报的结构化止损表 + 监控 KPI 必须逐项复查，这是复用旧分析的核心价值。
3. **穿透回报重算**：股价变了、TTM 利润变了、分红率可能变了 → GG 必须重算，不能沿用年报值。
4. **银行/行业适配**：沿用年报分析报告已确定的口径改写（银行 OE/FCF/EBITDA 失真处理），保持一致。
5. **预期给理由**：所有"预期今年"数据必须写清推算依据（H1 实际 + 历史规律 + 管理层指引），并标注可靠性等级。
6. **中报未审计**：注明"未经审计（已经会计师审阅）"。

## Output
- `output/{code}_{company}/{company}_{code}_{year}中报解读.md`（主交付物）
- `output/{code}_{company}/{code}_{year}_中报.pdf` + `interim_report_text_{year}.txt`（中间产物）
