# shopee_creator/creation_steps.py
# -*- coding: utf-8 -*
from __future__ import annotations

from typing import List, Dict, Optional
import io
import csv
import re
from io import BytesIO

import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound
import pandas as pd

from .utils_creator import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, get_env,
    forward_fill_by_group, _is_true
)

# -------------------------------------------------------------------
# 공용: 시트 탭 유연 탐색(정확/부분 매칭)
# -------------------------------------------------------------------
def _find_worksheet_by_alias(sh: gspread.Spreadsheet, aliases: List[str]) -> gspread.Worksheet:
    want = {str(a).strip().lower() for a in aliases if str(a).strip()}
    sheets = sh.worksheets()

    # 1) 정확 매칭
    for ws in sheets:
        if ws.title.strip().lower() in want:
            return ws

    # 2) 부분 매칭
    for ws in sheets:
        t = ws.title.strip().lower()
        if any(a in t for a in want):
            return ws

    raise WorksheetNotFound(
        f"Sheet not found by aliases: {aliases}; existing={[w.title for w in sheets]}"
    )

# -------------------------------------------------------------------
# C2 전용 헬퍼
# -------------------------------------------------------------------
def _find_col_index(keys: List[str], name: str, extra_alias: List[str] = []) -> int:
    """헤더 키 목록(keys=header_key 적용된 리스트)에서 name 또는 alias를 찾음"""
    tgt = header_key(name)
    aliases = [header_key(a) for a in extra_alias] + [tgt]
    # 정확 매칭
    for i, k in enumerate(keys):
        if k in aliases:
            return i
    # 부분 매칭
    for i, k in enumerate(keys):
        if any(a and a in k for a in aliases):
            return i
    return -1

def _pick_index_by_candidates(header_row: List[str], candidates: List[str]) -> int:
    """헤더 행에서 후보명(정규화)으로 가장 그럴듯한 인덱스 찾기 (정확 > 부분 일치)"""
    keys = [header_key(x) for x in header_row]
    # 정확 일치
    for cand in candidates:
        ck = header_key(cand)
        for i, k in enumerate(keys):
            if k == ck:
                return i
    # 부분 일치
    for cand in candidates:
        ck = header_key(cand)
        if not ck:
            continue
        for i, k in enumerate(keys):
            if ck in k:
                return i
    return -1

def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    """
    Reference 시트의 TemplateDict 탭에서
    TopLevel(첫 컬럼) → [헤더들] 매핑을 로드.
    - 탭이 없거나 데이터가 없으면 명확한 에러로 중단(디버깅 용이)
    """
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    try:
        ws = ref.worksheet(ref_sheet)
    except WorksheetNotFound:
        raise WorksheetNotFound(f"Required sheet '{ref_sheet}' not found in '{ref.title}'")

    vals = with_retry(lambda: ws.get_all_values()) or []

    print(f"[TDict][DEBUG] ref='{ref.title}' tab='{ref_sheet}' rows={len(vals)}")
    try:
        print("[TDict][DEBUG] tabs in ref (head):", [w.title for w in ref.worksheets()][:10])
    except Exception:
        pass

    if len(vals) < 2:
        raise RuntimeError(
            f"TemplateDict has no data (rows={len(vals)}) in '{ref.title}'. "
            f"Tab '{ref_sheet}' must have header + at least 1 data row."
        )

    out: Dict[str, List[str]] = {}
    for r in vals[1:]:
        if not r or not (r[0] or "").strip():
            continue
        out[header_key(r[0])] = [str(x or "").strip() for x in r[1:]]
    if not out:
        raise RuntimeError("TemplateDict parsed to empty dict. Check first-column values.")
    return out

def _collect_indices(header_row: List[str]) -> Dict[str, int]:
    keys = [header_key(x) for x in header_row]

    def idx(name: str, aliases: List[str] = []) -> int:
        return _find_col_index(keys, name, extra_alias=aliases)

    return {
        "create": idx("create", ["use", "apply"]),
        "variation": idx("variation", ["variationno", "variationintegrationno", "var code", "variation code", "parent sku", "parentsku"]),
        "sku": idx("sku", ["seller_sku"]),
        "brand": idx("brand", ["brandname"]),
        "option_eng": idx("option(eng)", ["optioneng", "option", "option1", "option name", "option for variation 1"]),
        "prod_name": idx("product name", ["item(eng)", "itemeng", "name"]),
        "desc": idx("description", ["product description"]),
        "category": idx("category"),
        "detail_idx": idx("details index", ["detail image count", "details count", "detailindex"]),
    }

# -------------------------------------------------------------------
# C1: TEM_OUTPUT 시트 준비/초기화
# -------------------------------------------------------------------
def run_step_C1(sh: gspread.Spreadsheet, ref: Optional[gspread.Spreadsheet]) -> None:
    print("\n[ Create ] Step C1: Prepare TEM_OUTPUT sheet ...")
    tem_name = get_tem_sheet_name()
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
    except Exception:
        tem_ws = with_retry(lambda: sh.add_worksheet(title=tem_name, rows=2000, cols=200))
    with_retry(lambda: tem_ws.update(values=[[""]], range_name="A1"))
    print("C1 Done.")

