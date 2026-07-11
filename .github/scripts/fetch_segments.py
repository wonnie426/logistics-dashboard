#!/usr/bin/env python3
"""
DART 분기/사업보고서에서 사업부문별 실적을 자동 파싱해 segment_data.json을 업데이트한다.

파싱 신뢰도 기준:
  CONFIDENT  → segment_data.json 자동 업데이트 후 커밋
  UNCERTAIN  → 파싱은 됐지만 검증 실패 → GitHub Issue 생성 (수동 확인 요청)
  FAILED     → 테이블을 아예 못 찾음 → GitHub Issue 생성

실행 예시:
  python fetch_segments.py \\
    --api-key $DART_API_KEY \\
    --github-token $GITHUB_TOKEN \\
    --repo wonnie426/logistics-dashboard

Claude 없이 유지보수 시:
  - 각 회사 설정은 SEGMENT_CONFIG 딕셔너리만 수정하면 됨
  - 부문명이 바뀌면 해당 회사 segment_aliases 리스트에 추가
  - 단위(unit)는 천원=1000, 백만원=1000000
  - 신뢰도 임계값은 CONFIDENCE_THRESHOLD 상수 조정
"""

import argparse
import json
import logging
import os
import re
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

import requests
from html.parser import HTMLParser

# ─────────────────────────────────────────────────────────────────────────────
# 상수 및 설정
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://opendart.fss.or.kr/api"
KST = timezone(timedelta(hours=9))
CONFIDENCE_THRESHOLD = 0.75   # 이 값 이상이면 자동 업데이트

# 회사별 파싱 설정 — 부문명/키워드가 바뀌면 여기만 수정
SEGMENT_CONFIG = {
    "LGL": {
        "corp_code": "01388369",
        "name": "롯데글로벌로지스",
        "note_keywords": ["영업부문정보", "영업부문", "부문별 영업실적"],
        "segments": {
            "TLS": {
                "aliases": ["TLS", "T.L.S", "TLS부문", "계약물류", "운송"],
                "priority": 1,
            },
            "Lastmile": {
                "aliases": ["Lastmile", "라스트마일", "택배", "Last Mile", "라스트 마일"],
                "priority": 2,
            },
            "GBS": {
                "aliases": ["GBS", "G.B.S", "GBS부문", "글로벌"],
                "priority": 3,
            },
        },
        "unit": 1000,          # 천원 → 원
        "unit_label": "천원",
        "revenue_row_aliases": [
            "외부고객으로부터의 수익", "외부고객수익", "총부문수익",
            "수익", "매출액", "외부고객으로부터의 매출액",
        ],
        "op_income_row_aliases": [
            "보고부문영업이익", "영업이익", "세그먼트이익", "영업이익(손실)",
        ],
        "fs_div": "CFS",
    },
    "CJ": {
        "corp_code": "00113526",
        "name": "CJ대한통운",
        "note_keywords": ["영업부문정보", "영업부문", "사업부문"],
        "segments": {
            "CL": {
                "aliases": ["CL", "계약물류", "CL부문", "Contract Logistics"],
                "priority": 1,
            },
            "택배": {
                "aliases": ["택배", "Parcel", "택배부문"],
                "priority": 2,
            },
            "글로벌": {
                "aliases": ["글로벌", "Global", "글로벌부문", "해외"],
                "priority": 3,
            },
            "건설": {
                "aliases": ["건설", "Construction", "건설부문"],
                "priority": 4,
            },
        },
        "unit": 1000,
        "unit_label": "천원",
        "revenue_row_aliases": [
            "순매출액", "외부고객으로부터의 매출액", "매출액",
            "외부매출액", "수익", "외부고객수익",
        ],
        "op_income_row_aliases": [
            "영업이익", "영업이익(손실)", "세그먼트이익",
        ],
        "fs_div": "CFS",
    },
    "HJ": {
        "corp_code": "00102027",
        "name": "한진",
        "note_keywords": ["영업부문정보", "영업부문", "부문별 영업손익"],
        "segments": {
            "물류": {
                "aliases": ["물류", "Logistics", "물류부문"],
                "priority": 1,
            },
            "택배": {
                "aliases": ["택배", "Express", "택배부문"],
                "priority": 2,
            },
            "글로벌": {
                "aliases": ["글로벌", "Global", "글로벌부문", "해운", "국제"],
                "priority": 3,
            },
            "에너지": {
                "aliases": ["에너지", "Energy", "에너지부문"],
                "priority": 4,
            },
        },
        "unit": 1000000,       # 백만원 → 원
        "unit_label": "백만원",
        "revenue_row_aliases": [
            "수익", "매출액", "외부매출액", "외부고객으로부터의 수익",
            "외부고객매출액", "외부고객 매출액",
        ],
        "op_income_row_aliases": [
            "영업이익", "영업손익", "영업이익(손실)",
        ],
        "fs_div": "CFS",
    },
    "HGL": {
        "corp_code": "00164742",
        "name": "현대글로비스",
        "note_keywords": ["영업부문정보", "영업부문", "사업부문별 정보", "부문별 영업실적"],
        "segments": {
            "물류사업": {
                "aliases": ["물류사업", "물류", "Logistics", "물류부문", "완성차물류"],
                "priority": 1,
            },
            "유통사업": {
                "aliases": ["유통사업", "유통", "Distribution", "유통부문"],
                "priority": 2,
            },
            "해운사업": {
                "aliases": ["해운사업", "해운", "Shipping", "해운부문", "선박"],
                "priority": 3,
            },
        },
        "unit": 1000000,       # 백만원 → 원
        "unit_label": "백만원",
        "revenue_row_aliases": [
            "수익", "매출액", "외부매출액", "외부고객으로부터의 수익",
            "외부고객매출액", "외부고객 매출액",
        ],
        "op_income_row_aliases": [
            "영업이익", "영업손익", "영업이익(손실)",
        ],
        "fs_div": "CFS",
    },
}

