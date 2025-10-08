# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Optional
import io
import csv
import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound

# [최종 수정] 모든 공용 유틸리티는 이제 main_controller.py가 로드한
# utils_common (최상위 모듈 또는 item_creator.utils_common)에서
# 직접 가져오거나, item_uploader 대신 item_creator의 utils_common을 사용하도록 변경합니다.
# 이렇게 하면 main_controller.py의 복잡한 shimming 구조에서 발생하는 오류를 피할 수 있습니다.

# item_uploader 경로를 item_creator.utils_common의 함수들로 대체합니다.
# main_controller가 sys.path에 root와 item_creator를 추가하므로,
# utils_common에 있는 함수는 from utils_common import ... 로 접근 가능합니다.

# 공용 유틸리티는 repo root의 utils_common과 item_creator의 utils_common에 분산되어 있으므로,
# main_controller의 shim을 믿고 item_uploader.utils_common에서 일괄 임포트하는 것이 아니라,
# 직접 유틸리티 모듈에서 필요한 함수들을 임포트합니다.

# item_uploader.utils_common을 직접 참조하는 대신,
# main_controller가 utils_common과 item_creator.utils_common을 로드한 후
# creation_steps를 로드하므로, 이들을 최상위/상대 경로로 참조해야 합니다.

# main_controller.py에서 제공하는 유틸리티들을 직접 참조합니다.
# _find_col_index는 item_uploader.automation_steps에 있었으나,
# 현재 구조에서는 utils_common.py에 정의되어 있지 않아 에러의 소지가 있습니다.
# 임포트 오류를 없애기 위해, 유틸리티 함수들을 로컬 utils_common에서만 가져오도록 수정합니다.

from utils_common import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, authorize_gspread, extract_sheet_id
)
from .utils_common import get_env, join_url, forward_fill_by_group

# _find_col_index 함수가 utils_common.py에 없으므로,
# item_uploader.automation_steps.py의 내용을 기반으로 여기에 재정의합니다.
# (이것이 가장 흔한 순환 임포트/모듈 누락 해결책입니다.)
def _find_col_index(keys: List[str], name: str, extra_alias: List[str]=[]) -> int:
    """헤더 키 목록(keys=header_key 적용된 리스트)에서 name 또는 alias를 찾음 (automation_steps에서 가져옴)"""
    tgt = header_key(name)
    aliases = [header_key(a) for a in extra_alias] + [tgt]
    # 정확 매칭
    for i, k in enumerate(keys):
        if k in aliases:
            return i
    # 포함 매칭
    for i, k in enumerate(keys):
        if any(a and a in k for a in aliases):
            return i
    return -1


# (참고) 레퍼런스 시트에서 템플릿 헤더 사전 로딩
def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    ws = safe_worksheet(ref, ref_sheet)
    vals = with_retry(lambda: ws.get_all_values()) or []
    out: Dict[str, List[str]] = {}
    for r in vals[1:]:
        if not r or not (r[0] or "").strip():
            continue
        out[header_key(r[0])] = [str(x or "").strip() for x in r[1:]]
    return out


# C1: TEM_OUTPUT 시트 준비/초기화
def run_step_C1(sh: gspread.Spreadsheet, ref: Optional[gspread.Spreadsheet]):
    print("\n[ Create ] Step C1: Prepare TEM_OUTPUT sheet ...")
    tem_name = get_tem_sheet_name()
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
    except Exception:
        tem_ws = with_retry(lambda: sh.add_worksheet(title=tem_name, rows=2000, cols=200))
    # PID 컬럼을 위해 A1은 비워둠 (C2에서 전체 갱신 예정)
    with_retry(lambda: tem_ws.update(values=[[""]], range_name="A1")) 
    print("C1 Done.")