# -------------------------------------------------------------------
# C2: Collection → TEM_OUTPUT
# -------------------------------------------------------------------
def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet) -> None:
    print("\n[ Create ] Step C2: Build TEM from Collection ...")
    tem_name = get_tem_sheet_name()

    # 1) TemplateDict 로드
    template_dict = _load_template_dict(ref)
    print(f"[C2][DEBUG] TemplateDict loaded. top-level count = {len(template_dict)}")

    # 2) Collection 탭 유연 탐색 (+ 환경변수 오버라이드)
    coll_name = get_env("COLLECTION_SHEET_NAME", "Collection")
    aliases = [coll_name, "collection", "collections", "raw", "sheet1", "상품정보", "상품", "수집", "수집데이터"]
    try:
        coll_ws = _find_worksheet_by_alias(sh, aliases)
    except WorksheetNotFound as e:
        raise WorksheetNotFound(
            f"[C2] Could not find Collection tab. tried={aliases}, existing={[w.title for w in sh.worksheets()]}"
        ) from e

    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []
    print(f"[C2][DEBUG] Collection rows = {len(coll_vals)} (header cols = {len(coll_vals[0]) if coll_vals else 0})")

    if not coll_vals or len(coll_vals) < 2:
        print("[C2] Collection 비어 있음. (rows < 2)")
        return

    # 3) 헤더 인덱스 수집
    colmap = _collect_indices(coll_vals[0])
    print("[C2][DEBUG] colmap =", colmap)

    create_i    = colmap["create"]     if colmap["create"]    >= 0 else -1
    variation_i = colmap["variation"]  if colmap["variation"] >= 0 else 1
    sku_i       = colmap["sku"]        if colmap["sku"]       >= 0 else 2
    brand_i     = colmap["brand"]      if colmap["brand"]     >= 0 else 3
    option_i    = colmap["option_eng"] if colmap["option_eng"]>= 0 else 5
    pname_i     = colmap["prod_name"]  if colmap["prod_name"] >= 0 else 7
    desc_i      = colmap["desc"]       if colmap["desc"]      >= 0 else 9
    category_i  = colmap["category"]   if colmap["category"]  >= 0 else 10
    dcount_i    = colmap["detail_idx"] if colmap["detail_idx"]>= 0 else 11

    if create_i == -1:
        print("[C2] ERROR: 'create' column not found (aliases: create, use, apply). Check Collection header.")
        return

    # 4) 그룹 별 forward fill
    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]

    def _reset_when(row: List[str]) -> bool:
        return not any(str(x or "").strip() for x in row)

    ff_vals = forward_fill_by_group(
        [list(r) for r in coll_vals],
        group_idx=variation_i,
        fill_col_indices=fill_cols,
        reset_when=_reset_when,
    )
    print(f"[C2][DEBUG] forward-filled rows = {len(ff_vals)}")

    create_true_count = sum(1 for r in ff_vals[1:] if _is_true((r[create_i] if create_i < len(r) else "")))
    print(f"[C2][DEBUG] Rows where 'create' is True (final check): {create_true_count}")

    # 5) 버킷 빌드
    buckets: Dict[str, Dict[str, List]] = {}
    failures: List[List[str]] = []
    category_missing_count = 0
    toplevel_missing_count = 0

    def set_if_exists(headers: List[str], row: List[str], name: str, value: str):
        idx = _find_col_index([header_key(h) for h in headers], name)
        if idx >= 0:
            row[idx] = value

    created_rows = 0
    failed_categories_log: List[str] = []

    for r in range(1, len(ff_vals)):
        row = ff_vals[r]
        if not _is_true(row[create_i] if create_i < len(row) else ""):
            continue

        variation = (row[variation_i] if variation_i < len(row) else "").strip()
        sku       = (row[sku_i]       if sku_i       < len(row) else "").strip()
        brand     = (row[brand_i]     if brand_i     < len(row) else "").strip()
        opt1      = (row[option_i]    if option_i    < len(row) else "").strip()
        pname     = (row[pname_i]     if pname_i     < len(row) else "").strip()
        desc      = (row[desc_i]      if desc_i      < len(row) else "").strip()
        category  = (row[category_i]  if category_i  < len(row) else "").strip()

        if not category:
            pid = variation or sku or f"ROW{r+1}"
            failures.append([pid, "", pname, "CATEGORY_MISSING", f"row={r+1}"])
            category_missing_count += 1
            continue

        top_category_raw = top_of_category(category)
        top_norm = header_key(top_category_raw or "")
        headers = template_dict.get(top_norm)

        if not headers:
            failures.append(["", category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND", f"top={top_category_raw} (Key: {top_norm})"])
            toplevel_missing_count += 1
            if top_category_raw not in failed_categories_log:
                failed_categories_log.append(f"'{top_category_raw}' (Key: '{top_norm}')")
            continue

        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)
        set_if_exists(headers, tem_row, "variation name1", "Options")
        set_if_exists(headers, tem_row, "parent sku", variation)
        set_if_exists(headers, tem_row, "variation integration no.", variation)
        set_if_exists(headers, tem_row, "option for variation 1", opt1)
        set_if_exists(headers, tem_row, "sku", sku)
        set_if_exists(headers, tem_row, "brand", brand)

        pid = variation or sku or f"ROW{r+1}"
        b = buckets.setdefault(top_norm, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)
        created_rows += 1

    print(f"[C2][DEBUG] Filtered summary: Created={created_rows}, Category Missing={category_missing_count}, Toplevel Not Found={toplevel_missing_count}")
    print(f"[C2][DEBUG] Total failures: {len(failures)}")
    if failed_categories_log:
        print("\n[C2][ERROR] TEMPLATE DICT MATCH FAILURES:")
        for log in failed_categories_log:
            print(f"  → Missing Top-Level Key: {log}")
        print("---------------------------------------")

    # 6) TEM_OUTPUT 갱신
    out_matrix: List[List[str]] = []
    for top_key, pack in buckets.items():
        out_matrix.append(["PID"] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])
        print(f"[C2][DEBUG] bucket[{top_key}] rows = {len(pack['rows'])}")

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))
        print(f"[C2] TEM_OUTPUT updated. rows={len(out_matrix)} cols={max_cols}")
    else:
        print("[C2] out_matrix is empty → TEM_OUTPUT 미갱신 (TemplateDict/Collection 확인 필요)")

    print("C2 Done.")

