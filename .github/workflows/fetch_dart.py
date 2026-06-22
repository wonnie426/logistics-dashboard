import os, json, requests, time
from datetime import datetime, date

API_KEY = os.environ.get("DART_API_KEY", "")

COMPANIES = {
    "롯데글로벌로지스": {"corp_code": "01388369", "color": "#C8102E", "short": "롯데"},
    "CJ대한통운":       {"corp_code": "00113526", "color": "#00A0DC", "short": "CJ"},
    "한진":             {"corp_code": "00102027", "color": "#003087", "short": "한진"},
}

ACCOUNT_TARGETS = {
    "매출액":           ["ifrs-full_Revenue", "dart_Revenue"],
    "영업이익":         ["ifrs-full_ProfitLossFromOperatingActivities", "dart_OperatingIncomeLoss"],
    "당기순이익":       ["ifrs-full_ProfitLoss", "dart_ProfitLoss"],
    "자산총계":         ["ifrs-full_Assets"],
    "부채총계":         ["ifrs-full_Liabilities"],
    "자본총계":         ["ifrs-full_Equity"],
    "유동자산":         ["ifrs-full_CurrentAssets"],
    "유동부채":         ["ifrs-full_CurrentLiabilities"],
    "현금및현금성자산": ["ifrs-full_CashAndCashEquivalents"],
    "영업활동현금흐름": ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
}

BASE_URL = "https://opendart.fss.or.kr/api"

def get_recent_reports(corp_code):
    reports = []
    current_year = date.today().year
    for year in range(current_year - 2, current_year + 1):
        for rtype in ["A", "B", "C", "D"]:
            params = {
                "crtfc_key": API_KEY, "corp_code": corp_code,
                "bgn_de": f"{year}0101", "end_de": f"{year}1231",
                "pblntf_ty": rtype, "sort": "rd", "sort_mth": "desc", "page_count": 5
            }
            try:
                r = requests.get(f"{BASE_URL}/list.json", params=params, timeout=15)
                data = r.json()
                if data.get("status") == "000" and data.get("list"):
                    for item in data["list"]:
                        if any(k in item.get("report_nm","") for k in ["사업보고서","반기보고서","분기보고서"]):
                            reports.append(item)
            except Exception as e:
                print(f"  목록 조회 실패: {e}")
            time.sleep(0.3)
    seen, unique = set(), []
    for r in reports:
        k = r.get("rcept_no","")
        if k not in seen:
            seen.add(k); unique.append(r)
    return unique[:8]

def get_fs(corp_code, year, reprt_code):
    for fs_div in ["CFS", "OFS"]:
        params = {"crtfc_key": API_KEY, "corp_code": corp_code,
                  "bsns_year": year, "reprt_code": reprt_code, "fs_div": fs_div}
        try:
            r = requests.get(f"{BASE_URL}/fnlttSinglAcntAll.json", params=params, timeout=15)
            data = r.json()
            if data.get("status") == "000" and data.get("list"):
                return data["list"]
        except: pass
        time.sleep(0.4)
    return []

def extract(fs_list, targets):
    for item in fs_list:
        for t in targets:
            if t in item.get("account_id","") or t in item.get("account_nm",""):
                raw = item.get("thstrm_amount","").replace(",","")
                try: return int(raw)
                except: pass
    return None

def calc_ratios(a):
    def pct(x, y):
        return round(x/y*100, 2) if x and y else None
    r = {}
    r["영업이익률"]       = pct(a.get("영업이익"), a.get("매출액"))
    r["순이익률"]         = pct(a.get("당기순이익"), a.get("매출액"))
    r["ROA"]              = pct(a.get("당기순이익"), a.get("자산총계"))
    r["ROE"]              = pct(a.get("당기순이익"), a.get("자본총계"))
    r["부채비율"]         = pct(a.get("부채총계"), a.get("자본총계"))
    r["유동비율"]         = pct(a.get("유동자산"), a.get("유동부채"))
    if a.get("자산총계") and a.get("부채총계"):
        r["자기자본비율"] = round((a["자산총계"]-a["부채총계"])/a["자산총계"]*100, 2)
    r["영업현금흐름_매출비"] = pct(a.get("영업활동현금흐름"), a.get("매출액"))
    return {k:v for k,v in r.items() if v is not None}

def reprt_code(nm):
    if "사업보고서" in nm: return "11011"
    if "반기보고서" in nm: return "11012"
    if "1분기" in nm: return "11013"
    if "3분기" in nm: return "11014"
    return "11011"

def period_label(nm, dt):
    y = dt[:4]
    if "사업보고서" in nm: return f"{y}년 연간"
    if "반기보고서" in nm: return f"{y}년 상반기"
    if "1분기" in nm: return f"{y}년 1분기"
    if "3분기" in nm: return f"{y}년 3분기"
    return y

def main():
    if not API_KEY:
        print("ERROR: DART_API_KEY 없음"); raise SystemExit(1)
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at_kst": datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분"),
        "companies": {}
    }
    for name, info in COMPANIES.items():
        print(f"\n수집 중: {name}")
        company = {"name": name, "short": info["short"],
                   "color": info["color"], "corp_code": info["corp_code"], "periods": []}
        for rpt in get_recent_reports(info["corp_code"])[:6]:
            nm = rpt.get("report_nm","")
            dt = rpt.get("rcept_dt","")
            rcno = rpt.get("rcept_no","")
            print(f"  → {nm} ({dt})")
            fs = get_fs(info["corp_code"], dt[:4], reprt_code(nm))
            accs = {k: extract(fs, v) for k,v in ACCOUNT_TARGETS.items()}
            accs = {k:v for k,v in accs.items() if v is not None}
            company["periods"].append({
                "label": period_label(nm, dt),
                "report_nm": nm, "rcept_no": rcno, "rcept_dt": dt,
                "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcno}",
                "accounts": accs,
                "ratios": calc_ratios(accs)
            })
        result["companies"][name] = company
        time.sleep(1)
    os.makedirs("data", exist_ok=True)
    with open("data/financial_data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n완료: data/financial_data.json 저장")

if __name__ == "__main__":
    main()
