#!/usr/bin/env python3
"""
LGL 2021/2022 연간 재무제표 라인 항목을 statements.json에 추가하는 패치 스크립트.
VM(등록 IP)에서 실행:
  python3 patch_lgl_statements.py --api-key <DART_API_KEY>
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

BASE_URL = "https://opendart.fss.or.kr/api"
LGL_CORP_CODE = "00207676"
TARGET_YEARS = ["2021", "2022"]
ANNUAL_REPRT_CODE = "11011"
STMT_DIVS = ["BS", "IS", "CIS", "CF", "SCE"]


def dart_get(endpoint, params, api_key):
    params["crtfc_key"] = api_key
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "000":
        return data
    print(f"  DART API 오류 {data.get('status')}: {data.get('message')}")
    return None


def _amt_to_int(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-", "－"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def parse_statements(accounts):
    def ord_key(a):
        try:
            return int(str(a.get("ord", "0")).strip() or "0")
        except ValueError:
            return 0

    out = {}
    for div in STMT_DIVS:
        rows = sorted([a for a in accounts if a.get("sj_div") == div], key=ord_key)
        items = []
        seen = set()
        for a in rows:
            nm = (a.get("account_nm") or "").strip()
            if not nm:
                continue
            detail = (a.get("account_detail") or "").strip()
            detail = re.sub(r"\s*\[(member|구성요소)\]", "", detail, flags=re.I).strip()
            if "|" in detail:
                detail = detail.split("|")[-1].strip()
            if detail in ("연결재무제표", "재무제표", "자본"):
                detail = "합계"
            label = nm if (div != "SCE" or detail in ("", "-", "－")) else f"{nm} ({detail})"
            key = (label,)
            if key in seen:
                continue
            seen.add(key)
            items.append({"l": label, "v": _amt_to_int(a.get("thstrm_amount"))})
        if items:
            out[div] = items
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    api_key = args.api_key
    stmt_path = Path(args.data_dir) / "statements.json"

    if stmt_path.exists():
        with open(stmt_path, "r", encoding="utf-8") as f:
            stmt_out = json.load(f)
    else:
        stmt_out = {}

    for year in TARGET_YEARS:
        print(f"\n[LGL] {year} 연간 수집 중...")
        for fs_div in ("CFS", "OFS"):
            data = dart_get("fnlttSinglAcntAll.json", {
                "corp_code": LGL_CORP_CODE,
                "bsns_year": year,
                "reprt_code": ANNUAL_REPRT_CODE,
                "fs_div": fs_div,
            }, api_key)
            if not data or not data.get("list"):
                print(f"  {fs_div}: 데이터 없음 (미공시)")
                continue
            accounts = data["list"]
            stmts = parse_statements(accounts)
            if stmts:
                (stmt_out.setdefault("LGL", {})
                         .setdefault(fs_div, {})
                         .setdefault("annual", {})[year]) = stmts
                print(f"  {fs_div}: {sum(len(v) for v in stmts.values())}개 항목 수집 완료")
            else:
                print(f"  {fs_div}: 파싱 결과 없음")

    with open(stmt_path, "w", encoding="utf-8") as f:
        json.dump(stmt_out, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {stmt_path}")


if __name__ == "__main__":
    main()