# -------------------------------------------------------------------
# C3: FDA Registration No. 채우기
# -------------------------------------------------------------------
def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False) -> None:
    print("\n[ Create ] Step C3: Fill FDA Code ...")

    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"  # 정책값

    # 대상 카테고리 로드
    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values("A:A", value_render_option="UNFORMATTED_VALUE"))
        target_categories = {str(r[0]).strip().lower() for r in (fda_vals_2d or []) if r and str(r[0]).strip()}
    except Exception as e:
        print(f"[C3] '{fda_sheet_name}' 탭 로드 실패: {e}. Step C3 스킵.")
        return

    # TEM 로드
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[C3] {tem_name} 탭 없음. Step C1/C2 선행 필요.")
        return
    if not vals:
        return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

    for r0, row in enumerate(vals):
        # 헤더 행 (B열 = Category)
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue

        if not current_keys or col_fda_B < 0 or col_category_B < 0:
            continue

        # Category 값 (헤더 제외 기준 → 시트 컬럼은 +1)
        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        category_val_normalized = category_val_raw.lower()

        if category_val_normalized and category_val_normalized in target_categories:
            c_fda_sheet_col = col_fda_B + 2  # 시트 실제 컬럼(B=2) 보정
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()
            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C3 Done. FDA codes applied: {len(updates)} cells.")

# -------------------------------------------------------------------
# C4: (보류) 가격 매핑
# -------------------------------------------------------------------
def run_step_C4_prices(sh: gspread.Spreadsheet) -> None:
    print("\n[ Create ] Step C4: Prices Mapping ...")

    tem_name = get_tem_sheet_name()

    # 1) 워크시트 핸들
    tem_ws = safe_worksheet(sh, tem_name)
    try:
        coll_ws = _find_worksheet_by_alias(
            sh, ["Collection", "collection", "collections", "raw", "sheet1", "상품정보", "상품", "수집", "수집데이터"]
        )
    except Exception:
        coll_ws = safe_worksheet(sh, "Collection")

    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []

    if not tem_vals or not coll_vals:
        print("[C4] TEM/Collection 비어 있음. 스킵.")
        return

    # 2) Collection에서 Parent SKU(=variation 별칭)와 가격 컬럼 찾기
    coll_hdr = coll_vals[0]
    coll_keys = [header_key(x) for x in coll_hdr]

    def cidx(name, aliases=[]):
        return _find_col_index(coll_keys, name, extra_alias=aliases)

    ix_parent = cidx("parent sku", ["parentsku", "variation", "variationintegrationno", "variation no", "variation code"])
    ix_price  = cidx("price", ["sale price", "selling price", "판매가"])
    ix_orig   = cidx("original price", ["list price", "msrp", "정가", "원가", "originalprice"])

    if ix_parent == -1 or (ix_price == -1 and ix_orig == -1):
        print("[C4] 가격 맵핑을 위한 컬럼(Parent SKU/Price)이 Collection에 없습니다. 스킵.")
        return

    price_by_parent: Dict[str, Dict[str, str]] = {}
    for r in range(1, len(coll_vals)):
        row = coll_vals[r]
        if not row:
            continue
        parent = (row[ix_parent] if ix_parent < len(row) else "").strip()
        if not parent:
            continue
        rec = price_by_parent.setdefault(parent, {})
        if ix_price != -1 and ix_price < len(row) and str(row[ix_price]).strip():
            rec["price"] = str(row[ix_price]).strip()
        if ix_orig != -1 and ix_orig < len(row) and str(row[ix_orig]).strip():
            rec["original"] = str(row[ix_orig]).strip()

    if not price_by_parent:
        print("[C4] 가격 데이터가 없습니다. 스킵.")
        return

    # 3) TEM_OUTPUT에서 헤더행들 순회하며 가격 칸 업데이트
    updates: List[Cell] = []
    current_keys = None
    idx_parent_B = idx_varint_B = idx_price_B = idx_orig_B = -1

    for r0, row in enumerate(tem_vals):
        # 헤더 행은 B열에 'Category'
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            idx_parent_B  = _find_col_index(current_keys, "parent sku")
            idx_varint_B  = _find_col_index(current_keys, "variation integration no.", ["variation integration"])
            idx_price_B   = _find_col_index(current_keys, "price", ["selling price", "sale price"])
            idx_orig_B    = _find_col_index(current_keys, "original price", ["list price", "msrp"])
            continue

        if not current_keys:
            continue

        # lookup key: Parent SKU 우선, 없으면 Variation Integration No.
        parent = (row[idx_parent_B + 1] if idx_parent_B != -1 and len(row) > idx_parent_B + 1 else "").strip()
        if not parent:
            parent = (row[idx_varint_B + 1] if idx_varint_B != -1 and len(row) > idx_varint_B + 1 else "").strip()
        if not parent:
            continue

        rec = price_by_parent.get(parent)
        if not rec:
            continue

        # price
        if idx_price_B != -1 and "price" in rec:
            sheet_col = idx_price_B + 2
            cur = (row[sheet_col - 1] if len(row) >= sheet_col else "").strip()
            if cur != rec["price"]:
                updates.append(Cell(row=r0 + 1, col=sheet_col, value=rec["price"]))

        # original price
        if idx_orig_B != -1 and "original" in rec:
            sheet_col = idx_orig_B + 2
            cur = (row[sheet_col - 1] if len(row) >= sheet_col else "").strip()
            if cur != rec["original"]:
                updates.append(Cell(row=r0 + 1, col=sheet_col, value=rec["original"]))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"[C4] Prices mapped. Updates: {len(updates)} cells")


