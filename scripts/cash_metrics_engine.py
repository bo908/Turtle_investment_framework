#!/usr/bin/env python3
"""Cash Metrics Engine — 白盒可复现的现金/负债/真金白银现金流总表.

沿用龟龟框架因子3 的口径（真实现金收入 − 经营现金支出W − 全额capex），
但每个中间量都输出「原始行项值 + 算式代入 + 结果」，使用户可对着财报逐格复现。

计算口径见 strategies/cash_metrics/计算逻辑说明.md。

Usage:
    python scripts/cash_metrics_engine.py --code 600887 --output-dir output/600887_伊利股份/
"""

import argparse
import os
import statistics
import sys

from config import get_token, validate_stock_code
from format_utils import format_number, format_table, format_header

# 有息负债的 4 个分项（资产负债表原始字段）
IBD_COMPONENTS = [
    ("短期借款", "st_borr"),
    ("长期借款", "lt_borr"),
    ("应付债券", "bond_payable"),
    ("一年内到期非流动负债", "non_cur_liab_due_1y"),
]


class CashMetricsEngine:
    """白盒现金指标引擎。

    需要一个已 assemble_data_pack 的 TushareClient（_store 已填充）。
    """

    def __init__(self, ts_code: str, output_dir: str, client):
        self.ts_code = ts_code
        self.output_dir = output_dir
        self.client = client
        self._sf = client._safe_float

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _annual_df(self, key: str):
        return self.client._get_annual_df(key)

    def _unit(self) -> str:
        return self.client._unit_label()

    def _price_unit(self) -> str:
        return self.client._price_unit()

    @staticmethod
    def _by_year(df) -> dict:
        """Build {year_str: row} lookup from an annual DataFrame."""
        out = {}
        if df is None or df.empty:
            return out
        for _, r in df.iterrows():
            out[str(r["end_date"])[:4]] = r
        return out

    def _fmt(self, v) -> str:
        """Format raw value to millions with comma separators."""
        return format_number(v)

    def _raw_row(self, label: str, by_year: dict, col: str, years: list) -> list:
        """Build a table row: [label, val_year1, val_year2, ...] from raw line items."""
        row = [label]
        for y in years:
            r = by_year.get(y)
            row.append(self._fmt(self._sf(r.get(col)) if r is not None else None))
        return row

    def _market_cap(self) -> dict:
        """Extract market cap in raw reporting-currency units (matches factor4 logic)."""
        bi_df = self.client._store.get("basic_info")
        if bi_df is None or bi_df.empty:
            return {}
        bi = bi_df.iloc[0]
        close = self._sf(bi.get("close"))

        if self.client._is_us(self.ts_code):
            total_mv_raw = self._sf(bi.get("total_mv"))  # raw USD
            if not total_mv_raw:
                return {}
            return {"mkt_cap_raw": total_mv_raw,
                    "total_shares": (total_mv_raw / close) if close else None,
                    "close": close, "source": "§1 total_mv (原始美元)"}
        if self.client._is_hk(self.ts_code):
            total_market_cap = self._sf(bi.get("total_market_cap"))  # 百万港元
            if not total_market_cap:
                return {}
            mkt_cap_raw = total_market_cap * 1e6
            return {"mkt_cap_raw": mkt_cap_raw,
                    "total_shares": (mkt_cap_raw / close) if close else None,
                    "close": close, "source": "§1 total_market_cap × 1e6"}
        # A-share
        total_mv_wan = self._sf(bi.get("total_mv"))      # 万元
        total_share_wan = self._sf(bi.get("total_share"))  # 万股
        if not total_mv_wan:
            return {}
        return {"mkt_cap_raw": total_mv_wan * 10000,
                "total_shares": (total_share_wan * 10000) if total_share_wan else None,
                "close": close, "source": "§1 total_mv(万元) × 10000"}

    # ------------------------------------------------------------------
    # Section 1: 现金与负债结构
    # ------------------------------------------------------------------

    def _section_cash_debt(self):
        bs = self._annual_df("balance_sheet")
        if bs.empty:
            return None, {}
        by_year = self._by_year(bs)
        years = [str(r["end_date"])[:4] for _, r in bs.iterrows()][:5]

        lines = [format_header(3, "1. 现金与负债结构"), ""]
        lines.append(f"> 所有原始行项来自 §4 合并资产负债表，期末点值，单位 {self._unit()}。")
        lines.append("> 有息负债 = 短期借款 + 长期借款 + 应付债券 + 一年内到期非流动负债。")
        lines.append("")

        headers = ["行项 [来源: §4资产负债表]"] + years
        rows = []
        rows.append(self._raw_row("货币资金 money_cap", by_year, "money_cap", years))
        rows.append(self._raw_row("交易性金融资产 trad_asset", by_year, "trad_asset", years))
        for label, col in IBD_COMPONENTS:
            rows.append(self._raw_row(f"  {label} {col}", by_year, col, years))

        # 有息负债合计
        ibd_by_year = {}
        ibd_row = ["= 有息负债合计（4项之和）"]
        for y in years:
            r = by_year.get(y)
            total = 0.0
            any_valid = False
            for _, col in IBD_COMPONENTS:
                v = self._sf(r.get(col)) if r is not None else None
                if v is not None:
                    total += v
                    any_valid = True
            ibd_by_year[y] = total if any_valid else None
            ibd_row.append(self._fmt(ibd_by_year[y]))
        rows.append(ibd_row)

        rows.append(self._raw_row("总负债 total_liab", by_year, "total_liab", years))

        # 净现金（狭义/广义）
        narrow_row = ["= 狭义净现金（货币资金 − 有息负债）"]
        broad_row = ["= 广义净现金（货币资金 + 交易性 − 有息负债）"]
        narrow_by_year, broad_by_year = {}, {}
        for y in years:
            r = by_year.get(y)
            cash = self._sf(r.get("money_cap")) if r is not None else None
            trad = self._sf(r.get("trad_asset")) if r is not None else None
            ibd = ibd_by_year.get(y)
            narrow = (cash - ibd) if (cash is not None and ibd is not None) else None
            broad = (cash + (trad or 0) - ibd) if (cash is not None and ibd is not None) else None
            narrow_by_year[y] = narrow
            broad_by_year[y] = broad
            narrow_row.append(self._fmt(narrow))
            broad_row.append(self._fmt(broad))
        rows.append(narrow_row)
        rows.append(broad_row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")

        # 算式代入（最新年）
        latest = years[0]
        r = by_year.get(latest)
        if r is not None:
            comps = [self._sf(r.get(c)) or 0 for _, c in IBD_COMPONENTS]
            cash = self._sf(r.get("money_cap")) or 0
            trad = self._sf(r.get("trad_asset")) or 0
            lines.append(f"**{latest} 算式代入**（{self._unit()}）：")
            lines.append("```")
            lines.append(f"有息负债 = {self._fmt(comps[0])} + {self._fmt(comps[1])} + "
                         f"{self._fmt(comps[2])} + {self._fmt(comps[3])} = {self._fmt(ibd_by_year[latest])}")
            lines.append(f"狭义净现金 = {self._fmt(cash)} − {self._fmt(ibd_by_year[latest])} "
                         f"= {self._fmt(narrow_by_year[latest])}")
            lines.append(f"广义净现金 = {self._fmt(cash)} + {self._fmt(trad)} − {self._fmt(ibd_by_year[latest])} "
                         f"= {self._fmt(broad_by_year[latest])}")
            lines.append("```")

        # 原始现金（不减负债）：狭义现金=货币资金；广义现金=货币资金+交易性金融资产
        r_latest = by_year.get(latest)
        cash_latest = self._sf(r_latest.get("money_cap")) if r_latest is not None else None
        trad_latest = self._sf(r_latest.get("trad_asset")) if r_latest is not None else None
        cash_narrow = cash_latest
        cash_broad = None
        if cash_latest is not None:
            cash_broad = cash_latest + (trad_latest or 0)
        total_liab_latest = self._sf(r_latest.get("total_liab")) if r_latest is not None else None

        ctx = {
            "years": years,
            "ibd_latest": ibd_by_year.get(latest),
            "total_liab_latest": total_liab_latest,        # 总负债
            "narrow_latest": narrow_by_year.get(latest),   # 狭义净现金（减负债）
            "broad_latest": broad_by_year.get(latest),     # 广义净现金（减负债）
            "cash_narrow_latest": cash_narrow,             # 狭义现金（货币资金，不减负债）
            "cash_broad_latest": cash_broad,               # 广义现金（货币资金+交易性，不减负债）
            "latest_year": latest,
        }
        return "\n".join(lines), ctx

    # ------------------------------------------------------------------
    # Section 3: 真金白银现金流 AA
    # ------------------------------------------------------------------

    def _section_aa(self):
        income = self._annual_df("income")
        bs = self._annual_df("balance_sheet")
        cf = self._annual_df("cashflow")
        if income.empty or bs.empty or cf.empty:
            return None, {}

        inc_by = self._by_year(income)
        bs_by = self._by_year(bs)
        cf_by = self._by_year(cf)
        income_years = [str(r["end_date"])[:4] for _, r in income.iterrows()]

        # 仅保留有上年资产负债表可算变动的年份
        years = [y for y in income_years if str(int(y) - 1) in bs_by and y in bs_by][:5]
        if not years:
            return None, {}

        lines = [format_header(3, "3. 真金白银现金流（真实可支配现金结余 AA）"), ""]
        lines.append("> 口径：真实现金收入 − 经营现金支出W − 全额capex（资本投资一律视作开支，不加回投资收益）。")
        lines.append(f"> 单位 {self._unit()}。ΔX = 本年期末 − 上年期末。")
        lines.append("")

        # ---- 3A 真实现金收入 ----
        lines.append("#### 3A 真实现金收入")
        lines.append("")
        hdr = ["行项 [来源]"] + years
        rows = []
        rows.append(self._raw_row("营业收入 S revenue [§3]", inc_by, "revenue", years))

        ar_cur = ["应收账款(本年末) accounts_receiv [§4]"]
        ar_prev = ["应收账款(上年末) [§4]"]
        cl_cur = ["合同负债(本年末) contract_liab [§4]"]
        cl_prev = ["合同负债(上年末) [§4]"]
        t_row = ["T 应收变动 = 本年末 − 上年末"]
        u_row = ["U 合同负债变动 = 本年末 − 上年末"]
        rev_cash_row = ["= 真实现金收入 = S − max(0,T) − max(0,−U)"]
        tcr_by = {}
        for y in years:
            py = str(int(y) - 1)
            s = self._sf(inc_by[y].get("revenue")) if y in inc_by else None
            arc = self._sf(bs_by[y].get("accounts_receiv")) or 0
            arp = self._sf(bs_by[py].get("accounts_receiv")) or 0
            clc = self._sf(bs_by[y].get("contract_liab")) or 0
            clp = self._sf(bs_by[py].get("contract_liab")) or 0
            t = arc - arp
            u = clc - clp
            tcr = (s - max(0, t) - max(0, -u)) if s is not None else None
            tcr_by[y] = tcr
            ar_cur.append(self._fmt(arc)); ar_prev.append(self._fmt(arp))
            cl_cur.append(self._fmt(clc)); cl_prev.append(self._fmt(clp))
            t_row.append(self._fmt(t)); u_row.append(self._fmt(u))
            rev_cash_row.append(self._fmt(tcr))
        rows += [ar_cur, ar_prev, cl_cur, cl_prev, t_row, u_row, rev_cash_row]
        lines.append(format_table(hdr, rows, alignments=["l"] + ["r"] * len(years)))
        lines.append("")

        # ---- 3B 经营现金支出 W ----
        lines.append("#### 3B 经营现金支出 W = W1供应商 + W2员工 + W3现金税 + W4利息")
        lines.append("")
        rows = []
        rows.append(self._raw_row("营业成本 oper_cost [§3]", inc_by, "oper_cost", years))
        ap_cur = ["应付账款(本年末) acct_payable [§4]"]
        ap_prev = ["应付账款(上年末) [§4]"]
        w1_row = ["W1 = 营业成本 + max(0,−ΔAP)"]
        w2_row = ["W2 支付职工现金 c_pay_to_staff [§5]"]
        it_row = ["所得税 income_tax [§3]"]
        dta_row = ["ΔDTA 递延所得税资产变动 [§4]"]
        dtl_row = ["ΔDTL 递延所得税负债变动 [§4]"]
        w3_row = ["W3 = 所得税 − (ΔDTA − ΔDTL)"]
        w4_row = ["W4 财务费用 finance_exp [§3]"]
        w_row = ["= W 合计"]
        w_by = {}
        w2_fallback_used = False
        for y in years:
            py = str(int(y) - 1)
            oper_cost = self._sf(inc_by[y].get("oper_cost")) or 0
            apc = self._sf(bs_by[y].get("acct_payable")) or 0
            app = self._sf(bs_by[py].get("acct_payable")) or 0
            ap_change = apc - app
            w1 = oper_cost + max(0, -ap_change)

            w2_raw = self._sf(cf_by[y].get("c_pay_to_staff")) if y in cf_by else None
            if w2_raw is None or w2_raw == 0:
                sell = self._sf(inc_by[y].get("sell_exp")) or 0
                admin = self._sf(inc_by[y].get("admin_exp")) or 0
                rd = self._sf(inc_by[y].get("rd_exp")) or 0
                w2 = sell + admin + rd
                if w2 > 0:
                    w2_fallback_used = True
                    w2_disp = self._fmt(w2) + "†"
                else:
                    w2_disp = self._fmt(w2)
            else:
                w2 = w2_raw
                w2_disp = self._fmt(w2)

            income_tax = self._sf(inc_by[y].get("income_tax")) or 0
            dtac = self._sf(bs_by[y].get("defer_tax_assets")) or 0
            dtap = self._sf(bs_by[py].get("defer_tax_assets")) or 0
            dtlc = self._sf(bs_by[y].get("defer_tax_liab")) or 0
            dtlp = self._sf(bs_by[py].get("defer_tax_liab")) or 0
            d_dta = dtac - dtap
            d_dtl = dtlc - dtlp
            w3 = income_tax - (d_dta - d_dtl)
            w4 = self._sf(inc_by[y].get("finance_exp")) or 0
            w = w1 + w2 + w3 + w4
            w_by[y] = w

            ap_cur.append(self._fmt(apc)); ap_prev.append(self._fmt(app))
            w1_row.append(self._fmt(w1)); w2_row.append(w2_disp)
            it_row.append(self._fmt(income_tax))
            dta_row.append(self._fmt(d_dta)); dtl_row.append(self._fmt(d_dtl))
            w3_row.append(self._fmt(w3)); w4_row.append(self._fmt(w4))
            w_row.append(self._fmt(w))
        rows += [ap_cur, ap_prev, w1_row, w2_row, it_row, dta_row, dtl_row, w3_row, w4_row, w_row]
        lines.append(format_table(hdr, rows, alignments=["l"] + ["r"] * len(years)))
        if w2_fallback_used:
            lines.append("")
            lines.append("> † W2: c_pay_to_staff 为空，已用利润表 SGA（销售+管理+研发费用）替代，偏保守。")
        lines.append("")

        # ---- 3C 基准结余 + AA ----
        lines.append("#### 3C 基准结余 = 真实现金收入 − W − 全额capex")
        lines.append("")
        rows = []
        tcr_disp = ["真实现金收入（3A）"]
        w_disp = ["− W 经营支出（3B）"]
        capex_disp = ["− 资本开支 c_pay_acq_const_fiolta [§5]"]
        surplus_disp = ["= 基准结余"]
        surplus_by = {}
        for y in years:
            tcr = tcr_by.get(y)
            w = w_by.get(y)
            capex = self._sf(cf_by[y].get("c_pay_acq_const_fiolta")) if y in cf_by else None
            surplus = None
            if tcr is not None and w is not None and capex is not None:
                surplus = tcr - w - capex
            surplus_by[y] = surplus
            tcr_disp.append(self._fmt(tcr))
            w_disp.append(self._fmt(w))
            capex_disp.append(self._fmt(capex))
            surplus_disp.append(self._fmt(surplus))
        rows += [tcr_disp, w_disp, capex_disp, surplus_disp]
        lines.append(format_table(hdr, rows, alignments=["l"] + ["r"] * len(years)))
        lines.append("")

        # AA 三口径
        surpluses = [surplus_by[y] for y in years if surplus_by[y] is not None]
        aa_2y = aa_all = aa_excl = None
        if surpluses:
            aa_all = sum(surpluses) / len(surpluses)
            aa_2y = sum(surpluses[:2]) / min(2, len(surpluses))
            pos = [s for s in surpluses if s >= 0]
            aa_excl = sum(pos) / len(pos) if pos else aa_all
            lines.append(f"- **AA_2y（近2年均值，默认基准）= {self._fmt(aa_2y)} {self._unit()}**")
            lines.append(f"- AA_all（全部年份均值）= {self._fmt(aa_all)} {self._unit()}")
            lines.append(f"- AA_excl（剔除负值年份均值）= {self._fmt(aa_excl)} {self._unit()}")
            n = len(surpluses)
            lines.append(f"- 计算说明：AA_2y = ({self._fmt(surpluses[0])} + "
                         f"{self._fmt(surpluses[1]) if n > 1 else '—'}) / {min(2, n)}")

        # 真实现金流 = 最近一年 AA（最新年基准结余）
        aa_latest = surplus_by.get(years[0]) if years else None
        # 净利润（归母，最新年）
        np_latest = self._sf(inc_by[years[0]].get("n_income_attr_p")) if years and years[0] in inc_by else None

        ctx = {"aa_2y": aa_2y, "aa_all": aa_all, "aa_excl": aa_excl,
               "aa_latest": aa_latest, "np_latest": np_latest,
               "latest_year": years[0] if years else None}
        return "\n".join(lines), ctx

    # ------------------------------------------------------------------
    # Section 4: 回收期矩阵
    # ------------------------------------------------------------------

    def _section_payback(self, cash_ctx: dict, aa_ctx: dict):
        mc = self._market_cap()
        if not mc or not cash_ctx or not aa_ctx:
            return None
        mkt = mc.get("mkt_cap_raw")
        if not mkt:
            return None

        lines = [format_header(3, "4. 现金流回收期 = (市值 − 净现金) / AA"), ""]
        lines.append(f"> 分子 (市值 − 净现金) 即企业价值 EV；分母 AA 为真金白银年现金流。结果单位：年。")
        lines.append(f"> 市值来源：{mc.get('source')}；净现金取最新年 {cash_ctx.get('latest_year')}。")
        lines.append("")
        lines.append(f"- 市值 = {self._fmt(mkt)} {self._unit()}")
        lines.append(f"- 狭义净现金 = {self._fmt(cash_ctx.get('narrow_latest'))} {self._unit()}")
        lines.append(f"- 广义净现金 = {self._fmt(cash_ctx.get('broad_latest'))} {self._unit()}")
        lines.append("")

        def _payback(net_cash, aa):
            if net_cash is None or aa is None or aa == 0:
                return "—"
            return f"{(mkt - net_cash) / aa:.2f} 年"

        headers = ["净现金口径 ＼ AA口径", "AA_2y", "AA_all"]
        rows = [
            ["狭义净现金",
             _payback(cash_ctx.get("narrow_latest"), aa_ctx.get("aa_2y")),
             _payback(cash_ctx.get("narrow_latest"), aa_ctx.get("aa_all"))],
            ["广义净现金",
             _payback(cash_ctx.get("broad_latest"), aa_ctx.get("aa_2y")),
             _payback(cash_ctx.get("broad_latest"), aa_ctx.get("aa_all"))],
        ]
        lines.append(format_table(headers, rows, alignments=["l", "r", "r"]))
        lines.append("")

        # 算式代入（狭义 × AA_2y）
        nc = cash_ctx.get("narrow_latest")
        aa2 = aa_ctx.get("aa_2y")
        if nc is not None and aa2:
            lines.append("**算式代入（狭义净现金 × AA_2y）**：")
            lines.append("```")
            lines.append(f"回收期 = (市值 − 狭义净现金) / AA_2y")
            lines.append(f"      = ({self._fmt(mkt)} − ({self._fmt(nc)})) / {self._fmt(aa2)}")
            lines.append(f"      = {(mkt - nc) / aa2:.2f} 年")
            lines.append("```")

        # 补充：投资活动现金流净额原值（供参考）
        cf = self._annual_df("cashflow")
        if not cf.empty:
            cf_by = self._by_year(cf)
            cyears = [str(r["end_date"])[:4] for _, r in cf.iterrows()][:5]
            inv_row = self._raw_row("投资活动现金流净额 n_cashflow_inv_act [§5]", cf_by,
                                    "n_cashflow_inv_act", cyears)
            lines.append("")
            lines.append("> 参考：投资活动现金流净额原值（AA 已全额扣 capex，此处仅供了解投资规模）")
            lines.append("")
            lines.append(format_table(["行项 [来源]"] + cyears, [inv_row],
                                      alignments=["l"] + ["r"] * len(cyears)))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 2: EBITDA 与估值倍数
    # ------------------------------------------------------------------

    def _fetch_ebitda_components(self):
        """A股专用：补取 Tushare EBITDA 还原所需的3个未采集字段。

        返回 {year: {...}}；港股/美股无此拆分接口 → 返回 {}。
        - income: fin_exp_int_exp（利息费用）, fin_exp_int_inc（利息收入）
        - cashflow: use_right_asset_dep（使用权资产折旧）
        """
        if self.client._is_hk(self.ts_code) or self.client._is_us(self.ts_code):
            return {}
        out = {}
        try:
            inc = self.client._safe_call(
                "income", ts_code=self.ts_code, report_type="1",
                fields="end_date,report_type,fin_exp_int_exp,fin_exp_int_inc")
            for _, r in inc.iterrows():
                y = str(r["end_date"])[:4]
                if str(r["end_date"]).endswith("1231"):
                    out.setdefault(y, {})
                    out[y]["fin_exp_int_exp"] = self._sf(r.get("fin_exp_int_exp"))
                    out[y]["fin_exp_int_inc"] = self._sf(r.get("fin_exp_int_inc"))
        except Exception:
            pass
        try:
            cf = self.client._safe_call(
                "cashflow", ts_code=self.ts_code, report_type="1",
                fields="end_date,report_type,use_right_asset_dep")
            for _, r in cf.iterrows():
                y = str(r["end_date"])[:4]
                if str(r["end_date"]).endswith("1231"):
                    out.setdefault(y, {})
                    out[y]["use_right_asset_dep"] = self._sf(r.get("use_right_asset_dep"))
        except Exception:
            pass
        return out

    def _ebitda_from_store(self):
        """从 §12 fina_indicator 读 Tushare 官方 EBITDA（与 turtle §17.8 同源）。

        返回 {year: ebitda_raw}。
        """
        fi = self.client._store.get("fina_indicators")
        out = {}
        if fi is None or fi.empty or "ebitda" not in fi.columns:
            return out
        for _, r in fi.iterrows():
            y = str(r["end_date"])[:4]
            if str(r["end_date"]).endswith("1231") or str(r["end_date"])[4:6] == f"{self.client._fy_end_month:02d}":
                v = self._sf(r.get("ebitda"))
                if v is not None:
                    out[y] = v
        return out

    def _section_ebitda(self, cash_ctx: dict):
        income = self._annual_df("income")
        cf = self._annual_df("cashflow")
        if income.empty:
            return None, None
        inc_by = self._by_year(income)
        cf_by = self._by_year(cf)
        years = [str(r["end_date"])[:4] for _, r in income.iterrows()][:5]

        ebitda_ts = self._ebitda_from_store()       # Tushare 官方值（最终采用）
        comps = self._fetch_ebitda_components()      # 还原所需补充字段

        lines = [format_header(3, "2. EBITDA 与估值倍数"), ""]
        lines.append("> **EBITDA 采用 Tushare `fina_indicator.ebitda`（与 turtle §17.8 同源）**；下表为白盒还原，供对照财报复现。")
        lines.append("> 还原式 = 利润总额 + 利息净额(利息费用−利息收入) + 固定资产折旧 + 无形摊销 + 长期待摊摊销 + 使用权资产折旧。")
        lines.append(f"> 利润总额/利息 来自 §3 利润表，各类折旧摊销 来自 §5 现金流量表。单位 {self._unit()}。")
        lines.append("")

        hdr = ["行项 [来源]"] + years
        rows = []
        rows.append(self._raw_row("利润总额 total_profit [§3]", inc_by, "total_profit", years))

        # 利息净额 = fin_exp_int_exp − fin_exp_int_inc（来自补取字段）
        int_exp_row = ["利息费用 fin_exp_int_exp [§3]"]
        int_inc_row = ["利息收入 fin_exp_int_inc [§3]"]
        int_net_row = ["  利息净额 = 费用 − 收入"]
        int_net_by = {}
        for y in years:
            ie = comps.get(y, {}).get("fin_exp_int_exp")
            ii = comps.get(y, {}).get("fin_exp_int_inc")
            net = None
            if ie is not None or ii is not None:
                net = (ie or 0) - (ii or 0)
            int_net_by[y] = net
            int_exp_row.append(self._fmt(ie)); int_inc_row.append(self._fmt(ii))
            int_net_row.append(self._fmt(net))
        rows += [int_exp_row, int_inc_row, int_net_row]

        rows.append(self._raw_row("  固定资产折旧 depr_fa_coga_dpba [§5]", cf_by, "depr_fa_coga_dpba", years))
        rows.append(self._raw_row("  无形资产摊销 amort_intang_assets [§5]", cf_by, "amort_intang_assets", years))
        rows.append(self._raw_row("  长期待摊费用摊销 lt_amort_deferred_exp [§5]", cf_by, "lt_amort_deferred_exp", years))

        ura_row = ["  使用权资产折旧 use_right_asset_dep [§5]"]
        for y in years:
            ura_row.append(self._fmt(comps.get(y, {}).get("use_right_asset_dep")))
        rows.append(ura_row)

        # D&A 四项小计 + 还原 EBITDA + Tushare 官方 EBITDA
        da_row = ["= D&A 小计（固折+无摊+长摊+使用权折）"]
        recon_row = ["= 还原 EBITDA"]
        ts_row = ["= Tushare EBITDA（采用值）"]
        recon_by = {}
        for y in years:
            depr = self._sf(cf_by[y].get("depr_fa_coga_dpba")) if y in cf_by else None
            ai = self._sf(cf_by[y].get("amort_intang_assets")) if y in cf_by else None
            ad = self._sf(cf_by[y].get("lt_amort_deferred_exp")) if y in cf_by else None
            ura = comps.get(y, {}).get("use_right_asset_dep")
            da = sum(v for v in [depr, ai, ad, ura] if v is not None)
            tp = self._sf(inc_by[y].get("total_profit")) if y in inc_by else None
            net = int_net_by.get(y)
            recon = None
            if tp is not None:
                recon = tp + (net or 0) + da
            recon_by[y] = recon
            da_row.append(self._fmt(da))
            recon_row.append(self._fmt(recon))
            ts_row.append(self._fmt(ebitda_ts.get(y)))
        rows += [da_row, recon_row, ts_row]
        lines.append(format_table(hdr, rows, alignments=["l"] + ["r"] * len(years)))
        lines.append("")

        latest = years[0]
        # EBITDA 最终采用 Tushare 值；缺失时回退到还原值
        ebitda_latest = ebitda_ts.get(latest)
        ebitda_src = "Tushare fina_indicator"
        if ebitda_latest is None:
            ebitda_latest = recon_by.get(latest)
            ebitda_src = "还原式（Tushare 字段缺失，回退）"

        # 算式代入（最新年还原式）
        tp = self._sf(inc_by[latest].get("total_profit")) if latest in inc_by else None
        net = int_net_by.get(latest)
        depr = self._sf(cf_by[latest].get("depr_fa_coga_dpba")) if latest in cf_by else None
        ai = self._sf(cf_by[latest].get("amort_intang_assets")) if latest in cf_by else None
        ad = self._sf(cf_by[latest].get("lt_amort_deferred_exp")) if latest in cf_by else None
        ura = comps.get(latest, {}).get("use_right_asset_dep")
        if tp is not None:
            recon_l = recon_by.get(latest)
            lines.append(f"**{latest} 还原式代入**（{self._unit()}）：")
            lines.append("```")
            lines.append(f"EBITDA = 利润总额 + 利息净额 + 固折 + 无摊 + 长摊 + 使用权折")
            lines.append(f"       = {self._fmt(tp)} + ({self._fmt(net)}) + {self._fmt(depr)} + "
                         f"{self._fmt(ai)} + {self._fmt(ad)} + {self._fmt(ura)}")
            lines.append(f"       = {self._fmt(recon_l)}（还原）  vs  {self._fmt(ebitda_ts.get(latest))}（Tushare 采用）")
            lines.append("```")
            if ura is None and not (self.client._is_hk(self.ts_code) or self.client._is_us(self.ts_code)):
                lines.append("> ⚠️ 使用权资产折旧字段缺失，还原值可能偏低；EBITDA 仍采用 Tushare 官方值。")
            lines.append("")

        # 估值倍数（最新年）
        mc = self._market_cap()
        mkt = mc.get("mkt_cap_raw") if mc else None
        if mkt and cash_ctx and ebitda_latest and ebitda_latest != 0:
            net_cash = cash_ctx.get("narrow_latest") or 0   # 狭义（与 turtle §17.8 对齐）
            net_debt = -net_cash
            ev = mkt - net_cash
            lines.append(f"**估值倍数（{latest}，EV 用狭义净现金，与 turtle §17.8 对齐）**：")
            lines.append("")
            mult_rows = [
                [f"EBITDA（{self._unit()}）", self._fmt(ebitda_latest), f"来源：{ebitda_src}"],
                [f"企业价值 EV（{self._unit()}）", self._fmt(ev), "市值 − 狭义净现金"],
                ["EV/EBITDA", f"{ev / ebitda_latest:.2f}x", "—"],
                ["净负债/EBITDA", f"{net_debt / ebitda_latest:.2f}x", "(有息负债−货币资金)/EBITDA，负值=净现金"],
            ]
            lines.append(format_table(["指标", "值", "说明"], mult_rows,
                                      alignments=["l", "r", "l"]))

        return "\n".join(lines), ebitda_latest

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------

    def run(self) -> str:
        lines = [
            format_header(1, f"现金指标总表（白盒可复现）— {self.ts_code}"),
            "",
            f"*数据来源: Tushare Pro，原始行项标注 §N 对应 data_pack 板块；金额单位 {self._unit()}（除标注）*",
            f"*口径沿用龟龟因子3；每个数字均展示原始行项+算式，可对照财报复现*",
            "",
            "---",
            "",
        ]

        cash_md, cash_ctx = self._section_cash_debt()
        aa_md, aa_ctx = self._section_aa()
        ebitda_md, ebitda_latest = self._section_ebitda(cash_ctx)

        yr = (cash_ctx.get("latest_year") if cash_ctx else None) or \
             (aa_ctx.get("latest_year") if aa_ctx else "")

        # 参数速览（置顶，供填表）
        # 顺序：净利润、广义现金、狭义现金、有息负债合计、EBITDA、真实现金流(最近一年AA)、AA_2y、AA_all
        lines.append(format_header(2, "参数速览（供填表）"))
        lines.append("")
        summary_rows = []
        if aa_ctx and aa_ctx.get("np_latest") is not None:
            summary_rows.append([f"净利润（归母·{yr}）", self._fmt(aa_ctx.get("np_latest"))])
        if cash_ctx:
            summary_rows.append([f"广义现金（货币资金+交易性·{yr}）",
                                 self._fmt(cash_ctx.get("cash_broad_latest"))])
            summary_rows.append([f"狭义现金（货币资金·{yr}）",
                                 self._fmt(cash_ctx.get("cash_narrow_latest"))])
            summary_rows.append([f"有息负债合计（{yr}）",
                                 self._fmt(cash_ctx.get("ibd_latest"))])
            summary_rows.append([f"总负债（{yr}）",
                                 self._fmt(cash_ctx.get("total_liab_latest"))])
        if ebitda_latest is not None:
            summary_rows.append([f"EBITDA（{yr}）", self._fmt(ebitda_latest)])
        if aa_ctx:
            summary_rows.append([f"真实现金流（最近一年 AA·{yr}）", self._fmt(aa_ctx.get("aa_latest"))])
            summary_rows.append(["AA_2y（真金白银·近2年）", self._fmt(aa_ctx.get("aa_2y"))])
            summary_rows.append(["AA_all（真金白银·全部年）", self._fmt(aa_ctx.get("aa_all"))])
        if summary_rows:
            lines.append(format_table([f"参数（{self._unit()}）", "值"], summary_rows,
                                      alignments=["l", "r"]))
        lines.append("")
        lines.append("---")
        lines.append("")

        # 白盒明细：现金与负债 → EBITDA → 真金白银AA → 回收期 → 承诺/预期
        lines.append(format_header(2, "白盒明细"))
        lines.append("")

        if cash_md:
            lines.append(cash_md)
            lines.append("")
        if ebitda_md:
            lines.append(ebitda_md)
            lines.append("")
        if aa_md:
            lines.append(aa_md)
            lines.append("")

        payback_md = self._section_payback(cash_ctx, aa_ctx)
        if payback_md:
            lines.append(payback_md)
            lines.append("")

        # Phase 2 占位：承诺/预期分红回购
        lines.append(format_header(3, "5. 承诺值 / 预期值分红回购（待 Phase 2 读年报补充）"))
        lines.append("")
        lines.append("*[待 LLM 读年报『利润分配政策』与回购预案章节填入]*")
        lines.append("")
        lines.append("| 项目 | 承诺值 | 预期值 | 来源 |")
        lines.append("| --- | ---: | ---: | --- |")
        lines.append("| 分红政策（最低支付率/金额） | 待填 | 待填 | 年报利润分配政策 |")
        lines.append("| 回购金额（上限/区间） | 待填 | 待填 | 回购预案公告 |")
        lines.append("| 回购性质（注销型/激励型） | 待填 | — | 回购公告 |")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Cash metrics white-box engine")
    parser.add_argument("--code", required=True, help="Stock code (e.g., 600887)")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    ts_code = validate_stock_code(args.code)
    token = get_token()

    from tushare_collector import TushareClient

    print(f"[cash_metrics_engine] 正在采集 {ts_code} 数据...", file=sys.stderr)
    client = TushareClient(token)
    client.assemble_data_pack(ts_code)

    print(f"[cash_metrics_engine] 正在计算现金指标...", file=sys.stderr)
    engine = CashMetricsEngine(ts_code, args.output_dir, client)
    output_md = engine.run()

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "cash_metrics.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_md)

    print(f"[cash_metrics_engine] 完成: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
