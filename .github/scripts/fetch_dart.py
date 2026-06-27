#!/usr/bin/env python3
"""
DART API로 롯데글로벌로지스, CJ대한통운, 한진의 재무제표를 수집해
data/financial_data.json을 갱신한다.

실행: python fetch_dart.py --api-key <DART_API_KEY>
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── 상수 ────────────────────────────────────────────────────────────────────
BASE_URL = "https://opendart.fss.or.kr/api"
KST = timezone(timedelta(hours=9))

COMPANIES = {
    "LGL": {"corp_code": "00207676", "name": "롯데글로벌로지스", "color": "#C8102E", "listed": False,
            "stock_type": "kotc", "stock_code": "040830"},
    "CJ":  {"corp_code": "00113410", "name": "CJ대한통운",       "color": "#00A0DC", "listed": True,
            "stock_type": "krx",  "stock_code": "000120"},
    "HJ":  {"corp_code": "00163512", "name": "한진",             "color": "#003087", "listed": True,
            "stock_type": "krx",  "stock_code": "002320"},
}

# 기간별 종가 기준일 (최근 거래일 기준)
PERIOD_END_DATES = {
    "annual": {
        "2021": "20211230", "2022": "20221229", "2023": "20231228",
        "2024": "20241230", "2025": "20251230", "2026": "20261231",
    },
    "Q1": {"2023": "20230331", "2024": "20240329", "2025": "20250331", "2026": "20260331"},
    "Q2": {"2023": "20230630", "2024": "20240628", "2025": "20250630", "2026": "20260630"},
    "Q3": {"2023": "20230929", "2024": "20240930", "2025": "20250930", "2026": "20260930"},
}

REPORT_CODES = {
    "annual": "11011",
    "Q2":     "11012",
    "Q1":     "11013",
    "Q3":     "11014",
}

COLLECT_YEARS = ["2021", "2022", "2023", "2024", "2025", "2026"]

# ── 주가 수집 ──────────────────────────────────────────────────────────────
def fetch_naver_prices(symbol: str) -> dict:
    """네이버 금융에서 KRX 종목 일별 종가 {YYYYMMDD: price} 반환"""
    url = (f"https://fchart.stock.naver.com/sise.nhn"
           f"?symbol={symbol}&timeframe=day&count=2000&requestType=0")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        prices = {}
        # XML 형식: <item data="YYYYMMDD|open|high|low|close|volume" />
        for m in re.finditer(r'data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|(\d+)\|', r.text):
            date, close = m.group(1), m.group(2)
            if close and close != '0':
                prices[date] = int(close)
        return prices
    except Exception as e:
        print(f"  주가 수집 실패 ({symbol}): {e}")
        return {}


def fetch_kotc_prices(code: str) -> dict:
    """38.co.kr에서 K-OTC 종목 일별 종가 {YYYYMMDD: price} 반환"""
    url = f"https://www.38.co.kr/html/forum/board/?code={code}&o=kotc_sise"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.encoding = 'euc-kr'
        prices = {}
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL | re.IGNORECASE)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) >= 5:
                date_text = re.sub(r'<[^>]+>', '', cells[0]).strip()
                price_text = re.sub(r'<[^>]+>', '', cells[4]).strip().replace(',', '')
                if re.match(r'\d{4}\.\d{2}\.\d{2}', date_text):
                    date_key = date_text.replace('.', '')
                    try:
                        prices[date_key] = int(price_text)
                    except ValueError:
                        pass
        return prices
    except Exception as e:
        print(f"  K-OTC 주가 수집 실패 ({code}): {e}")
        return {}


def get_period_end_price(prices: dict, target_date: str):
    """기준일 이전 가장 가까운 거래일 종가 반환"""
    if not prices:
        return None
    candidates = sorted([d for d in prices if d <= target_date], reverse=True)
    return prices[candidates[0]] if candidates else None


def collect_stock_prices(info: dict) -> dict:
    """회사의 모든 기간말 주가 수집 {annual_2023: price, 2023Q1: price, ...}"""
    stype = info.get("stock_type")
    code  = info.get("stock_code")
    if not code:
        return {}

    print(f"  주가 수집 중 ({stype}: {code})")
    if stype == "krx":
        prices = fetch_naver_prices(code)
    else:
        prices = fetch_kotc_prices(code)

    if not prices:
        return {}

    result = {}
    for year, date in PERIOD_END_DATES["annual"].items():
        p = get_period_end_price(prices, date)
        if p:
            result[f"annual_{year}"] = p

    for q in ["Q1", "Q2", "Q3"]:
        for year, date in PERIOD_END_DATES[q].items():
            p = get_period_end_price(prices, date)
            if p:
                result[f"{year}{q}"] = p

    return result


# ── 기업정보 수집 ────────────────────────────────────────────────────────────
def fetch_company_info(corp_code: str, api_key: str) -> dict:
    """DART에서 기업 기본정보 수집"""
    data = dart_get("company.json", {"corp_code": corp_code}, api_key)
    if not data:
        return {}
    return {
        "ceo":          data.get("ceo_nm", ""),
        "established":  data.get("est_dt", ""),
        "employees":    None,
        "industry":     data.get("induty_code", ""),
        "address":      data.get("adres", ""),
        "homepage":     data.get("hm_url", ""),
        "phone":        data.get("phn_no", ""),
        "fiscal_month": data.get("acc_mt", ""),
        "auditor":      data.get("auditor_nm", ""),
    }


# ── DART API 헬퍼 ──────────────────────────────────────────────────────────
def dart_get(endpoint: str, params: dict, api_key: str) -> dict | None:
    params["crtfc_key"] = api_key
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "000":
            return data
        print(f"  DART API 오류 {data.get('status')}: {data.get('message')} | params={params}")
        return None
    except Exception as e:
        print(f"  요청 실패: {e} | endpoint={endpoint} params={params}")
        return None


def fetch_disclosures(corp_code: str, api_key: str, days: int = 730) -> list:
    """최근 공시목록 수집 (최대 100건, 기본 2년치)"""
    from datetime import date, timedelta
    bgn = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    data = dart_get("list.json", {
        "corp_code": corp_code,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": 1,
        "page_count": 100,
        "sort": "date",
        "sort_mth": "desc",
    }, api_key)
    if not data:
        return []
    items = data.get("list", [])
    return [{
        "rcept_no":  d["rcept_no"],
        "rcept_dt":  d["rcept_dt"],
        "report_nm": d["report_nm"],
        "corp_name": d["corp_name"],
        "flr_nm":    d["flr_nm"],
        "rm":        d.get("rm", ""),
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}",
    } for d in items[:100]]


def fetch_report_list(corp_code: str, api_key: str, year: str, reprt_code: str) -> dict | None:
    data = dart_get("list.json", {
        "corp_code": corp_code,
        "bgn_de": f"{year}0101",
        "end_de": f"{int(year)+1}0630",
        "pblntf_ty": "A",
    }, api_key)
    if not data or "list" not in data:
        return None
    type_map = {"11011": "사업보고서", "11012": "반기보고서", "11013": "분기보고서", "11014": "분기보고서"}
    target_name = type_map.get(reprt_code, "")
    for item in data["list"]:
        if target_name in item.get("report_nm", ""):
            return {
                "rcept_no": item["rcept_no"],
                "rcept_dt": item["rcept_dt"],
                "report_nm": item["report_nm"],
                "report_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
            }
    return None


def fetch_accounts(corp_code: str, api_key: str, year: str, reprt_code: str):
    for fs_div in ("CFS", "OFS"):
        data = dart_get("fnlttSinglAcntAll.json", {
            "corp_code": corp_code,
            "bsns_year": year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }, api_key)
        if data and data.get("list"):
            return data["list"], fs_div
    return None, None


def fetch_accounts_both(corp_code: str, api_key: str, year: str, reprt_code: str):
    result = {}
    for fs_div in ("CFS", "OFS"):
        data = dart_get("fnlttSinglAcntAll.json", {
            "corp_code": corp_code,
            "bsns_year": year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }, api_key)
        if data and data.get("list"):
            result[fs_div] = data["list"]
    return result


# ── 계정명 → 값 매핑 ──────────────────────────────────────────────────────
def find_account(accounts: list, *names: str, sj_filter: str = None) -> int | None:
    pool = [a for a in accounts if sj_filter is None or a.get("sj_div") == sj_filter]
    # 1차: 정확히 일치
    for name in names:
        for acc in pool:
            if acc.get("account_nm", "").strip() == name:
                val = acc.get("thstrm_amount", "").replace(",", "").replace(" ", "")
                if val and val not in ("", "-", "－"):
                    try:
                        return int(val)
                    except ValueError:
                        pass
    # 2차: 포함 일치 (긴 이름 먼저, BS/IS만 허용)
    if sj_filter in ("BS", "IS", "CIS", None):
        for name in sorted(names, key=len, reverse=True):
            for acc in pool:
                nm = acc.get("account_nm", "").strip()
                if name in nm or nm in name:
                    val = acc.get("thstrm_amount", "").replace(",", "").replace(" ", "")
                    if val and val not in ("", "-", "－"):
                        try:
                            return int(val)
                        except ValueError:
                            pass
    return None


def parse_bs(accounts: list) -> dict:
    bs = "BS"
    return {
        "total_assets":            find_account(accounts, "자산총계", sj_filter=bs),
        "current_assets":          find_account(accounts, "유동자산", sj_filter=bs),
        "non_current_assets":      find_account(accounts, "비유동자산", sj_filter=bs),
        "total_liabilities":       find_account(accounts, "부채총계", sj_filter=bs),
        "current_liabilities":     find_account(accounts, "유동부채", sj_filter=bs),
        "non_current_liabilities": find_account(accounts, "비유동부채", sj_filter=bs),
        "total_equity":            find_account(accounts, "자본총계", sj_filter=bs),
        "controlling_equity":      find_account(accounts,
                                               "지배기업의 소유주에게 귀속되는 자본",
                                               "지배기업 소유주지분", "지배기업소유주지분",
                                               "지배주주지분", "지배기업주주지분",
                                               "지배기업 소유주에게 귀속되는 자본",
                                               sj_filter=bs),
        "cash_and_equivalents":    find_account(accounts, "현금및현금성자산", sj_filter=bs),
        "trade_receivables":       find_account(accounts, "매출채권", "매출채권 및 기타채권", sj_filter=bs),
        "inventory":               find_account(accounts, "재고자산", sj_filter=bs),
        "short_term_borrowings":   find_account(accounts, "단기차입금", sj_filter=bs),
        "current_portion_lt_debt": find_account(accounts, "유동성장기부채", "유동성 장기차입금", sj_filter=bs),
        "long_term_borrowings":    find_account(accounts, "장기차입금", sj_filter=bs),
        "bonds_payable":           find_account(accounts, "사채", sj_filter=bs),
        "lease_liabilities":       find_account(accounts, "리스부채", sj_filter=bs),
    }


def parse_pl(accounts: list) -> dict:
    def pl_find(*names):
        # IS 우선, 없으면 CIS에서 찾기
        return (find_account(accounts, *names, sj_filter="IS") or
                find_account(accounts, *names, sj_filter="CIS"))
    return {
        "revenue":                pl_find("매출액", "영업수익", "수익(매출액)",
                                          "이익(매출액)", "영업수익(매출액)"),
        "cost_of_revenue":        pl_find("매출원가", "영업비용"),
        "gross_profit":           pl_find("매출총이익", "매출총손익"),
        "sga":                    pl_find("판매비와관리비", "판매비및관리비", "판매비와 관리비"),
        "operating_income":       pl_find("영업이익", "영업이익(손실)", "영업손익"),
        "interest_expense":       pl_find("이자비용", "금융원가", "금융비용",
                                          "이자비용(금융원가)", "이자비용 등"),
        "net_income":             pl_find("당기순이익", "당기순이익(손실)", "당기순손익"),
        "controlling_net_income": pl_find("지배기업 소유주 귀속 당기순이익",
                                          "지배기업의 소유주에게 귀속되는 당기순이익",
                                          "지배기업의 소유주에게 귀속되는 당기순이익(손실)",
                                          "지배기업 소유주지분 당기순이익",
                                          "지배기업 소유주에게 귀속되는 당기순이익",
                                          "지배주주귀속 당기순이익"),
        "depreciation":           pl_find("감가상각비", "유형자산감가상각비",
                                          "감가상각 및 상각비"),
    }


def parse_cf(accounts: list) -> dict:
    return {
        "operating_cf":  find_account(accounts, "영업활동현금흐름", "영업활동으로 인한 현금흐름"),
        "investing_cf":  find_account(accounts, "투자활동현금흐름", "투자활동으로 인한 현금흐름"),
        "financing_cf":  find_account(accounts, "재무활동현금흐름", "재무활동으로 인한 현금흐름"),
        "interest_paid": find_account(accounts, "이자의 지급", "이자지급", "이자비용 지급"),
    }


# ── 재무비율 계산 ──────────────────────────────────────────────────────────
def safe_div(a, b, pct=False, decimals=2):
    if a is None or b is None or b == 0:
        return None
    result = a / b
    if pct:
        result *= 100
    return round(result, decimals)


def calc_ratios(bs: dict, pl: dict, cf: dict) -> dict:
    rev = pl.get("revenue")
    op  = pl.get("operating_income")
    ni  = pl.get("net_income")
    cni = pl.get("controlling_net_income")
    dep = pl.get("depreciation")
    ie  = pl.get("interest_expense") or (abs(cf.get("interest_paid")) if cf.get("interest_paid") else None)
    ta  = bs.get("total_assets")
    tl  = bs.get("total_liabilities")
    eq  = bs.get("total_equity")
    ceq = bs.get("controlling_equity")
    ca  = bs.get("current_assets")
    cl  = bs.get("current_liabilities")
    ll  = bs.get("lease_liabilities")
    ocf = cf.get("operating_cf")

    ebitda = (op + dep) if (op is not None and dep is not None) else None

    borrows = [bs.get("short_term_borrowings"), bs.get("current_portion_lt_debt"),
               bs.get("long_term_borrowings"), bs.get("bonds_payable")]
    total_debt = sum(b for b in borrows if b is not None) if any(b is not None for b in borrows) else None
    total_debt_with_lease = (total_debt + ll) if (total_debt is not None and ll is not None) else total_debt

    # controlling_equity 없으면 total_equity로 대체 (지배주주 100%인 경우 등)
    roe_equity = ceq if ceq else eq
    roe_income = cni if cni is not None else ni

    return {
        "gross_margin":         safe_div(pl.get("gross_profit"), rev, pct=True),
        "operating_margin":     safe_div(op, rev, pct=True),
        "ebitda_margin":        safe_div(ebitda, rev, pct=True),
        "net_margin":           safe_div(ni, rev, pct=True),
        "roa":                  safe_div(ni, ta, pct=True),
        "roe":                  safe_div(roe_income, roe_equity, pct=True),
        "debt_ratio":           safe_div(tl, eq, pct=True),
        "debt_ratio_ex_lease":  safe_div((tl - ll) if (tl and ll) else tl, eq, pct=True),
        "current_ratio":        safe_div(ca, cl, pct=True),
        "equity_ratio":         safe_div(eq, ta, pct=True),
        "borrowing_dependency": safe_div(total_debt_with_lease, ta, pct=True),
        "interest_coverage":    safe_div(op, ie, decimals=2),
        "operating_cf_margin":  safe_div(ocf, rev, pct=True),
    }


# ── 메인 수집 로직 ──────────────────────────────────────────────────────────
def build_period_data(accounts: list, fs_div: str, year: str,
                      period_key: str, report_info: dict | None) -> dict:
    bs = parse_bs(accounts)
    pl = parse_pl(accounts)
    cf = parse_cf(accounts)
    ratios = calc_ratios(bs, pl, cf)
    period_label = {"annual": "사업보고서", "Q1": "1분기보고서",
                    "Q2": "반기보고서", "Q3": "3분기보고서"}.get(period_key, "")
    fs_label = "연결" if fs_div == "CFS" else "별도"
    return {
        "source": f"{year}년 {period_label} ({fs_label}기준)",
        "report_type": period_label,
        "filing_date": report_info["rcept_dt"] if report_info else None,
        "report_url":  report_info["report_url"] if report_info else None,
        "bs": bs, "pl": pl, "cf": cf, "ratios": ratios,
        "market": {
            "stock_price": None, "shares_outstanding": None, "market_cap": None,
            "eps": None, "bps": None, "per": None, "pbr": None, "ev_ebitda": None
        },
    }


def collect_period(corp_code: str, api_key: str, year: str,
                   period_key: str, reprt_code: str) -> dict | None:
    print(f"    수집 중: {year} {period_key} (reprt_code={reprt_code})")

    report_info = fetch_report_list(corp_code, api_key, year, reprt_code)
    both = fetch_accounts_both(corp_code, api_key, year, reprt_code)

    if not both:
        print(f"    → 데이터 없음 (미공시)")
        return None

    result = {}
    for fs_div, accounts in both.items():
        result[fs_div] = build_period_data(accounts, fs_div, year, period_key, report_info)

    # 기본(default) 기준: CFS 우선
    result["_default"] = "CFS" if "CFS" in result else "OFS"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", required=True, help="DART API 키")
    parser.add_argument("--data-dir", default="data", help="data/ 디렉토리 경로")
    args = parser.parse_args()

    api_key = args.api_key
    data_dir = Path(args.data_dir)
    fin_path = data_dir / "financial_data.json"

    if fin_path.exists():
        with open(fin_path, "r", encoding="utf-8") as f:
            output = json.load(f)
    else:
        output = {"companies": {k: {"annual": {}, "quarterly": {}} for k in COMPANIES}}

    output["last_updated"] = datetime.now(KST).isoformat()
    latest_report = {}

    for code, info in COMPANIES.items():
        corp_code = info["corp_code"]
        print(f"\n[{code}] {info['name']} 수집 시작")

        co_data = output["companies"].setdefault(code, {})
        co_data.update({
            "name": info["name"], "color": info["color"],
            "corp_code": corp_code, "listed": info["listed"],
            "stock_code": info.get("stock_code"), "stock_type": info.get("stock_type"),
        })
        co_data.setdefault("annual", {})
        co_data.setdefault("quarterly", {})

        # 기업정보 수집
        print(f"  기업정보 수집 중...")
        co_data["info"] = fetch_company_info(corp_code, api_key)

        # 공시목록 수집
        print(f"  공시목록 수집 중...")
        co_data["disclosures"] = fetch_disclosures(corp_code, api_key)

        # 주가 수집
        stock_prices = collect_stock_prices(info)
        co_data["stock_prices"] = stock_prices

        for year in COLLECT_YEARS:
            result = collect_period(corp_code, api_key, year, "annual", REPORT_CODES["annual"])
            if result:
                co_data["annual"][year] = result
                if code not in latest_report or year > latest_report[code].get("year", ""):
                    ref = result.get("CFS") or result.get("OFS") or {}
                    latest_report[code] = {
                        "year": year, "period": "annual",
                        "report_type": ref.get("report_type", ""),
                        "filing_date": ref.get("filing_date"),
                        "report_url": ref.get("report_url"),
                    }

        quarters = [
            ("Q1", REPORT_CODES["Q1"]),
            ("Q2", REPORT_CODES["Q2"]),
            ("Q3", REPORT_CODES["Q3"]),
        ]
        for year in ["2023", "2024", "2025", "2026"]:
            for q_key, reprt_code in quarters:
                period_key = f"{year}{q_key}"
                result = collect_period(corp_code, api_key, year, q_key, reprt_code)
                if result:
                    co_data["quarterly"][period_key] = result

    output["latest_report"] = latest_report

    with open(fin_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {fin_path}")


if __name__ == "__main__":
    main()