# -------------------------------------------------------------------
# C5 전용 헬퍼
# -------------------------------------------------------------------
def _find_header_row_and_offset(tem_values: List[List[str]]) -> tuple[int, int, Dict[str, int]]:
    """
    TEM_OUTPUT에서 헤더 행과 PID 오프셋, 관심 컬럼 인덱스 맵을 찾는다.
    - 헤더 행 판정 전략을 다층으로 완화:
      1) 기존 방식(맨 앞 'PID' 유무)
      2) B열이 'Category'인 행을 헤더로 간주
      3) base_offset=0/1 양쪽을 모두 시도
    - 컬럼 매칭은 alias를 폭넓게 허용
    - Variation이 없어도 SKU가 있으면 IPv만 부분 업데이트 가능하도록 허용(커버/D이미지는 Variation 필요)
    반환 인덱스는 항상 'PID를 제외한 기준'으로 통일한다.
    """
    if not tem_values:
        raise RuntimeError("TEM_OUTPUT이 비어 있습니다.")

    # 폭넓은 alias 집합
    WANT = {
        "variation": {
            "variationintegrationno", "variationintegrationno.", "variationno", "variationintegration", "variation",
            "variation integration no", "variation integration", "variation code", "variation id"
        },
        "sku": {"sku", "seller_sku", "seller sku", "item sku"},
        "cover": {
            "coverimage", "cover image", "coverimageurl", "cover image url", "cover", "cover url"
        },
        "ipv": {
            "imagepervariation", "image per variation",
            "imageurlpervariation", "image url per variation",
            "ipv", "variation image", "image each variation"
        },
    }

    def _try_parse_row_as_header(row: List[str], base_offset_guess: int) -> Optional[Dict[str, int]]:
        keys = [header_key(x) for x in row[base_offset_guess:]]
        if not keys:
            return None
        ix_map: Dict[str, int] = {}

        # helper: 포함 여부 검사
        def _first_index(matchers: set[str]) -> int:
            # 정확 일치 우선
            for i, k in enumerate(keys):
                if k in matchers:
                    return i
            # 부분 일치 허용
            for i, k in enumerate(keys):
                if any(m for m in matchers if m and m in k):
                    return i
            return -1

        # variation / sku / cover / ipv
        vi = _first_index(WANT["variation"])
        if vi != -1: ix_map["variation"] = vi
        si = _first_index(WANT["sku"])
        if si != -1: ix_map["sku"] = si
        ci = _first_index(WANT["cover"])
        if ci != -1: ix_map["cover"] = ci
        ii = _first_index(WANT["ipv"])
        if ii != -1: ix_map["ipv"] = ii

        # item image 1..8 (정확 매칭 우선, 그다음 부분)
        for n in range(1, 9):
            want_exact = header_key(f"item image {n}")
            found = -1
            for i, k in enumerate(keys):
                if k == want_exact:
                    found = i
                    break
            if found == -1:
                for i, k in enumerate(keys):
                    if want_exact in k:
                        found = i
                        break
            if found != -1:
                ix_map[f"item{n}"] = found

        # 이 행을 헤더로 인정할 조건:
        has_any_image = ("cover" in ix_map) or ("ipv" in ix_map) or any(f"item{n}" in ix_map for n in range(1, 9))
        has_key_for_fill = ("variation" in ix_map) or ("sku" in ix_map)  # 최소한 하나는 있어야 채울 수 있음

        return ix_map if (has_any_image and has_key_for_fill) else None

    # 1) 1차: 기존 로직(맨 앞 'PID' 판단) + base_offset=1
    for r, row in enumerate(tem_values):
        if not row:
            continue
        if header_key(row[0]) == "pid":
            ix_map = _try_parse_row_as_header(row, base_offset_guess=1)
            if ix_map:
                return r, 1, ix_map

    # 2) 2차: B열이 'Category'인 행을 헤더로 가정 + base_offset=1
    for r, row in enumerate(tem_values):
        if len(row) > 1 and header_key(row[1]) == "category":
            ix_map = _try_parse_row_as_header(row, base_offset_guess=1)
            if ix_map:
                return r, 1, ix_map

    # 3) 3차: base_offset=0도 시도 (PID가 진짜로 없게 만든 경우)
    for r, row in enumerate(tem_values):
        if not row:
            continue
        ix_map = _try_parse_row_as_header(row, base_offset_guess=0)
        if ix_map:
            return r, 0, ix_map

    # 실패 시 어떤 키들이 보였는지 힌트를 남김
    sample = next((row for row in tem_values if any(str(c).strip() for c in row)), [])
    seen = [header_key(x) for x in sample]
    raise RuntimeError(
        "TEM_OUTPUT 헤더 행을 찾지 못했습니다 (Variation/이미지 관련 컬럼 누락). "
        f"예시 행 키: {seen[:15]}"
    )

