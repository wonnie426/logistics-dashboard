# 물류사 비교 대시보드 — 프로젝트 컨텍스트

> 이 문서는 AI와의 작업 세션을 이어받을 때 빠르게 컨텍스트를 공유하기 위해 작성됐습니다.
> 마지막 업데이트: 2026-06-30

---

## 1. 프로젝트 개요

**GitHub Pages 정적 사이트**로 배포되는 물류 4사 재무 비교 대시보드.

- **URL**: `https://wonnie426.github.io/logistics-dashboard/`
- **저장소**: `https://github.com/wonnie426/logistics-dashboard`
- **로컬 경로**: `C:\Users\LOTTE GL\Desktop\logistics-dashboard`
- **구조**: 단일 `index.html` + `data/` JSON 파일들 (빌드 없음, 순수 정적)

### 비교 대상 4사

| 코드 | 회사명 | 색상 |
|------|--------|------|
| `LGL` | 롯데글로벌로지스 | `#C8102E` |
| `CJ` | CJ대한통운 | `#00A0DC` |
| `HJ` | 한진 | `#003087` |
| `HGL` | 현대글로비스 | `#002C5F` |

---

## 2. 기술 스택

```
index.html          — 전체 앱 (HTML + CSS + JS 단일 파일, ~5000줄+)
data/
  financial_data.json   — 재무 요약 데이터 (연간/분기)
  statements.json       — DART 형식 재무제표 라인 항목
  segment_data.json     — 세그먼트 데이터
  thresholds.json       — 업종 임계값
  industry_avg.json     — 업종 평균값

라이브러리 (CDN):
  Chart.js 4.4.0
  PptxGenJS 3.12.0
  XLSX (SheetJS) 0.18.5
```

---

## 3. 데이터 구조

### 3-1. financial_data.json

```json
{
  "companies": {
    "LGL": {
      "annual": {
        "2024": {
          "CFS": {
            "bs": { "total_assets": ..., "total_liabilities": ..., "total_equity": ..., ... },
            "pl": { "revenue": ..., "operating_income": ..., "net_income": ..., ... },
            "cf": { "operating_cf": ..., "investing_cf": ..., "financing_cf": ..., "capex": ..., ... }
          },
          "OFS": { "bs": {...}, "pl": {...}, "cf": {...} },
          "_default": "CFS"
        }
      },
      "quarterly": { ... }
    }
  }
}
```

**주의**: LGL 2021/2022는 원래 `_default` 키가 없었음 (수동 입력분). 현재는 추가됨.

#### bs 주요 필드
`total_assets`, `current_assets`, `non_current_assets`, `total_liabilities`, `current_liabilities`, `non_current_liabilities`, `total_equity`, `controlling_equity`, `cash_and_equivalents`, `trade_receivables`, `inventory`, `short_term_borrowings`, `current_portion_lt_debt`, `long_term_borrowings`, `bonds_payable`, `lease_liabilities`

#### pl 주요 필드
`revenue`, `cost_of_revenue`, `gross_profit`, `sga`, `operating_income`, `interest_expense`, `net_income`, `controlling_net_income`

#### cf 주요 필드
`operating_cf`, `investing_cf`, `financing_cf`, `interest_paid`, `interest_received`, `tax_paid`, `capex`, `beginning_cash`, `ending_cash`

---

### 3-2. statements.json

DART API 형식의 재무제표 라인 항목. `stmtViewer()` 함수가 이 데이터를 렌더링함.

```json
{
  "LGL": {
    "CFS": {
      "annual": {
        "2024": {
          "BS": [{"l": "계정명", "v": 숫자(원)}, ...],
          "IS": [...],
          "CIS": [...],
          "CF": [...],
          "SCE": [...]
        }
      }
    },
    "OFS": {
      "annual": {
        "2024": { "BS": [...], "IS": [...], "CIS": [...], "CF": [...], "SCE": [...] }
      }
    }
  },
  "CJ": { ... },
  "HJ": { ... },
  "HGL": { ... }
}
```

**v 값 부호 규칙**:
- 자산/매출 등 양수 항목: 양수
- 매출원가, 비용, 부채 상환 등: 음수

---

## 4. 주요 JS 함수/상수