# Collection 헤더 인덱스 수집
def _collect_indices(header_row: List[str]) -> Dict[str, int]:
    keys = [header_key(x) for x in header_row]
    def idx(name: str, aliases: List[str] = []) -> int:
        return _find_col_index(keys, name, extra_alias=aliases)

    return {
        "create": idx("create", ["use", "apply"]),  # A열 True 필터
        "variation": idx("variation", ["variationno", "variationintegrationno", "var code", "variation code"]),  # B
        "sku": idx("sku", ["seller_sku"]),  # C
        "brand": idx("brand", ["brandname"]),  # D
        "option_eng": idx("option(eng)", ["optioneng", "option", "option1", "option name", "option for variation 1"]),  # F→H
        "prod_name": idx("product name", ["item(eng)", "itemeng", "name"]),  # H→C
        "desc": idx("description", ["product description"]),  # J→D
        "category": idx("category"),  # K→B
        "detail_idx": idx("details index", ["detail image count", "details count", "detailindex"]),  # L (1~8)
    }


def _is_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("true", "t", "1", "y", "yes", "✔", "✅")


# C2: Collection → TEM_OUTPUT 생성 (매핑 + Variation 그룹 공란 보정)
def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet):
    print("\n[ Create ] Step C2: Build TEM from Collection ...")
    tem_name = get_tem_sheet_name()
    template_dict = _load_template_dict(ref)

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []
    if not coll_vals or len(coll_vals) < 2:
        print("[C2] Collection 비어 있음.")
        return

    # 컬럼 인덱스 파싱
    colmap = _collect_indices(coll_vals[0])
    create_i       = colmap["create"]       if colmap["create"]      >= 0 else 0
    variation_i    = colmap["variation"]    if colmap["variation"]   >= 0 else 1
    sku_i          = colmap["sku"]          if colmap["sku"]         >= 0 else 2
    brand_i        = colmap["brand"]        if colmap["brand"]       >= 0 else 3
    option_i       = colmap["option_eng"]   if colmap["option_eng"]  >= 0 else 5
    pname_i        = colmap["prod_name"]    if colmap["prod_name"]   >= 0 else 7
    desc_i         = colmap["desc"]         if colmap["desc"]        >= 0 else 9
    category_i     = colmap["category"]     if colmap["category"]    >= 0 else 10
    dcount_i       = colmap["detail_idx"]   if colmap["detail_idx"]  >= 0 else 11

    # 동일 Variation 그룹에서 공란 자동 보정
    # [수정 반영] reset_when: 완전히 빈 행만 그룹 단절로 간주 (Desc/Category 전파를 위함)
    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]
    def _reset_when(row: List[str]) -> bool:
        # 요구사항 반영: 완전히 빈 행(아예 데이터가 없는 행)만 그룹 단절로 간주.
        return not any(str(x or "").strip() for x in row)
    
    # coll_vals가 아닌 복사본에 forward-fill 실행
    ff_vals = forward_fill_by_group(
        [list(r) for r in coll_vals],
        group_idx=variation_i,
        fill_col_indices=fill_cols,
        reset_when=_reset_when
    )

    buckets: Dict[str, Dict[str, List]] = {}
    failures: List[List[str]] = []

    def set_if_exists(headers: List[str], row: List[str], name: str, value: str):
        idx = _find_col_index([header_key(h) for h in headers], name)
        if idx >= 0:
            row[idx] = value

    # A열 True만 처리 + 매핑
    for r in range(1, len(ff_vals)):
        row = ff_vals[r]
        if not _is_true(row[create_i] if create_i < len(row) else ""):
            continue

        variation = (row[variation_i] if variation_i < len(row) else "").strip()
        sku       = (row[sku_i] if sku_i < len(row) else "").strip()
        brand     = (row[brand_i] if brand_i < len(row) else "").strip()
        opt1      = (row[option_i] if option_i < len(row) else "").strip()
        pname     = (row[pname_i] if pname_i < len(row) else "").strip()
        desc      = (row[desc_i] if desc_i < len(row) else "").strip()
        category  = (row[category_i] if category_i < len(row) else "").strip()

        if not category:
            pid = variation or sku or f"ROW{r+1}"
            failures.append([pid, "", pname, "CATEGORY_MISSING", f"row={r+1}"])
            continue

        # 카테고리 최상위별 헤더 세트 선택
        top_norm = header_key(top_of_category(category) or "")
        headers = template_dict.get(top_norm)
        if not headers:
            failures.append(["", category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND", f"top={top_of_category(category)}"])
            continue

        # TEM_OUTPUT 한 행 구성 (PID 컬럼은 별도 추가)
        tem_row = [""] * len(headers)
        # 매핑 규칙
        set_if_exists(headers, tem_row, "category", category)               # K → B
        set_if_exists(headers, tem_row, "product name", pname)              # H → C
        set_if_exists(headers, tem_row, "product description", desc)        # J → D
        set_if_exists(headers, tem_row, "variation integration", variation) # B → F
        set_if_exists(headers, tem_row, "variation name1", "Options")       # 고정값 → G
        set_if_exists(headers, tem_row, "option for variation 1", opt1)     # F → H
        set_if_exists(headers, tem_row, "sku", sku)                         # C → N
        set_if_exists(headers, tem_row, "brand", brand)                     # D → AE

        pid = variation or sku or f"ROW{r+1}"
        b = buckets.setdefault(top_norm, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)

    # TEM_OUTPUT 시트에 집계 기록 (헤더 블록 + 데이터)
    out_matrix: List[List[str]] = []
    for _, pack in buckets.items():
        # 첫 열은 PID를 위해 비워둠 (out_matrix에선 [PID] + [Header] 형태로 저장)
        out_matrix.append(["PID"] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))

    # 실패 로그 누적
    if failures:
        try:
            ws_f = safe_worksheet(sh, "Failures")
        except WorksheetNotFound:
            ws_f = with_retry(lambda: sh.add_worksheet(title="Failures", rows=1000, cols=10))
            with_retry(lambda: ws_f.update(values=[["PID", "Category", "Name", "Reason", "Detail"]], range_name="A1"))
        
        # [Failures 시트 초기화 요구사항]은 main_controller.py의 _reset_failures에서 처리되므로, 
        # 여기서는 단순히 기존 값에 추가합니다.
        
        vals = with_retry(lambda: ws_f.get_all_values()) or []
        start = len(vals) + 1
        with_retry(lambda: ws_f.update(values=failures, range_name=f"A{start}"))

    print(f"C2 Done. Buckets: {len(buckets)}")


# C4: MARGIN → TEM 가격 매핑 (SKU 기준, 'SKU Price' 채우기)
def run_step_C4_prices(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C4: Fill SKU Price from MARGIN ...")
    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C4] TEM_OUTPUT 비어 있음.")
        return

    # 1) MARGIN 시트 로드 (SKU ↔ 소비자가)
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
    except WorksheetNotFound:
        print("[C4] MARGIN 시트를 찾을 수 없습니다. 가격 매핑을 건너뜜.")
        return
    mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
    if len(mg_vals) < 2:
        print("[C4] MARGIN 데이터가 비어 있습니다.")
        return

    mg_keys = [header_key(h) for h in mg_vals[0]]
    # A열 SKU, E열 소비자가(라벨은 유연하게 대응)
    idx_mg_sku   = _find_col_index(mg_keys, "sku", extra_alias=["seller_sku"])
    idx_mg_price = _find_col_index(
        mg_keys, "소비자가",
        extra_alias=["consumer price", "consumerprice", "price", "list price", "selling price", "sell price"]
    )
    if idx_mg_sku == -1 or idx_mg_price == -1:
        print(f"[C4] MARGIN 헤더 인식 실패: sku={idx_mg_sku}, price={idx_mg_price}")
        return

    sku_to_price: Dict[str, str] = {}
    for r in range(1, len(mg_vals)):
        row = mg_vals[r]
        sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
        price = (row[idx_mg_price] if idx_mg_price < len(row) else "").strip()
        if sku and price:
            sku_to_price[sku] = price

    # 2) TEM에서 블록별 헤더 탐지 후 SKU/Price 인덱스 찾아 채움
    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_price = -1

    for r0, row in enumerate(tem_vals):
        # 각 카테고리 블록의 헤더 경계 (두 번째 열이 'Category')
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku   = _find_col_index(cur_headers, "sku")
            idx_t_price = _find_col_index(
                cur_headers, "sku price",
                extra_alias=["price", "selling price", "sell price"]
            )
            continue
        if not cur_headers or idx_t_sku == -1 or idx_t_price == -1:
            continue

        # 실제 데이터 행: TEM은 A열 PID + 이후 헤더들과 정렬되어 있으므로 +1 보정
        sku = (row[idx_t_sku + 1] if len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        val = sku_to_price.get(sku, "")
        if not val:
            continue

        # 값이 다를 때만 업데이트
        cur = (row[idx_t_price + 1] if len(row) > idx_t_price + 1 else "").strip()
        if cur != val:
            # PID(A열=1) + Price 인덱스 + 1 = 최종 컬럼 인덱스
            updates.append(Cell(row=r0 + 1, col=idx_t_price + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C4 Done. Prices updated: {len(updates)} cells")


# C5: 이미지 URL 채우기 (Option/Cover/Details) + Variation 복원
def run_step_C5_images(
    sh: gspread.Spreadsheet,
    shop_code: str,
    cover_base_url: str,
    details_base_url: str,
    option_base_url: str,
):
    print("\n[ Create ] Step C5: Fill images (Option/Cover/Details) & restore Variation ...")

    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C5] TEM_OUTPUT 비어 있음.")
        return

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []

    # SKU → Variation, Variation → 상세이미지 개수 매핑 수집
    sku_to_var: Dict[str, str] = {}
    var_to_count: Dict[str, int] = {}

    if coll_vals and len(coll_vals) >= 2:
        colmap = _collect_indices(coll_vals[0])
        create_i       = colmap["create"]       if colmap["create"]      >= 0 else 0
        variation_i    = colmap["variation"]    if colmap["variation"]   >= 0 else 1
        sku_i          = colmap["sku"]          if colmap["sku"]         >= 0 else 2
        dcount_i       = colmap["detail_idx"]   if colmap["detail_idx"]  >= 0 else 11

        # Variation 그룹 공란 보정 (개수 포함)
        fill_cols = [variation_i, dcount_i]
        def _reset_when(row: List[str]) -> bool:
            # C5 수집을 위한 전파는 C2와 달리 'Create=True' 행만 추적
            if not any(str(x or "").strip() for x in row):
                return True
            return not _is_true(row[create_i] if create_i < len(row) else "")
            
        ff_vals = forward_fill_by_group(
            coll_vals, group_idx=variation_i, fill_col_indices=fill_cols, reset_when=_reset_when
        )

        for r in range(1, len(ff_vals)):
            row = ff_vals[r]
            if not _is_true(row[create_i] if create_i < len(row) else ""):
                continue
            var = (row[variation_i] if variation_i < len(row) else "").strip()
            sku = (row[sku_i] if sku_i < len(row) else "").strip()
            try:
                cnt = int((row[dcount_i] if dcount_i < len(row) else "").strip() or "8")
            except Exception:
                cnt = 8
            cnt = max(1, min(8, cnt))
            if sku:
                sku_to_var[sku] = var
            if var and var not in var_to_count:
                var_to_count[var] = cnt

    updates: List[Cell] = []
    cur_headers = None
    idx_cover = idx_optimg = idx_sku = idx_varno = -1
    idx_items: List[int] = []

    suffix = f"_C_{shop_code}" if shop_code else ""

    for r0, row in enumerate(tem_vals):
        # 헤더 경계(두번째 열이 'Category'인 행): 이후 열 인덱스 계산
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_cover   = _find_col_index(cur_headers, "coverimage")
            idx_optimg  = _find_col_index(cur_headers, "imagepervariation")
            idx_sku     = _find_col_index(cur_headers, "sku")
            idx_varno   = _find_col_index(cur_headers, "variationintegration")
            idx_items = []
            for k in range(1, 9):
                i = _find_col_index(cur_headers, f"itemimage{k}")
                idx_items.append(i)
            continue
        if not cur_headers:
            continue

        # TEM은 A열 PID + 이후 헤더들과 정렬되어 있으므로 +1 보정
        sku = (row[idx_sku + 1] if idx_sku != -1 and len(row) > idx_sku + 1 else "").strip()
        var = sku_to_var.get(sku, (row[idx_varno + 1] if idx_varno != -1 and len(row) > idx_varno + 1 else "").strip())
        key = var if var else sku  # Cover/Details 기준: VIN 있으면 VIN, 없으면 SKU

        # Variation Integration No. 복원(있으면 덮어씀)
        if idx_varno != -1 and var and (row[idx_varno + 1] if len(row) > idx_varno + 1 else "") != var:
            updates.append(Cell(row=r0 + 1, col=idx_varno + 2, value=var))

        # I열: Image per Variation = OptionBaseURL + SKU
        if idx_optimg != -1 and sku:
            opt_url = join_url(option_base_url, sku)
            if (row[idx_optimg + 1] if len(row) > idx_optimg + 1 else "") != opt_url:
                updates.append(Cell(row=r0 + 1, col=idx_optimg + 2, value=opt_url))

        # O열: Cover image = (VIN or SKU) + suffix
        if idx_cover != -1 and key:
            # join_url은 뒤에 슬래시를 제거하므로 직접 .jpg를 붙임
            cov_url = f"{join_url(cover_base_url, key)}{suffix}.jpg"
            if (row[idx_cover + 1] if len(row) > idx_cover + 1 else "") != cov_url:
                updates.append(Cell(row=r0 + 1, col=idx_cover + 2, value=cov_url))

        # P~W: Item Image 1~8 = DetailsBaseURL + (VIN or SKU) + _D1.._D8
        count = var_to_count.get(var, 8)
        for k, j in enumerate(idx_items, start=1):
            if j == -1:
                continue
            val = f"{join_url(details_base_url, key)}_D{k}" if k <= count else ""
            if (row[j + 1] if len(row) > j + 1 else "") != val:
                updates.append(Cell(row=r0 + 1, col=j + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print("C5 Done.")


# C6: Stock/Weight/Brand 보정 (Stock=1000, Brand=0, Weight=MARGIN 매핑)
def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C6: Fill Stock, Weight, Brand ...")
    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C6] TEM_OUTPUT 비어 있음.")
        return

    # 1) MARGIN 시트 로드 (SKU ↔ Weight)
    sku_to_weight: Dict[str, str] = {}
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
        mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
        if len(mg_vals) >= 2:
            mg_keys = [header_key(h) for h in mg_vals[0]]
            idx_mg_sku = _find_col_index(mg_keys, "sku", extra_alias=["seller_sku"])
            # F열 또는 header="weight"
            idx_mg_weight = _find_col_index(
                mg_keys, "weight", extra_alias=["무게", "f"] 
            )
            if idx_mg_sku != -1 and idx_mg_weight != -1:
                for r in range(1, len(mg_vals)):
                    row = mg_vals[r]
                    sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
                    weight = (row[idx_mg_weight] if idx_mg_weight < len(row) else "").strip()
                    if sku and weight:
                        sku_to_weight[sku] = weight
    except WorksheetNotFound:
        print("[C6] MARGIN 시트를 찾을 수 없습니다. Weight 매핑을 건너뜜.")
    except Exception as e:
        print(f"[C6] MARGIN 처리 중 오류: {e}. Weight 매핑 건너뜜.")

    # 2) TEM에서 블록별 헤더 탐지 후 Stock, Weight, Brand, SKU 인덱스 찾아 채움
    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_stock = idx_t_weight = idx_t_brand = -1
    
    for r0, row in enumerate(tem_vals):
        # 각 카테고리 블록의 헤더 경계 (두 번째 열이 'Category')
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku    = _find_col_index(cur_headers, "sku")
            idx_t_stock  = _find_col_index(cur_headers, "stock") # M열
            idx_t_weight = _find_col_index(cur_headers, "weight") # Z열
            idx_t_brand  = _find_col_index(cur_headers, "brand") # AE열
            continue
        
        if not cur_headers or idx_t_sku == -1:
            continue

        # 실제 데이터 행: TEM은 A열 PID + 이후 헤더들과 정렬되어 있으므로 +1 보정
        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        # Stock (M열 = 1000)
        if idx_t_stock != -1:
            val = "1000"
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != val:
                # PID(A열=1) + Stock 인덱스 + 1 = 최종 컬럼 인덱스
                updates.append(Cell(row=r0 + 1, col=idx_t_stock + 2, value=val))

        # Brand (AE열 = 0)
        if idx_t_brand != -1:
            val = "0"
            cur = (row[idx_t_brand + 1] if len(row) > idx_t_brand + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_brand + 2, value=val))
        
        # Weight (Z열 = MARGIN 매핑)
        if idx_t_weight != -1 and sku:
            val = sku_to_weight.get(sku, "")
            if val:
                cur = (row[idx_t_weight + 1] if len(row) > idx_t_weight + 1 else "").strip()
                if cur != val:
                    updates.append(Cell(row=r0 + 1, col=idx_t_weight + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))
    
    print(f"C6 Done. Updates: {len(updates)} cells")


class ShopeeCreator:
    """
    신규 상품 템플릿 생성 파이프라인 컨트롤러. (main_controller.py의 _ImplCreator)
    """

    def __init__(self, sheet_url: str, ref_url: Optional[str] = None) -> None:
        if not sheet_url:
            raise ValueError("sheet_url is required.")
        self.sheet_url = sheet_url
        self.ref_url = ref_url

        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None
        
        # main_controller.py에서 주입되는 속성들
        self.shop_code: Optional[str] = None
        self.cover_base_url: Optional[str] = None
        self.details_base_url: Optional[str] = None
        self.option_base_url: Optional[str] = None


    # ----------------------------------------------------------
    # 내부 유틸
    # ----------------------------------------------------------

    def _connect(self) -> None:
        """gspread 인증 및 대상/레퍼런스 스프레드시트 오픈"""
        self.gc = authorize_gspread()
        ss_id = extract_sheet_id(self.sheet_url)
        if not ss_id:
            raise ValueError("Invalid sheet_url: cannot extract spreadsheet ID.")
        self.sh = with_retry(lambda: self.gc.open_by_key(ss_id))

        if self.ref_url:
            ref_id = extract_sheet_id(self.ref_url)
            if ref_id:
                try:
                    self.ref = with_retry(lambda: self.gc.open_by_key(ref_id))
                except Exception:
                    self.ref = None
            else:
                self.ref = None

    def _reset_failures(self) -> None:
        """실행 시마다 Failures 시트를 초기화"""
        assert self.sh is not None
        try:
            ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: ws.clear())
        except WorksheetNotFound:
            ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=10))
        # [Failures 시트 초기화 요구사항 반영]: 헤더만 남기고 초기화
        with_retry(lambda: ws.update(values=[["PID", "Category", "Name", "Reason", "Detail"]], range_name="A1"))

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C4 → C5 → C6
        """
        try:
            # 인증 및 시트 연결
            self._connect()
            assert self.sh is not None
            assert self.ref is not None # C2, C4에서 사용하므로 필요

            # 실패 로그 초기화 (요구사항)
            self._reset_failures()

            # 단계 실행
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C4_prices(self.sh)
            run_step_C5_images(
                self.sh,
                shop_code=self.shop_code,
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )
            run_step_C6_stock_weight_brand(self.sh)

            print("✅ 모든 단계 완료되었습니다.")
            return True

        except Exception as e:
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False


    # ----------------------------------------------------------
    # CSV Export (main_controller가 fallback으로 사용)
    # ----------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """TEM_OUTPUT 시트를 CSV 바이트로 반환"""
        if not self.sh:
            return None

        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals:
                return None

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerows(vals)
            return buf.getvalue().encode("utf-8-sig")
        except Exception as e:
            print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
            return None