# C5 전용: Collection에서 Variation별 상세이미지 개수 맵 만들기
def _build_details_count_by_var(collection_values: List[List[str]]) -> Dict[str, int]:
    """
    Collection 시트에서 Details Index를 읽어 {variation_no: dcount}를 만든다.
    - 헤더 별칭을 폭넓게 허용 (Details Index / Details / Detail Index / Detail Image Count / Details Count ...)
    - dcount는 0~8로 클램프
    """
    VAR_KEYS = {"variationintegrationno.", "variationno.", "variationintegration", "variation"}
    DET_KEYS = {
        "detailsindex", "details", "detailindex",
        "detailimagecount", "detailscount", "detailcount",
        "detailimages", "detailimage"
    }

    if not collection_values:
        return {}

    # 1행: 헤더
    header = collection_values[0]
    hdr_keys = [header_key(x) for x in header]

    ix_var = ix_det = None
    for i, k in enumerate(hdr_keys):
        if ix_var is None and k in VAR_KEYS: ix_var = i
        if ix_det is None and k in DET_KEYS: ix_det = i

    if ix_var is None or ix_det is None:
        # 헤더가 없으면 D이미지 생성을 생략(커버/IPv는 그대로 처리)
        return {}

    dmap: Dict[str, int] = {}
    for row in collection_values[1:]:
        if not row or len(row) <= max(ix_var, ix_det):
            continue
        var_no = str(row[ix_var]).strip()
        det_raw = str(row[ix_det]).strip()
        if not var_no:
            continue
        try:
            dcount = int(float(det_raw)) if det_raw != "" else 0
        except ValueError:
            dcount = 0
        dmap[var_no] = max(0, min(8, dcount))  # 0~8
    return dmap


# -------------------------------------------------------------------
# C5: Image URL 채우기 (데이터 버전)
# -------------------------------------------------------------------
def run_step_C5_images_values(
    tem_values: List[List[str]],
    collection_values: List[List[str]],
    base_url: str,
    shop_code: str,
) -> List[List[str]]:
    """
    TEM_OUTPUT values(2D 배열)를 입력받아, 이미지 URL 컬럼을 채워서 같은 형태로 반환.
    - PID 유무 자동 대응
    - 있는 컬럼만 부분 업데이트
    - Details Index 폭넓은 별칭 허용
    """
    if not tem_values:
        return tem_values

    base = (base_url or "").rstrip("/") + "/"
    hdr_row, base_offset, ix_map = _find_header_row_and_offset(tem_values)
    dmap = _build_details_count_by_var(collection_values)

    out = list(tem_values)
    for r in range(hdr_row + 1, len(out)):
        row = out[r]
        data = row[base_offset:]
        if not data:
            continue

        var_no = data[ix_map["variation"]].strip() if "variation" in ix_map and ix_map["variation"] < len(data) else ""
        sku    = data[ix_map["sku"]].strip()       if "sku"       in ix_map and ix_map["sku"]       < len(data) else ""
        dcount = dmap.get(var_no, 0)

        # Cover (base/VAR_C_CODE.jpg) — shop_code 필요
        if "cover" in ix_map and ix_map["cover"] < len(data):
            data[ix_map["cover"]] = f"{base}{var_no}_C_{shop_code}.jpg" if (var_no and shop_code) else ""

        # IPv (base/SKU.jpg)
        if "ipv" in ix_map and ix_map["ipv"] < len(data):
            data[ix_map["ipv"]] = f"{base}{sku}.jpg" if sku else ""

        # D1..D8 (base/VAR_Dn.jpg)
        for n in range(1, 9):
            key = f"item{n}"
            if key in ix_map and ix_map[key] < len(data):
                data[ix_map[key]] = f"{base}{var_no}_D{n}.jpg" if (var_no and dcount >= n) else ""

        out[r] = row[:base_offset] + data

    return out

# -------------------------------------------------------------------
# C5: Image URL 채우기 (I/O 래퍼 — 컨트롤러 호환 시그니처)
# -------------------------------------------------------------------
def run_step_C5_images(sh: gspread.Spreadsheet, base_url: str, shop_code: str):
    tem_ws = safe_worksheet(sh, get_tem_sheet_name())
    try:
        coll_ws = _find_worksheet_by_alias(
            sh, ["Collection", "collection", "collections", "raw", "sheet1", "상품정보", "상품", "수집", "수집데이터"]
        )
    except Exception:
        coll_ws = safe_worksheet(sh, "Collection")

    tem_values = with_retry(lambda: tem_ws.get_all_values()) or []
    collection_values = with_retry(lambda: coll_ws.get_all_values()) or []

    new_values = run_step_C5_images_values(
        tem_values=tem_values,
        collection_values=collection_values,
        base_url=base_url,
        shop_code=shop_code,
    )

    if new_values != tem_values:
        end_a1 = rowcol_to_a1(len(new_values), max(len(r) for r in new_values) if new_values else 1)
        with_retry(lambda: tem_ws.update(values=new_values, range_name=f"A1:{end_a1}"))

    print("[C5] Done.")