```javascript
// 상수
CMP_COLORS = {LGL:'#C8102E', CJ:'#00A0DC', HJ:'#003087', HGL:'#002C5F'}
CMP_NAMES  = {LGL:'롯데글로벌로지스', CJ:'CJ대한통운', HJ:'한진', HGL:'현대글로비스'}

// 재무제표 뷰어 (탭별 테이블 렌더링)
stmtViewer(code, year, fsDiv, stmtType)
  → statements.json에 데이터 있으면 실제 라인 표시
  → 없으면 financial_data.json 요약값으로 fallback (회색 이탤릭)

// 종합비교 커스텀 차트 다운로드
downloadChart(canvasId, filename)         // PNG
downloadCmpChartExcel()                   // Excel (.xlsx)
downloadCmpChartPPT()                     // PPT (PptxGenJS, 2슬라이드)

// 커스텀 차트 데이터
customBuilderState.compare = { metrics: [...], companies: [...] }
getCmpData(code, period)                  // 회사별 기간 데이터
getMetricValue(data, metricKey)           // 지표 값 추출
getCmpPeriods()                           // 표시할 기간 목록

// STMT_DEFS: 재무제표 항목 한글 → [group, field] 매핑
// (stmtViewer fallback에서 financial_data.json 필드 찾을 때 사용)
```

---

## 5. 인프라 & 배포

### GitHub Actions
- `.github/workflows/update_data.yml` — 매일 23:00 UTC 실행 (KST 오전 8시)
- DART API는 등록 IP만 허용 → **GCP VM**(IP: `35.188.162.158`)에서 cron으로 직접 실행 후 push

### Git Push 방법 (Windows 인증 우회)
```bash
git -c credential.helper= push origin main
```

### GCP VM
- 역할: DART API 데이터 자동 수집 스크립트 실행
- DART API 키: GitHub Actions Secret `DART_API_KEY`로 관리
- VM에서 git pull 시 diverge 발생했을 때:
  ```bash
  git fetch origin && git reset --hard origin/main
  ```

---

## 6. DART API 관련

- **등록 IP**: `35.188.162.158` (GCP VM)
- **LGL CORP_CODE**: `00207676`
- **주요 엔드포인트**: `https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json`
- **파라미터**: `corp_code`, `bsns_year`, `reprt_code(11011=사업보고서)`, `fs_div(CFS/OFS)`

**중요**: LGL 2021/2022년도는 DART API에서 **error 013** (XBRL 미공시) 반환.
→ 이유: 비상장사 시절 이미지 PDF로 제출, XBRL 데이터 없음.
→ 해결: 사업보고서 PDF 스크린샷에서 수동 입력.

---

## 7. 완료된 작업 목록

### 7-1. 종합비교 커스텀 차트 다운로드 버튼 추가
**위치**: `index.html` → `cmpBuilderHtml()` 함수

card-title 우측에 PNG / Excel / PPT 버튼 3개 추가:
```html
<div style="display:flex;gap:6px">
  <button class="chart-download" onclick="downloadChart('c-cmp-custom','종합비교_커스텀차트.png')">💾 PNG</button>
  <button class="chart-download" onclick="downloadCmpChartExcel()">📋 Excel</button>
  <button class="chart-download" onclick="downloadCmpChartPPT()">📊 PPT</button>
</div>
```

`downloadCmpChartExcel()`, `downloadCmpChartPPT()` 함수 신규 추가.
PPT는 2슬라이드 구성: 슬라이드1 편집 가능 차트 (이중 Y축 지원), 슬라이드2 데이터 테이블.

---

### 7-2. stmtViewer fallback 구현
**위치**: `index.html` → `stmtViewer()` 함수

statements.json에 해당 연도 데이터 없을 때 financial_data.json 요약값으로 대체 표시.
회색 이탤릭으로 fallback 값임을 시각적으로 구분.

```javascript
// STMT_DEFS 한글라벨 → [group, field] 매핑
const simpleFb = {};
STMT_DEFS.forEach(([,,rows]) => rows.forEach(([lbl, field, grp]) => {
  simpleFb[lbl] = [grp, field];
}));

function fbVal(dartLabel, k) {
  let fb = simpleFb[dartLabel];
  if (!fb) {
    const entry = Object.entries(simpleFb).find(([lbl]) =>
      dartLabel.startsWith(lbl) || lbl.startsWith(dartLabel.split('(')[0].trim())
    );
    if (entry) fb = entry[1];
  }
  return fb ? (dataMap[k]?.[fb[0]]?.[fb[1]] ?? null) : null;
}
```

---

### 7-3. LGL 2021/2022 연결재무제표(CFS) 수동 입력

**출처**: 롯데글로벌로지스 2022년 사업보고서 (2023.03.31 제출) 스크린샷
**파일**: `data/statements.json` → `LGL.CFS.annual.2021`, `LGL.CFS.annual.2022`

| 구분 | 2021 항목수 | 2022 항목수 |
|------|------------|------------|
| BS (재무상태표) | 44 | 46 |
| IS (손익계산서) | 22 | 22 |
| CIS (포괄손익계산서) | 10 | 10 |
| CF (현금흐름표) | 35 | 32 |
| SCE (자본변동표) | 24 | 22 |