REPORT_CODE_MAP = {
    "11011": ("annual",     "사업보고서"),
    "11012": ("quarterly",  "반기보고서",    "Q2"),
    "11013": ("quarterly",  "1분기보고서",   "Q1"),
    "11014": ("quarterly",  "3분기보고서",   "Q3"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DART API 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def dart_get(endpoint: str, params: dict, api_key: str) -> dict | None:
    params = {**params, "crtfc_key": api_key}
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "000":
            return data
        log.warning("DART status %s: %s", data.get("status"), data.get("message"))
        return None
    except Exception as e:
        log.error("DART GET 실패 [%s]: %s", endpoint, e)
        return None


def find_latest_report(corp_code: str, api_key: str, reprt_code: str, bsns_year: str) -> dict | None:
    """해당 연도의 최신 보고서 접수번호 반환."""
    data = dart_get("list.json", {
        "corp_code": corp_code,
        "bgn_de": f"{bsns_year}0101",
        "end_de": f"{int(bsns_year) + 1}0630",
        "pblntf_ty": "A",
    }, api_key)
    if not data or "list" not in data:
        return None

    code_to_name = {"11011": "사업보고서", "11012": "반기보고서",
                    "11013": "분기보고서", "11014": "분기보고서"}
    target = code_to_name.get(reprt_code, "")
    for item in sorted(data["list"], key=lambda x: x.get("rcept_dt", ""), reverse=True):
        if target in item.get("report_nm", ""):
            return {
                "rcept_no": item["rcept_no"],
                "rcept_dt": item["rcept_dt"],
                "report_nm": item["report_nm"],
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
            }
    return None


def download_document_html(rcept_no: str, api_key: str) -> list[tuple[str, str]]:
    """
    DART document.xml 에서 zip 다운로드 후 HTML 파일 목록 반환.
    반환: [(파일명, html문자열), ...]  크기 내림차순
    """
    url = f"{BASE_URL}/document.xml"
    params = {"rcept_no": rcept_no, "crtfc_key": api_key}
    try:
        r = requests.get(url, params=params, timeout=60, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "xml" in content_type or "json" in content_type:
            # API 오류 응답
            log.warning("document.xml이 zip이 아님: %s", content_type)
            return []
        buf = BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            html_files = [
                (name, zf.read(name).decode("utf-8", errors="replace"))
                for name in zf.namelist()
                if name.lower().endswith((".htm", ".html", ".xml"))
            ]
        # 크기 큰 파일(본문일 가능성 높음) 순서로
        html_files.sort(key=lambda x: len(x[1]), reverse=True)
        log.info("  다운로드 성공: zip 내 HTML %d개", len(html_files))
        return html_files
    except Exception as e:
        log.error("  document 다운로드 실패: %s", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# HTML 테이블 파서
# ─────────────────────────────────────────────────────────────────────────────

class TableExtractor(HTMLParser):
    """HTML에서 테이블을 2D 리스트로 추출."""
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self._in_cell = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._current_table = []
        elif tag in ("tr",):
            if self._depth == 1:
                self._current_row = []
        elif tag in ("td", "th", "te"):
            if self._depth == 1:
                self._in_cell = True
                self._current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            if self._depth == 1 and self._current_table:
                self.tables.append(self._current_table)
            self._depth -= 1
        elif tag == "tr":
            if self._depth == 1 and self._current_row:
                self._current_table.append(self._current_row)
        elif tag in ("td", "th", "te"):
            if self._depth == 1 and self._in_cell:
                self._current_row.append(self._current_cell.strip())
                self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell += data

    def handle_entityref(self, name):
        if self._in_cell:
            entities = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"'}
            self._current_cell += entities.get(name, "")

    def handle_charref(self, name):
        if self._in_cell:
            try:
                ch = chr(int(name[1:], 16) if name.startswith("x") else int(name))
                self._current_cell += ch
            except Exception:
                pass


def extract_tables(html: str) -> list[list[list[str]]]:
    parser = TableExtractor()
    parser.feed(html)
    return parser.tables


def normalize_text(s: str) -> str:
    """공백/줄바꿈 제거 후 소문자."""
    return re.sub(r"\s+", "", s).lower()


def parse_number(s: str) -> int | None:
    """'1,234,567' 또는 '(1,234)' 형태의 숫자 문자열을 int로."""
    if not s:
        return None
    s = s.strip().replace(",", "").replace(" ", "")
    # 음수 표기: (1234) 또는 -1234 또는 △1,234
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    elif s.startswith("△") or s.startswith("▲"):
        negative = True
        s = s[1:]
    elif s.startswith("-"):
        negative = True
        s = s[1:]
    s = s.replace(",", "")
    try:
        v = int(float(s))
        return -v if negative else v
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 부문 테이블 탐색 및 추출
# ─────────────────────────────────────────────────────────────────────────────

def score_table_relevance(table: list[list[str]], cfg: dict) -> float:
    """
    테이블이 사업부문 테이블일 가능성 점수 (0.0 ~ 1.0).
    부문명이 많이 등장할수록, 수익/영업이익 키워드가 있을수록 높음.
    """
    flat = " ".join(normalize_text(cell) for row in table for cell in row)

    # 부문명 매칭
    seg_hits = 0
    for seg_key, seg_info in cfg["segments"].items():
        for alias in seg_info["aliases"]:
            if normalize_text(alias) in flat:
                seg_hits += 1
                break

    if seg_hits == 0:
        return 0.0

    # 수익/영업이익 키워드
    rev_hit = any(normalize_text(k) in flat for k in cfg["revenue_row_aliases"])
    op_hit  = any(normalize_text(k) in flat for k in cfg["op_income_row_aliases"])

    # 숫자 셀 비율
    all_cells = [c for row in table for c in row if c.strip()]
    num_cells = sum(1 for c in all_cells if parse_number(c) is not None)
    num_ratio = num_cells / max(len(all_cells), 1)

    total_segs = len(cfg["segments"])
    score = (seg_hits / total_segs) * 0.5 + (0.25 if rev_hit else 0) + (0.15 if op_hit else 0) + min(num_ratio, 0.1)
    return round(score, 3)


def detect_table_orientation(table: list[list[str]], cfg: dict) -> str:
    """
    테이블 방향 판별:
      'row_header' : 행 헤더 = 수익/영업이익, 열 헤더 = 부문명  (일반적)
      'col_header' : 행 헤더 = 부문명, 열 헤더 = 수익/영업이익  (전치형)
      'unknown'
    """
    if not table:
        return "unknown"

    # 첫 행/열에 부문명이 있는지 확인
    first_row_flat = " ".join(normalize_text(c) for c in table[0])
    first_col_flat = " ".join(normalize_text(row[0]) for row in table if row)

    seg_in_first_row = sum(
        1 for seg_info in cfg["segments"].values()
        if any(normalize_text(a) in first_row_flat for a in seg_info["aliases"])
    )
    seg_in_first_col = sum(
        1 for seg_info in cfg["segments"].values()
        if any(normalize_text(a) in first_col_flat for a in seg_info["aliases"])
    )

    if seg_in_first_row >= 2:
        return "row_header"   # 열 헤더에 부문명 → 행이 수익/영업이익
    if seg_in_first_col >= 2:
        return "col_header"   # 행 헤더에 부문명 → 열이 수익/영업이익
    return "unknown"


def find_col_for_segment(header_row: list[str], seg_info: dict) -> int | None:
    """헤더 행에서 부문명 열 인덱스 반환."""
    for i, cell in enumerate(header_row):
        n = normalize_text(cell)
        for alias in seg_info["aliases"]:
            if normalize_text(alias) in n:
                return i
    return None


def find_row_for_keyword(table: list[list[str]], keywords: list[str]) -> int | None:
    """첫 번째 열(또는 전체)에서 키워드 행 인덱스 반환."""
    for i, row in enumerate(table):
        if not row:
            continue
        cell0 = normalize_text(row[0])
        for kw in keywords:
            if normalize_text(kw) in cell0:
                return i
        # 첫 열 외 다른 열에도 확인
        row_text = " ".join(normalize_text(c) for c in row)
        for kw in keywords:
            if normalize_text(kw) in row_text:
                return i
    return None


def extract_values_row_header(
    table: list[list[str]], cfg: dict
) -> dict[str, dict[str, int | None]]:
    """
    row_header 방향 테이블에서 값 추출.
    헤더행: [구분, 부문A, 부문B, ..., 합계]
    데이터행: [수익, val, val, ...]
    """
    if not table:
        return {}

    header_row = table[0]
    result: dict[str, dict] = {}

    # 각 부문의 열 인덱스 찾기
    seg_col: dict[str, int] = {}
    for seg_key, seg_info in cfg["segments"].items():
        col = find_col_for_segment(header_row, seg_info)
        if col is not None:
            seg_col[seg_key] = col

    if not seg_col:
        return {}

    # 수익/영업이익 행 찾기
    rev_row = find_row_for_keyword(table, cfg["revenue_row_aliases"])
    op_row  = find_row_for_keyword(table, cfg["op_income_row_aliases"])

    for seg_key, col in seg_col.items():
        rev = None
        op  = None
        if rev_row is not None and col < len(table[rev_row]):
            rev = parse_number(table[rev_row][col])
        if op_row is not None and col < len(table[op_row]):
            op = parse_number(table[op_row][col])
        result[seg_key] = {"revenue": rev, "operating_income": op}

    return result


def extract_values_col_header(
    table: list[list[str]], cfg: dict
) -> dict[str, dict[str, int | None]]:
    """
    col_header 방향 테이블에서 값 추출.
    헤더행: [구분, 수익, 영업이익, ...]
    데이터행: [부문명, val, val, ...]
    """
    if not table:
        return {}

    header_row = table[0]
    result: dict[str, dict] = {}

    # 수익/영업이익 열 인덱스 찾기
    rev_col: int | None = None
    op_col:  int | None = None
    for i, cell in enumerate(header_row):
        n = normalize_text(cell)
        if rev_col is None and any(normalize_text(k) in n for k in cfg["revenue_row_aliases"]):
            rev_col = i
        if op_col is None and any(normalize_text(k) in n for k in cfg["op_income_row_aliases"]):
            op_col = i

    if rev_col is None and op_col is None:
        return {}

    # 부문명 행 찾기
    for row in table[1:]:
        if not row:
            continue
        row0 = normalize_text(row[0])
        for seg_key, seg_info in cfg["segments"].items():
            if seg_key in result:
                continue
            for alias in seg_info["aliases"]:
                if normalize_text(alias) in row0:
                    rev = parse_number(row[rev_col]) if rev_col is not None and rev_col < len(row) else None
                    op  = parse_number(row[op_col])  if op_col  is not None and op_col  < len(row) else None
                    result[seg_key] = {"revenue": rev, "operating_income": op}
                    break

    return result


def parse_segment_from_html(html: str, cfg: dict) -> dict:
    """
    HTML에서 사업부문 테이블을 찾아 값을 추출한다.

    반환:
      {
        "status": "confident" | "uncertain" | "failed",
        "confidence": float,
        "segments": { "TLS": {"revenue": int, "operating_income": int}, ... },
        "note": str,
        "raw_table": [[...]],   # 디버깅용
        "issues": [str],        # 검증 실패 사유
      }
    """
    tables = extract_tables(html)
    log.info("    HTML 내 테이블 수: %d", len(tables))

    # 1) 부문 관련 테이블 후보 선정 (관련도 점수 순)
    scored = [(score_table_relevance(t, cfg), t) for t in tables]
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_table = scored[0] if scored else (0.0, [])
    log.info("    최고 관련도 테이블 점수: %.3f (행 %d개)", best_score, len(best_table))

    if best_score < 0.2:
        return {
            "status": "failed",
            "confidence": 0.0,
            "segments": {},
            "note": "사업부문 테이블을 찾지 못함 (관련도 점수 0.2 미만)",
            "raw_table": [],
            "issues": ["테이블 탐색 실패"],
        }

    # 2) 테이블 방향 판별 및 값 추출
    orientation = detect_table_orientation(best_table, cfg)
    log.info("    테이블 방향: %s", orientation)

    if orientation == "row_header":
        extracted = extract_values_row_header(best_table, cfg)
    elif orientation == "col_header":
        extracted = extract_values_col_header(best_table, cfg)
    else:
        # 둘 다 시도
        extracted = extract_values_row_header(best_table, cfg)
        if not extracted:
            extracted = extract_values_col_header(best_table, cfg)

    # 3) 검증
    issues = []
    total_segs = len(cfg["segments"])
    found_segs = len(extracted)

    if found_segs == 0:
        return {
            "status": "failed",
            "confidence": 0.0,
            "segments": {},
            "note": "부문명 매칭 실패 — 테이블 구조가 변경됐을 수 있음",
            "raw_table": best_table[:8],
            "issues": ["부문명 매칭 0개"],
        }

    if found_segs < total_segs:
        issues.append(f"부문 {found_segs}/{total_segs}개만 추출됨 (미추출: {set(cfg['segments']) - set(extracted)})")

    for seg_key, vals in extracted.items():
        rev = vals.get("revenue")
        op  = vals.get("operating_income")
        if rev is not None and rev <= 0:
            issues.append(f"{seg_key} 매출액이 0 이하: {rev}")
        if rev is not None and rev > 0 and rev < cfg["unit"] * 1000:
            issues.append(f"{seg_key} 매출액이 너무 작음 (단위 오류 가능): {rev}")
        # 영업이익은 음수도 허용 (손실 가능)

    # 신뢰도 점수
    seg_ratio   = found_segs / total_segs
    has_rev     = sum(1 for v in extracted.values() if v.get("revenue") is not None)
    has_op      = sum(1 for v in extracted.values() if v.get("operating_income") is not None)
    value_ratio = (has_rev + has_op) / max(found_segs * 2, 1)
    error_penalty = len(issues) * 0.15
    confidence = max(0.0, min(1.0, seg_ratio * 0.6 + value_ratio * 0.4 - error_penalty))

    status = "confident" if confidence >= CONFIDENCE_THRESHOLD and not issues else "uncertain"
    note = f"자동 파싱 (신뢰도 {confidence:.2f}, {cfg['unit_label']} 기준)"
    if issues:
        note += " | 검증 경고: " + "; ".join(issues)

    log.info("    추출 결과: %s, 신뢰도 %.3f, 이슈 %d개", status, confidence, len(issues))
    for seg_key, vals in extracted.items():
        log.info("      %s → revenue=%s, op_income=%s", seg_key, vals.get("revenue"), vals.get("operating_income"))

    return {
        "status": status,
        "confidence": confidence,
        "segments": extracted,
        "note": note,
        "raw_table": best_table[:8],  # 처음 8행만 저장 (디버깅)
        "issues": issues,
    }


# ─────────────────────────────────────────────────────────────────────────────
# segment_data.json 업데이트
# ─────────────────────────────────────────────────────────────────────────────

def period_key_for_report(bsns_year: str, reprt_code: str) -> tuple[str, str]:
    """(period_type, period_key) 반환. period_type: 'annual'|'quarterly'"""
    info = REPORT_CODE_MAP.get(reprt_code)
    if not info:
        return "annual", bsns_year
    if info[0] == "annual":
        return "annual", bsns_year
    quarter = info[2] if len(info) > 2 else "Q?"
    return "quarterly", f"{bsns_year}{quarter}"


def update_segment_json(
    seg_path: Path,
    code: str,
    period_type: str,
    period_key: str,
    fs_div: str,
    source_label: str,
    parse_result: dict,
    unit: int,
) -> bool:
    """segment_data.json에 파싱 결과 기록. 성공 시 True."""
    try:
        with open(seg_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error("segment_data.json 읽기 실패: %s", e)
        return False

    company = data["companies"].setdefault(code, {
        "segments": list(SEGMENT_CONFIG[code]["segments"].keys()),
        "annual": {},
        "quarterly": {},
    })

    period_dict = company.setdefault(period_type, {})
    period_entry = period_dict.setdefault(period_key, {})
    fs_entry = {
        "source": source_label,
        "auto_parsed": True,
        "parse_confidence": parse_result["confidence"],
    }
    for seg_key, vals in parse_result["segments"].items():
        note_text = f"{source_label} · 자동파싱 (신뢰도 {parse_result['confidence']:.2f})"
        rev = vals.get("revenue")
        op  = vals.get("operating_income")
        # 단위 변환 (이미 unit 곱하기는 파서 단계에서 하지 않음 — 원 단위로 변환)
        if rev is not None:
            rev = rev * unit
        if op is not None:
            op = op * unit
        fs_entry[seg_key] = {"revenue": rev, "operating_income": op, "note": note_text}

    period_entry[fs_div] = fs_entry

    try:
        with open(seg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info("  segment_data.json 업데이트 완료: %s %s %s", code, period_type, period_key)
        return True
    except Exception as e:
        log.error("segment_data.json 쓰기 실패: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Issue 생성
# ─────────────────────────────────────────────────────────────────────────────

def create_github_issue(
    github_token: str,
    repo: str,
    title: str,
    body: str,
) -> bool:
    """GitHub API로 Issue 생성."""
    if not github_token or not repo:
        log.warning("GitHub token 또는 repo 미설정 — Issue 생성 건너뜀")
        return False
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "body": body, "labels": ["segment-data", "needs-review"]}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 201:
            log.info("  GitHub Issue 생성 완료: %s", r.json().get("html_url"))
            return True
        log.error("  GitHub Issue 생성 실패: %s %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        log.error("  GitHub Issue 요청 예외: %s", e)
        return False


def build_issue_body(
    code: str,
    period_key: str,
    report_info: dict,
    parse_result: dict,
    cfg: dict,
) -> str:
    """GitHub Issue 본문 생성."""
    co_name = cfg["name"]
    status  = parse_result["status"]
    conf    = parse_result["confidence"]
    issues  = parse_result.get("issues", [])
    segs    = parse_result.get("segments", {})
    raw_tbl = parse_result.get("raw_table", [])
    unit_label = cfg["unit_label"]

    lines = [
        f"## {co_name} ({code}) — {period_key} 사업부문 파싱 결과 검토 필요",
        "",
        f"**상태:** `{status}` | **신뢰도:** {conf:.2f} | **보고서:** [{report_info.get('report_nm')}]({report_info.get('url')})",
        "",
    ]

    if issues:
        lines += ["### ⚠️ 검증 경고", ""]
        for iss in issues:
            lines.append(f"- {iss}")
        lines.append("")

    lines += ["### 파싱된 값 (원 단위 변환 전, 단위: " + unit_label + ")", ""]
    if segs:
        lines.append("| 부문 | 매출액 | 영업이익 |")
        lines.append("|------|--------|---------|")
        for seg_key, vals in segs.items():
            rev = vals.get("revenue")
            op  = vals.get("operating_income")
            lines.append(f"| {seg_key} | {rev:,} | {op:,} |" if rev is not None else f"| {seg_key} | 미추출 | 미추출 |")
    else:
        lines.append("파싱 결과 없음.")
    lines.append("")

    if raw_tbl:
        lines += ["### 파싱 대상 테이블 (처음 8행)", "```"]
        for row in raw_tbl:
            lines.append(" | ".join(str(c)[:20] for c in row))
        lines += ["```", ""]

    lines += [
        "### 수동 업데이트 방법",
        "",
        f"1. [DART 보고서 원본]({report_info.get('url')}) 접속",
        f"2. 연결재무제표 주석에서 '영업부문정보' 찾기",
        f"3. `data/segment_data.json` 에서 `{code}` → `{period_key.replace('Q','').lower()}` → `CFS` 항목 수정",
        f"4. 값 단위: **원** (DART 표시값 × {cfg['unit']:,})",
        "",
        "```json",
        f'"{period_key}": {{',
        f'  "CFS": {{',
        f'    "source": "2026년 X분기보고서 (연결재무제표 주석 영업부문정보)",',
    ]
    for seg_key in cfg["segments"]:
        lines.append(f'    "{seg_key}": {{ "revenue": null, "operating_income": null, "note": null }},')
    lines += ["  }", "}", "```", ""]
    lines.append("_이 이슈는 자동 파싱 시스템이 생성했습니다._")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 파싱 로그 관리
# ─────────────────────────────────────────────────────────────────────────────

def load_parse_log(log_path: Path) -> dict:
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed": {}}


def save_parse_log(log_path: Path, parse_log: dict):
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(parse_log, f, ensure_ascii=False, indent=2)


def is_already_processed(parse_log: dict, rcept_no: str) -> bool:
    return rcept_no in parse_log.get("processed", {})


def mark_processed(parse_log: dict, rcept_no: str, result_summary: dict):
    parse_log.setdefault("processed", {})[rcept_no] = {
        "timestamp": datetime.now(KST).isoformat(),
        **result_summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DART 사업부문 자동 파싱")
    parser.add_argument("--api-key",       required=True,  help="DART API 키")
    parser.add_argument("--github-token",  default="",     help="GitHub Personal Access Token (Issue 생성용)")
    parser.add_argument("--repo",          default="wonnie426/logistics-dashboard", help="GitHub 저장소 owner/repo")
    parser.add_argument("--data-dir",      default="data", help="data/ 디렉토리 경로")
    parser.add_argument("--years",         default="2025,2026", help="수집 연도 (쉼표 구분)")
    parser.add_argument("--dry-run",       action="store_true", help="파일 쓰기/Issue 생성 없이 파싱만")
    args = parser.parse_args()

    api_key      = args.api_key
    github_token = args.github_token or os.environ.get("GITHUB_TOKEN", "")
    repo         = args.repo
    data_dir     = Path(args.data_dir)
    years        = [y.strip() for y in args.years.split(",")]
    dry_run      = args.dry_run

    seg_path = data_dir / "segment_data.json"
    log_path = data_dir / "segment_parse_log.json"

    if not seg_path.exists():
        log.error("segment_data.json 없음: %s", seg_path)
        sys.exit(1)

    parse_log = load_parse_log(log_path)
    updated   = False
    results   = []

    for code, cfg in SEGMENT_CONFIG.items():
        corp_code = cfg["corp_code"]
        log.info("\n▶ %s (%s) 처리 시작", cfg["name"], code)

        report_types = [
            ("11011", years),          # 사업보고서 (연간)
            ("11013", years),          # 1분기
            ("11012", years),          # 반기(Q2)
            ("11014", years),          # 3분기
        ]

        for reprt_code, check_years in report_types:
            report_label = REPORT_CODE_MAP.get(reprt_code, ["?"])[1] if len(REPORT_CODE_MAP.get(reprt_code, [])) > 1 else reprt_code

            for bsns_year in check_years:
                log.info("  [%s %s] 확인 중...", bsns_year, report_label)

                report_info = find_latest_report(corp_code, api_key, reprt_code, bsns_year)
                if not report_info:
                    log.info("  → 미공시 (보고서 없음)")
                    continue

                rcept_no = report_info["rcept_no"]
                period_type, period_key = period_key_for_report(bsns_year, reprt_code)

                if is_already_processed(parse_log, rcept_no):
                    prev = parse_log["processed"][rcept_no]
                    log.info("  → 이미 처리됨 (%s, %s)", rcept_no, prev.get("status"))
                    continue

                log.info("  → 새 보고서 발견: %s (%s)", rcept_no, report_info.get("rcept_dt"))

                # HTML 다운로드
                html_files = download_document_html(rcept_no, api_key)
                if not html_files:
                    log.warning("  → HTML 다운로드 실패")
                    if not dry_run:
                        issue_title = f"[세그먼트 파싱 실패] {cfg['name']} {period_key} — 문서 다운로드 오류"
                        issue_body  = (
                            f"## {cfg['name']} {period_key} 문서 다운로드 실패\n\n"
                            f"rcept_no: `{rcept_no}`\n"
                            f"보고서: [{report_info.get('report_nm')}]({report_info.get('url')})\n\n"
                            "DART document.xml API 접근이 차단됐거나 zip 파일이 아닌 응답이 반환됐습니다.\n"
                            "보고서를 직접 열어 사업부문 데이터를 수동으로 입력해 주세요."
                        )
                        create_github_issue(github_token, repo, issue_title, issue_body)
                    mark_processed(parse_log, rcept_no, {
                        "code": code, "period_key": period_key,
                        "status": "download_failed", "report_url": report_info.get("url"),
                    })
                    save_parse_log(log_path, parse_log)
                    results.append((code, period_key, "download_failed"))
                    continue

                # 파싱 — 여러 HTML 파일 중 가장 좋은 결과 사용
                best_parse = None
                for fname, html in html_files[:3]:   # 상위 3개 파일만 시도
                    log.info("  파싱 시도: %s (%d chars)", fname, len(html))
                    result = parse_segment_from_html(html, cfg)
                    if best_parse is None or result["confidence"] > best_parse["confidence"]:
                        best_parse = result
                    if best_parse["status"] == "confident":
                        break

                parse_result = best_parse
                log.info("  최종 파싱 결과: status=%s, confidence=%.3f",
                         parse_result["status"], parse_result["confidence"])

                source_label = (
                    f"{bsns_year}년 {report_label}"
                    f" (연결재무제표 주석 영업부문정보, {report_info['rcept_dt']} 제출)"
                )

                if parse_result["status"] == "confident":
                    if not dry_run:
                        ok = update_segment_json(
                            seg_path, code, period_type, period_key,
                            cfg["fs_div"], source_label, parse_result, cfg["unit"]
                        )
                        if ok:
                            updated = True
                    else:
                        log.info("  [dry-run] segment_data.json 업데이트 건너뜀")
                    mark_processed(parse_log, rcept_no, {
                        "code": code, "period_key": period_key,
                        "status": "auto_updated", "confidence": parse_result["confidence"],
                        "report_url": report_info.get("url"),
                    })
                    results.append((code, period_key, "auto_updated"))

                else:   # uncertain or failed
                    if not dry_run:
                        issue_title = (
                            f"[세그먼트 수동 확인] {cfg['name']} {period_key} "
                            f"— 파싱 {parse_result['status']} (신뢰도 {parse_result['confidence']:.2f})"
                        )
                        issue_body = build_issue_body(
                            code, period_key, report_info, parse_result, cfg
                        )
                        create_github_issue(github_token, repo, issue_title, issue_body)
                    else:
                        log.info("  [dry-run] GitHub Issue 생성 건너뜀")
                    mark_processed(parse_log, rcept_no, {
                        "code": code, "period_key": period_key,
                        "status": parse_result["status"],
                        "confidence": parse_result["confidence"],
                        "issues": parse_result["issues"],
                        "report_url": report_info.get("url"),
                    })
                    results.append((code, period_key, parse_result["status"]))

                if not dry_run:
                    save_parse_log(log_path, parse_log)

    # 결과 요약
    log.info("\n" + "="*60)
    log.info("처리 완료:")
    for code, pk, status in results:
        log.info("  %-4s %-10s → %s", code, pk, status)
    if updated:
        log.info("segment_data.json 이 업데이트됐습니다.")
    else:
        log.info("segment_data.json 변경 없음.")

    # GitHub Actions에서 output variable로 전달
    gha_output = os.environ.get("GITHUB_OUTPUT")
    if gha_output:
        with open(gha_output, "a") as f:
            f.write(f"updated={'true' if updated else 'false'}\n")
            f.write(f"results={json.dumps(results)}\n")


if __name__ == "__main__":
    main()