# -------------------------------------------------------------------
# C6: Stock/Weight/Brand 보정 (MARGIN 시트 기반)
# -------------------------------------------------------------------
def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet) -> None:
    print("\n[ Create ] Step C6: Fill Stock, Weight, Brand ...")
    tem_name = get_tem_sheet_name()
    
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[C6] {tem_name} 탭 없음. Step C1/C2 선행 필요.")
        return

    if not tem_vals:
        print("[C6] TEM_OUTPUT 비어 있음.")
        return

    # 1) MARGIN 시트 로드 (SKU ↔ Weight)
    sku_to_weight: Dict[str, str] = {}
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
        mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
        if len(mg_vals) >= 2:
            idx_mg_sku = _pick_index_by_candidates(mg_vals[0], ["sku", "seller_sku"])
            idx_mg_weight = _pick_index_by_candidates(mg_vals[0], ["weight", "package weight"])
            if idx_mg_sku != -1 and idx_mg_weight != -1:
                for r in range(1, len(mg_vals)):
                    row = mg_vals[r]
                    sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
                    weight = (row[idx_mg_weight] if idx_mg_weight < len(row) else "").strip()
                    if sku and weight:
                        sku_to_weight[sku] = weight
    except WorksheetNotFound:
        print("[C6] MARGIN 시트 없음 → Weight 매핑 건너뜀.")
    except Exception as e:
        print(f"[C6] MARGIN 처리 중 오류: {e}. Weight 매핑 건너뜀.")

    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_stock = idx_t_weight = idx_t_brand = -1

    for r0, row in enumerate(tem_vals):
        # 헤더 행 찾기 (B열='Category')
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku    = _find_col_index(cur_headers, "sku")
            idx_t_stock  = _find_col_index(cur_headers, "stock")
            idx_t_weight = _find_col_index(cur_headers, "weight")
            idx_t_brand  = _find_col_index(cur_headers, "brand")
            continue
            idx_t_days   = _find_col_index(cur_headers, "days to ship", ["days", "leadtime", "handling time"])
            
        if not cur_headers or idx_t_sku == -1:
            continue

        # SKU (시트 인덱스: 헤더 인덱스 + 2)
        sku = (row[idx_t_sku + 1] if len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        # Stock = 1000
        if idx_t_stock != -1:
            val = "1000"
            c_stock_sheet_col = idx_t_stock + 2
            cur = (row[c_stock_sheet_col - 1] if len(row) >= c_stock_sheet_col else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=c_stock_sheet_col, value=val))

        # Brand = 0
        if idx_t_brand != -1:
            val = "0"
            c_brand_sheet_col = idx_t_brand + 2
            cur = (row[c_brand_sheet_col - 1] if len(row) >= c_brand_sheet_col else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=c_brand_sheet_col, value=val))

        # Days to ship = 1
        if idx_t_days != -1:
            val = "1"
            c_days_sheet_col = idx_t_days + 2
            cur = (row[c_days_sheet_col - 1] if len(row) >= c_days_sheet_col else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=c_days_sheet_col, value=val))


        # Weight = MARGIN 매핑
        if idx_t_weight != -1 and sku:
            val = sku_to_weight.get(sku, "")
            if val:
                c_weight_sheet_col = idx_t_weight + 2
                cur = (row[c_weight_sheet_col - 1] if len(row) >= c_weight_sheet_col else "").strip()
                if cur != val:
                    updates.append(Cell(row=r0 + 1, col=c_weight_sheet_col, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C6 Done. Updates: {len(updates)} cells")

# ---------------- C7: Mandatory 기본값 채우기 + 색칠 ----------------
# (필요 import)
from collections import defaultdict
try:
    from .utils_creator import get_bool_env, hex_to_rgb01
except Exception:
    def get_bool_env(name: str, default: bool=False) -> bool:
        v = get_env(name, None)
        if v is None: return default
        return str(v).strip().lower() in {"1","true","t","yes","y","on"}
    def hex_to_rgb01(hx: str) -> dict:
        hx = (hx or "").lstrip("#")
        if len(hx) == 3: hx = "".join(c*2 for c in hx)
        if len(hx) != 6: return {"red":1.0,"green":1.0,"blue":0.8}
        r = int(hx[0:2],16); g = int(hx[2:4],16); b = int(hx[4:6],16)
        return {"red": r/255.0, "green": g/255.0, "blue": b/255.0}

def _norm_cat_for_match(s: str) -> str:
    if not s: return ""
    x = str(s).strip().lower()
    x = x.replace(" - ", "/").replace("-", "/").replace("\\", "/").replace(" / ", "/")
    x = "/".join(seg.strip() for seg in x.split("/") if seg.strip())
    while "//" in x: x = x.replace("//", "/")
    return x

def _read_mandatory_defaults_from_ref(ref) -> Dict[str, Dict[str, str]]:
    def _read_defaults_ws(ws):
        vals = with_retry(lambda: ws.get_all_values()) or []
        if not vals: return {}
        keys = [header_key(x) for x in vals[0]]
        c_idx = _find_col_index(keys, "category")
        a_idx = _find_col_index(keys, "attribute", ["attr","property"])
        d_idx = _find_col_index(keys, "defaultvalue", ["default"])
        if min(c_idx, a_idx, d_idx) < 0: return {}
        out = {}
        for r in range(1, len(vals)):
            row = vals[r]
            cat  = (row[c_idx] if c_idx < len(row) else "").strip()
            attr = (row[a_idx] if a_idx < len(row) else "").strip()
            dval = (row[d_idx] if d_idx < len(row) else "").strip()
            if cat and attr:
                out.setdefault(_norm_cat_for_match(cat), {})[header_key(attr)] = dval
        return out
    sheets = with_retry(lambda: ref.worksheets())
    defaults_map: Dict[str, Dict[str, str]] = {}
    for ws in sheets:
        if ws.title.lower().startswith("mandatorydefaults_"):
            for k, d in _read_defaults_ws(ws).items():
                defaults_map.setdefault(k, {}).update(d)
    return defaults_map

def _read_category_mandatory_flags(ref) -> Dict[str, List[str]]:
    cat_props_ws = safe_worksheet(ref, get_env("CAT_PROPS_SHEET", "cat props"))
    vals = with_retry(lambda: cat_props_ws.get_all_values()) or []
    out = {}
    if vals:
        hdr_keys = [header_key(x) for x in vals[0]]
        for r in range(1, len(vals)):
            row = vals[r]
            cat = (row[0] if len(row)>0 else "").strip()
            if not cat: continue
            mand = [hdr_keys[j] for j, cell in enumerate(row) if str(cell).strip().lower()=="mandatory"]
            if mand:
                out[_norm_cat_for_match(cat)] = mand
    return out

def run_step_C7_mandatory_defaults(sh, ref):
    print("\n[ Automation ] Step C7: Fill Mandatory Defaults...")
    tem_name  = get_tem_sheet_name()
    color_hex = get_env("COLOR_HEX_MANDATORY", "#FFF9C4")
    overwrite = get_bool_env("OVERWRITE_NONEMPTY", False)

    try:
        tem_ws = safe_worksheet(sh, tem_name)
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음. C2 이후 실행 필요."); return

    defaults_map = _read_mandatory_defaults_from_ref(ref)
    catprops_map = _read_category_mandatory_flags(ref)

    vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not vals: print("[!] TEM_OUTPUT 비어 있음."); return

    # sheetId (색칠용)
    try:
        meta = with_retry(lambda: sh.fetch_sheet_metadata())
        sheet_id = next((s["properties"]["sheetId"] for s in meta["sheets"] 
                        if s["properties"]["title"] == tem_name), None)
    except Exception:
        sheet_id = None

    updates: List[Cell] = []
    color_ranges_by_col = defaultdict(list)
    current_hdr_keys = None
    total_filled = 0

    def _find_defaults(cat_raw: str) -> Dict[str, str]:
        if not cat_raw: return {}
        nc = _norm_cat_for_match(cat_raw)
        if nc in defaults_map: return defaults_map[nc]
        for k in defaults_map.keys():
            if nc.endswith(k) or k.endswith(nc): return defaults_map[k]
        for k in defaults_map.keys():
            if ("/"+k+"/") in ("/"+nc+"/"): return defaults_map[k]
        return {}

    def _find_mand(cat_raw: str) -> List[str]:
        if not cat_raw: return []
        nc = _norm_cat_for_match(cat_raw)
        if nc in catprops_map: return catprops_map[nc]
        for k in catprops_map.keys():
            if nc.endswith(k) or k.endswith(nc): return catprops_map[k]
        for k in catprops_map.keys():
            if ("/"+k+"/") in ("/"+nc+"/"): return catprops_map[k]
        return []

    for r0, row in enumerate(vals):
        # 헤더 인지 판별 (B열 'Category')
        if (row[1] if len(row)>1 else "").strip().lower() == "category":
            current_hdr_keys = [header_key(h) for h in row[1:]]
            continue
        if not current_hdr_keys: 
            continue

        pid = (row[0] if len(row)>0 else "").strip()
        cat = (row[1] if len(row)>1 else "").strip()
        if not pid or not cat: 
            continue

        # mandatory 색칠
        mand_list = _find_mand(cat)
        if mand_list and sheet_id is not None:
            for attr_norm in mand_list:
                j = _find_col_index(current_hdr_keys, attr_norm)
                if j >= 0:
                    color_ranges_by_col[j].append((r0, r0+1))

        # 기본값 채우기
        defaults = _find_defaults(cat)
        for attr_norm, dval in defaults.items():
            if not dval: continue
            j = _find_col_index(current_hdr_keys, attr_norm)
            if j < 0: continue
            col_1based = j + 2
            cur = (row[col_1based - 1] if len(row) >= col_1based else "").strip()
            if not cur or overwrite:
                updates.append(Cell(row=r0 + 1, col=col_1based, value=dval))
                total_filled += 1

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    # 색칠 요청
    def _merge(spans):
        if not spans: return []
        spans.sort()
        merged = [spans[0]]
        for s,e in spans[1:]:
            ls,le = merged[-1]
            if s <= le: merged[-1] = (ls, max(le,e))
            else: merged.append((s,e))
        return merged

    requests = []
    color = hex_to_rgb01(color_hex)
    if sheet_id is not None:
        for j, spans in color_ranges_by_col.items():
            for s,e in _merge(spans):
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": s, "endRowIndex": e,
                            "startColumnIndex": 1 + j, "endColumnIndex": 1 + j + 1
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": color}},
                        "fields": "userEnteredFormat.backgroundColor"
                    }
                })
        if requests:
            with_retry(lambda: sh.batch_update({"requests": requests}))

    print("========== C7 Mandatory Defaults RESULT ==========")
    print(f"채워진 셀 수: {total_filled:,}")
    print(f"색칠된 'mandatory' 열 개수: {len(color_ranges_by_col):,}")
    print("Step C7: Fill Mandatory Defaults Finished.")