**주요 수치 (연결 기준)**:

| 항목 | 2021 | 2022 |
|------|------|------|
| 자산총계 | 2조 2,913억 | 2조 6,540억 |
| 매출액 | 3조 2,824억 | 3조 9,983억 |
| 영업이익 | 427억 | 626억 |
| 당기순이익 | 190억 | 269억 |
| 영업CF | 904억 | 2,120억 |
| capex | 2,859억 | 1,378억 |

---

### 7-4. LGL 2021/2022 별도재무제표(OFS) 수동 입력

**파일**: `data/statements.json` → `LGL.OFS.annual.2021`, `LGL.OFS.annual.2022`

| 구분 | 2021 항목수 | 2022 항목수 |
|------|------------|------------|
| BS | 39 | 40 |
| IS | 16 | 16 |
| CIS | 6 | 6 |
| CF | 30 | 32 |
| SCE | 16 | 15 |

**주요 수치 (별도 기준)**:

| 항목 | 2021 | 2022 |
|------|------|------|
| 자산총계 | 2조 1,685억 | 2조 4,403억 |
| 매출액 | 2조 7,132억 | 3조 2,735억 |
| 영업이익 | 377억 | 518억 |
| 당기순이익 | 149억 | 199억 |
| 영업CF | 906억 | 2,072억 |
| capex | 2,838억 | 1,354억 |

---

## 8. Git 커밋 히스토리 (주요 작업)

```
14fea9b  LGL 2021/2022 별도 현금흐름표(OFS CF) 추가
8d50930  LGL 2021/2022 별도재무제표(OFS) 추가 (22년 사업보고서)
2146f96  LGL 2021/2022 현금흐름표·자본변동표 추가 (22년 사업보고서)
31409e8  LGL 2021/2022 연결재무제표 수동 입력 (22년 사업보고서)
892e0ac  stmtViewer fallback 구현 (DART 미공시 연도 대응)
...      종합비교 커스텀차트 PNG/Excel/PPT 다운로드 버튼 추가
```

---

## 9. 스크립트 파일

| 파일 | 용도 |
|------|------|
| `scripts/patch_lgl_2122.js` | LGL 2021/2022 CFS BS+IS+CIS+SCE 입력 |
| `scripts/patch_lgl_cf_sce.js` | LGL 2021/2022 CFS CF+SCE 보완 |
| `scripts/patch_lgl_ofs_2122.js` | LGL 2021/2022 OFS BS+IS+CIS+SCE 입력 |
| `scripts/patch_lgl_ofs_cf.js` | LGL 2021/2022 OFS CF 입력 |
| `.github/scripts/patch_lgl_statements.py` | DART API로 LGL 구년도 시도 (error 013으로 실패) |
| `.github/scripts/fetch_dart.py` | DART API 자동 수집 (GCP VM용) |

---

## 10. 알려진 이슈 & 제약

1. **LGL 2021/2022 DART 미공시**: DART API error 013. XBRL 미제출 연도. 수동 입력으로 해결.
2. **Windows npx 경로 문제**: `npx.cmd`에 공백 포함 경로 이슈로 로컬 프리뷰 서버 불안정.
3. **git credential 캐싱**: Windows Credential Manager 충돌 시 `git -c credential.helper= push origin main` 사용.
4. **GCP VM diverge**: VM 로컬 커밋과 origin 충돌 시 `git fetch origin && git reset --hard origin/main`.

---

## 11. 향후 작업 예정 (미완료)

- [ ] 각 회사 탭에서 재무요약 섹션 및 기본 차트 4개 제거
- [ ] 각 섹션별 접기/펼치기(collapse/expand) 버튼 추가
- [ ] DART 세그먼트 데이터 자동 파싱 방안 검토

---

## 12. 다음 AI에게 전달할 핵심 사항

1. **단일 index.html 구조**: 모든 로직이 index.html 안에 있음. 파일 분리 없음.
2. **데이터 파일 2개**: `financial_data.json`(요약) + `statements.json`(라인 항목) — 역할 구분 중요.
3. **LGL만 2021/2022 수동 입력**: 다른 3사(CJ/HJ/HGL)는 DART XBRL 정상 공시.
4. **fs_div 개념**: CFS=연결재무제표, OFS=별도재무제표. `_default: "CFS"` 키로 기본값 지정.
5. **배포 방식**: GitHub Pages 자동 배포 (push → 즉시 반영, 빌드 없음).
6. **금액 단위**: statements.json은 모두 **원(KRW)** 단위. financial_data.json도 동일.