# -------------------------------------------------------------------
# Export helpers (xlsx / csv)
# -------------------------------------------------------------------
def export_tem_xlsx(sh: gspread.Spreadsheet) -> Optional[BytesIO]:
    """
    TEM_OUTPUT 시트를 TopLevel Category 단위로 분할하여 Excel(xlsx) 파일 반환.
    - A열 PID 제거, Category 형식 정규화 포함.
    """
    if not sh:
        return None
    tem_name = get_tem_sheet_name()
    try:
        tem_ws = safe_worksheet(sh, tem_name)
    except WorksheetNotFound:
        return None

    all_data = with_retry(lambda: tem_ws.get_all_values())
    if not all_data:
        return None

    df = pd.DataFrame(all_data)
    for c in df.columns:
        df[c] = df[c].astype(str)
    
    header_mask = df.iloc[:, 1].str.lower().eq("category")
    header_indices = df.index[header_mask].tolist()
    if not header_indices:
        print("[!] TEM_OUTPUT 헤더 행(Category)을 찾을 수 없습니다.")
        return None

    output = BytesIO()

    try:
        import xlsxwriter  # noqa: F401
        engine = "xlsxwriter"
    except ImportError:
        try:
            import openpyxl  # noqa: F401
            engine = "openpyxl"
        except ImportError:
            print("[!] xlsx 생성용 라이브러리(xlsxwriter/openpyxl)가 없습니다.")
            return None

    with pd.ExcelWriter(output, engine=engine) as writer:
        for i, header_index in enumerate(header_indices):
            start_row = header_index + 1
            end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
            if start_row >= end_row:
                continue

            header_row = df.iloc[header_index, 1:]
            chunk_df = df.iloc[start_row:end_row, 1:].copy()

            # Category 표준화
            if not chunk_df.empty and chunk_df.shape[1] > 0 and header_key(header_row.iloc[0]) == "category":
                chunk_df.iloc[:, 0] = chunk_df.iloc[:, 0].astype(str).str.replace(r"\s*-\s*", "-", regex=True)

            columns = header_row.astype(str).tolist()
            if len(columns) != chunk_df.shape[1]:
                if len(columns) < chunk_df.shape[1]:
                    columns += [f"col_{k}" for k in range(len(columns), chunk_df.shape[1])]
                else:
                    columns = columns[: chunk_df.shape[1]]
            chunk_df.columns = columns

            cat_col_name = next((c for c in columns if c.lower() == "category"), None)
            first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"
            top_level_name = top_of_category(first_cat) or "UNKNOWN"
            sheet_name = re.sub(r"[\s/\\*?:\\[\\]]", "_", str(top_level_name).title())[:31]

            chunk_df.to_excel(writer, sheet_name=sheet_name, index=False)

    output.seek(0)
    print("Final template file generated successfully (xlsx).")
    return output

def export_tem_csv(sh: gspread.Spreadsheet) -> Optional[bytes]:
    """
    TEM_OUTPUT 시트를 CSV(bytes)로 반환.
    - A열 PID 제거 및 Category 정규화 포함.
    """
    if not sh:
        return None
    try:
        ws = safe_worksheet(sh, "TEM_OUTPUT")
        vals = with_retry(lambda: ws.get_all_values()) or []
        if not vals:
            return None

        processed_vals = []
        current_headers = None
        for row in vals:
            if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                current_headers = row[1:]
                processed_vals.append(current_headers)
                continue
            
            if current_headers and len(row) > 1:
                data_row = row[1:]
                if len(data_row) > 0 and header_key(current_headers[0]) == "category":
                    data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                processed_vals.append(data_row)
            elif len(row) > 0:
                processed_vals.append(row[1:])

        if not processed_vals:
            return None
            
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(processed_vals)
        return buf.getvalue().encode("utf-8-sig")
    except Exception as e:
        print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
        return None

# -------------------------------------------------------------------
# 호환용 별칭 (기존 호출부가 기대하는 이름 유지)
# -------------------------------------------------------------------
run_c1_collect = run_step_C1
run_c2_tem = run_step_C2
run_c3_fda = run_step_C3_fda
run_c4_price = run_step_C4_prices
run_c5_images = run_step_C5_images
run_c6_swb = run_step_C6_stock_weight_brand
run_c7_mandatory = run_step_C7_mandatory_defaults

