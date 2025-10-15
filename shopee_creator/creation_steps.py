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
import pandas as pd  # 명시적 임포트

# ⚠️ 중요: utils_creator.py가 join_url을 포함하고 있을 수 있으므로 임포트하지 않습니다.
from .utils_creator import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, get_env,
    forward_fill_by_group, # join_url 제거됨
    extract_sheet_id, _is_true # 🚨 _is_true 임포트
)


# -------------------------------------------------------------------
# 내부 헬퍼 (C5용)
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


from gspread.exceptions import WorksheetNotFound

def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    """
    Reference 시트의 TemplateDict 탭에서
    TopLevel(첫 컬럼) → [헤더들] 매핑을 로드.
    - 탭이 없거나 데이터가 없으면 명확한 에러로 중단(디버깅 용이)
    """
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")

    # 탭은 반드시 존재해야 함: 없으면 바로 예외
    try:
        ws = ref.worksheet(ref_sheet)
    except WorksheetNotFound:
        raise WorksheetNotFound(f"Required sheet '{ref_sheet}' not found in '{ref.title}'")

    vals = with_retry(lambda: ws.get_all_values()) or []

    # [DEBUG] 디버그 로그는 유지 (TemplateDict 로드 결과 확인)
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
        # 헤더 정규화는 필수: TemplateDict의 키는 header_key(top_of_category(...))로 찾음
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
        "variation": idx("variation", ["variationno", "variationintegrationno", "var code", "variation code"]),
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
        # 시트가 없거나 클리어 권한이 없을 때(403)를 대비하여 시트 추가 재시도
        tem_ws = with_retry(lambda: sh.add_worksheet(title=tem_name, rows=2000, cols=200))
    with_retry(lambda: tem_ws.update(values=[[""]], range_name="A1"))
    print("C1 Done.")


# -------------------------------------------------------------------
# C2: Collection → TEM_OUTPUT (버킷 생성 + Variation 그룹 공란 보정)
# -------------------------------------------------------------------

def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet) -> None:
    print("\n[ Create ] Step C2: Build TEM from Collection ...")
    tem_name = get_tem_sheet_name()

    template_dict = _load_template_dict(ref)
    print(f"[C2][DEBUG] TemplateDict loaded. top-level count = {len(template_dict)}")

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []

    # [DEBUG] Collection 데이터 유무/헤더 길이 확인
    print(f"[C2][DEBUG] Collection rows = {len(coll_vals)}"
          f" (header cols = {len(coll_vals[0]) if coll_vals else 0})")

    if not coll_vals or len(coll_vals) < 2:
        print("[C2] Collection 비어 있음. (rows < 2)")
        return

    colmap = _collect_indices(coll_vals[0])
    # [DEBUG] 주요 컬럼 인덱스 덤프
    print("[C2][DEBUG] colmap =", colmap)

    # 인덱스가 없을 경우 -1을 유지
    create_i   = colmap["create"]    if colmap["create"]    >= 0 else -1
    variation_i= colmap["variation"] if colmap["variation"] >= 0 else 1
    sku_i      = colmap["sku"]       if colmap["sku"]       >= 0 else 2
    brand_i    = colmap["brand"]     if colmap["brand"]     >= 0 else 3
    option_i   = colmap["option_eng"]if colmap["option_eng"]>= 0 else 5
    pname_i    = colmap["prod_name"] if colmap["prod_name"] >= 0 else 7
    desc_i     = colmap["desc"]      if colmap["desc"]      >= 0 else 9
    category_i = colmap["category"]  if colmap["category"]  >= 0 else 10
    dcount_i   = colmap["detail_idx"]if colmap["detail_idx"]>= 0 else 11
    
    # create_i가 -1이면 데이터가 없거나 헤더 문제로 처리 불가
    if create_i == -1:
        print("[C2] ERROR: 'create' column not found (aliases: create, use, apply). Check Collection sheet header.")
        return

    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]

    def _reset_when(row: List[str]) -> bool:
        return not any(str(x or "").strip() for x in row)

    ff_vals = forward_fill_by_group(
        [list(r) for r in coll_vals],
        group_idx=variation_i,
        fill_col_indices=fill_cols,
        reset_when=_reset_when,
    )

    # [DEBUG] forward fill 후 데이터 샘플
    print(f"[C2][DEBUG] forward-filled rows = {len(ff_vals)}")

    # 최종 유효 행 카운트 (디버그 용)
    create_true_count = sum(
        1 for r in ff_vals[1:] 
        if _is_true((r[create_i] if create_i < len(r) else ""))
    )
    print(f"[C2][DEBUG] Rows where 'create' is True (final check): {create_true_count}")
    
    buckets: Dict[str, Dict[str, List]] = {}
    failures: List[List[str]] = []
    category_missing_count = 0
    toplevel_missing_count = 0


    def set_if_exists(headers: List[str], row: List[str], name: str, value: str):
        idx = _find_col_index([header_key(h) for h in headers], name)
        if idx >= 0:
            row[idx] = value

    created_rows = 0

    # 실패 시 로그를 바로 출력할 리스트
    failed_categories_log: List[str] = []

    for r in range(1, len(ff_vals)):
        row = ff_vals[r]
        # 🚨 _is_true 함수 사용
        if not _is_true(row[create_i] if create_i < len(row) else ""):
            continue  # create=False 는 스킵

        # 컬럼 값 추출 (인덱스 체크 포함)
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
        
        # utils_creator.py에서 수정된 top_of_category 함수를 사용하여 순수 카테고리 이름 추출
        top_category_raw = top_of_category(category) 
        top_norm = header_key(top_category_raw or "")
        
        # TemplateDict에서 헤더 매핑 시도
        headers = template_dict.get(top_norm)

        if not headers:
            failures.append(["", category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND",
                             f"top={top_category_raw} (Key: {top_norm})"])
            toplevel_missing_count += 1
            # 🚨 [강제 디버그 로그 추가] 매칭 실패한 카테고리를 로그 리스트에 추가
            if top_category_raw not in failed_categories_log:
                 failed_categories_log.append(f"'{top_category_raw}' (Key: '{top_norm}')")
            continue

        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)
        set_if_exists(headers, tem_row, "variation name1", "Options")
        set_if_exists(headers, tem_row, "option for variation 1", opt1)
        set_if_exists(headers, tem_row, "sku", sku)
        set_if_exists(headers, tem_row, "brand", brand)

        pid = variation or sku or f"ROW{r+1}"
        b = buckets.setdefault(top_norm, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)
        created_rows += 1

    # 최종 디버그 로그 출력 (필터링 결과 요약)
    print(f"[C2][DEBUG] Filtered summary: Created={created_rows}, Category Missing={category_missing_count}, Toplevel Not Found={toplevel_missing_count}")
    print(f"[C2][DEBUG] Total failures (logged to failure list): {len(failures)}")

    # 🚨 [추가된 강제 디버그 로그 출력]
    if failed_categories_log:
         print("\n[C2][ERROR] TEMPLATE DICT MATCH FAILURES:")
         for log in failed_categories_log:
             print(f"  → Missing Top-Level Key: {log}")
         print("---------------------------------------")


    out_matrix: List[List[str]] = []
    for top_key, pack in buckets.items():
        out_matrix.append(["PID"] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])
        # [DEBUG] 버킷별 행수
        print(f"[C2][DEBUG] bucket[{top_key}] rows = {len(pack['rows'])}")

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        # TEM_OUTPUT 시트 업데이트
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))
        print(f"[C2] TEM_OUTPUT updated. rows={len(out_matrix)} cols={max_cols}")
    else:
        print("[C2] out_matrix is empty → TEM_OUTPUT 미갱신 (TemplateDict/Collection 확인 필요)")

    # TODO: failures 기록 시트 처리(필요시)
    print(f"C2 Done. Buckets: {len(buckets)}")

# -------------------------------------------------------------------
# C3: FDA Registration No. 채우기
# -------------------------------------------------------------------

def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False) -> None:
    print("\n[ Create ] Step C3: Fill FDA Code ...")

    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"  # 고정값 정책

    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        # A열 카테고리 로드
        fda_vals_2d = with_retry(lambda: fda_ws.get_values("A:A", value_render_option="UNFORMATTED_VALUE"))
        # 로드된 카테고리 리스트를 정규화하여 셋(set)으로 만듦
        # 🚨 TEM_OUTPUT의 값과 동일하게 정규화
        target_categories = {str(r[0]).strip().lower() for r in (fda_vals_2d or []) if r and str(r[0]).strip()}
    except Exception as e:
        print(f"[!] '{fda_sheet_name}' 탭 로드 실패: {e}. Step C3 건너<binary data, 2 bytes><binary data, 2 bytes><binary data, 2 bytes>니다.")
        return

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음. Step C1/C2 선행 필요.")
        return

    if not vals:
        return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

    # TEM_OUTPUT 데이터 순회
    for r0, row in enumerate(vals):
        # 헤더 행 찾기
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue
        # 헤더를 찾지 못했거나 필수 컬럼이 없으면 스킵
        if not current_keys or col_fda_B < 0 or col_category_B < 0:
            continue

        pid = (row[0] if len(row) > 0 else "").strip()
        if not pid:
            continue

        # Category 값 추출 (헤더 제외한 데이터 행의 인덱스 기준)
        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        
        # 카테고리 정규화 (전체 경로를 소문자로 사용)
        category_val_normalized = category_val_raw.lower()

        # FDA 대상 카테고리인지 확인
        if category_val_normalized and category_val_normalized in target_categories:
            # FDA 컬럼의 실제 시트 컬럼 인덱스 (B열 기준 +2)
            c_fda_sheet_col = col_fda_B + 2
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()
            
            # FDA 값이 비어 있거나 덮어쓰기 옵션이 켜져 있을 경우 업데이트
            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C3 Done. FDA codes applied: {len(updates)} cells.")


# -------------------------------------------------------------------
# C4: (보류) 가격 매핑
# -------------------------------------------------------------------

def run_step_C4_prices(sh: gspread.Spreadsheet) -> None:
    # TODO: 가격 매핑 로직(필요 시 구현)
    print("\n[ Create ] Step C4: Prices (Skipped/Placeholder)")
    pass


# === C5 Light: Image URL 채우기 (붙여넣기/통교체용) ===
# - Base URL을 사전 보정하여 슬래시 오류를 방지합니다.
# - 시트 접근 시 오류 처리(try/except)를 적용하여 안정성을 확보합니다.

from typing import List, Dict, Tuple

def _key(s: str) -> str:
    """헤더/키 정규화: 소문자, 공백/언더스코어 제거."""
    if s is None:
        return ""
    return "".join(str(s).strip().lower().replace("_", " ").split())

def _find_header_row_and_offset(tem_values: List[List[str]]) -> Tuple[int, int, Dict[str, int]]:
    """
    TEM_OUTPUT에서 헤더 행과 PID 오프셋, 그리고 관심 컬럼 인덱스 맵을 찾는다.
    - PID가 A열에 있으면 base_offset=1, 아니면 0
    - 인덱스는 항상 'PID를 제외한' 기준(=데이터 접근 인덱스)으로 보정하여 반환한다.
      예: 실제 시트 컬럼이 [PID, Category, SKU, ...] 이면, 여기서는 Category가 0, SKU가 1이 된다.
    """
    # 요구 컬럼(템플릿 기준) 키
    WANT = {
        "variation": {"variationintegrationno.", "variationno.", "variationintegration"},  # Variation Integration No. 포함
        "sku": {"sku"},
        "cover": {"coverimage", "coverimageurl", "cover img", "cover"},
        "ipv": {"imagepervariation", "imageurlpervariation", "image per variation"},
        # item images: item image 1..8
    }

    for r, row in enumerate(tem_values):
        if not row:
            continue
        # PID 존재 여부 판단
        first_key = _key(row[0]) if len(row) > 0 else ""
        base_offset = 1 if first_key in {"pid"} else 0

        # 헤더 키 배열 (PID 제외 시점부터 만들기)
        hdr_cells = row[base_offset:]
        keys = [_key(x) for x in hdr_cells]

        # 필요한 컬럼 후보들을 스캔
        ix_map: Dict[str, int] = {}
        # Variation
        for i, k in enumerate(keys):
            if k in WANT["variation"]:
                ix_map["variation"] = i
                break
        # SKU
        for i, k in enumerate(keys):
            if k in WANT["sku"]:
                ix_map["sku"] = i
                break
        # Cover
        for i, k in enumerate(keys):
            if k in WANT["cover"]:
                ix_map["cover"] = i
                break
        # IPv
        for i, k in enumerate(keys):
            if k in WANT["ipv"]:
                ix_map["ipv"] = i
                break
        # Item Image 1..8
        for n in range(1, 9):
            want = _key(f"item image {n}")
            for i, k in enumerate(keys):
                if k == want:
                    ix_map[f"item{n}"] = i
                    break

        # 헤더로 판단: 최소한 Variation과 (Cover/IPv/Item 중 하나)는 있어야 함
        has_variation = "variation" in ix_map
        has_any_image_col = ("cover" in ix_map) or ("ipv" in ix_map) or any(f"item{n}" in ix_map for n in range(1, 9))
        if has_variation and has_any_image_col:
            return r, base_offset, ix_map

    raise RuntimeError("TEM_OUTPUT 헤더 행을 찾지 못했습니다. (Variation/이미지 관련 컬럼이 누락된 듯합니다)")

def _build_details_count_by_var(collection_values: List[List[str]]) -> Dict[str, int]:
    """
    Collection 시트에서 Variation/Details Index를 읽어 {variation_no: dcount} 맵을 만든다.
    - Details Index 별칭을 폭넓게 허용 (C2와 일치 또는 그 이상)
    """
    VAR_KEYS = {"variationintegrationno.", "variationno.", "variationintegration", "variation"}
    DET_KEYS = {
        "detailsindex", "details", "detailindex",
        "detailimagecount", "detailscount", "detailcount", "detailimages", "detailimage",
    }

    if not collection_values:
        return {}

    # 헤더 행 탐색
    header_row = 0
    hdr_keys = [_key(x) for x in collection_values[header_row]]
    ix_var = ix_det = None
    for i, k in enumerate(hdr_keys):
        if ix_var is None and k in VAR_KEYS:
            ix_var = i
        if ix_det is None and k in DET_KEYS:
            ix_det = i
    if ix_var is None or ix_det is None:
        # 최소한 하나라도 없으면 아이템 이미지를 못 채우므로 빈 맵
        return {}

    dmap: Dict[str, int] = {}
    for row in collection_values[header_row + 1:]:
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
        dcount = max(0, min(8, dcount))  # 0~8로 클램프
        dmap[var_no] = dcount

    return dmap

def _compose_urls(base_url: str, shop_code: str, var_no: str, sku: str) -> Dict[str, str]:
    """각 이미지 유형의 URL 패턴을 생성한다."""
    if not base_url:
        base_url = ""
    base = base_url.rstrip("/") + "/"

    urls = {
        "cover": f"{base}{var_no}_C_{shop_code}.jpg" if var_no and shop_code else "",
        "ipv": f"{base}{sku}.jpg" if sku else "",
        # D1..D8은 여기서 만들지 않고 호출부에서 개수에 따라 만듦
    }
    return urls

def run_step_C5_images(
    tem_values: List[List[str]],
    collection_values: List[List[str]],
    base_url: str,
    shop_code: str,
) -> List[List[str]]:
    """
    C5: TEM_OUTPUT의 이미지 관련 컬럼(cover, item 1..8, image per variation)을 일괄 채운다.
    - PID 열 유무에 상관없이 작동
    - 존재하는 컬럼만 부분 업데이트 (일부 컬럼이 없어도 실패하지 않음)
    - Details Index는 다양한 별칭을 허용 (C2와 최소 동일 범위)
    - 반환: 수정된 tem_values (동일 객체를 수정하여 반환)
    """
    if not tem_values:
        return tem_values

    hdr_row, base_offset, ix_map = _find_header_row_and_offset(tem_values)
    dmap = _build_details_count_by_var(collection_values)

    # 데이터 행 루프
    for r in range(hdr_row + 1, len(tem_values)):
        row = tem_values[r]
        # 데이터 접근 인덱스는 항상 base_offset 이후부터 시작
        data = row[base_offset:]
        # 안전 가드
        if not data:
            continue

        # 키 값 가져오기 (없으면 빈 문자열)
        var_no = data[ix_map["variation"]].strip() if "variation" in ix_map and ix_map["variation"] < len(data) else ""
        sku = data[ix_map["sku"]].strip() if "sku" in ix_map and ix_map["sku"] < len(data) else ""

        urls = _compose_urls(base_url, shop_code, var_no, sku)
        dcount = dmap.get(var_no, 0)

        # Cover Image
        if "cover" in ix_map and ix_map["cover"] < len(data):
            data[ix_map["cover"]] = urls["cover"]

        # Image per Variation
        if "ipv" in ix_map and ix_map["ipv"] < len(data):
            data[ix_map["ipv"]] = urls["ipv"]

        # Item Image 1..8
        for n in range(1, 9):
            key = f"item{n}"
            if key in ix_map and ix_map[key] < len(data):
                data[ix_map[key]] = f"{urls['cover'][:-len('_C_'+shop_code+'.jpg')]}_D{n}.jpg" if dcount >= n and var_no else ""

        # 다시 원본 행에 써넣기
        tem_values[r] = row[:base_offset] + data

    return tem_values

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
    idx_t_pid = idx_t_sku = idx_t_stock = idx_t_weight = idx_t_brand = -1

    for r0, row in enumerate(tem_vals):
        # 헤더 행 찾기 (PID, Category, ...)
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            
            # PID 컬럼은 TEM_OUTPUT A열에 있으므로 0번째 인덱스를 찾음
            idx_t_pid = _find_col_index([header_key(row[0])], "pid")
            
            # 나머지 컬럼은 TEM_OUTPUT B열(인덱스 1)부터 시작하므로 B열부터 헤더 목록을 기준으로 찾음
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_stock = _find_col_index(cur_headers, "stock")
            idx_t_weight = _find_col_index(cur_headers, "weight")
            idx_t_brand = _find_col_index(cur_headers, "brand")
            continue
            
        if not cur_headers or idx_t_sku == -1:
            continue

        # SKU 추출 (시트 인덱스: PID=A열, Category=B열, SKU=C열... -> 헤더 인덱스 + 2)
        sku = (row[idx_t_sku + 1] if len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            # SKU가 없는 행은 건너뜀 (Variation도 SKU가 필수로 있어야함)
            continue

        # Stock = 1000 (stock 컬럼의 시트 인덱스: 헤더 인덱스 + 2)
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

        # Weight = MARGIN 매핑 적용
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

    # pandas DataFrame을 사용하여 데이터 처리
    df = pd.DataFrame(all_data)
    # 모든 셀을 문자열로 변환 (혼합 타입을 방지)
    for c in df.columns:
        df[c] = df[c].astype(str)
    
    # 헤더 행 인덱스 찾기 (B열='Category'인 행)
    header_mask = df.iloc[:, 1].str.lower().eq("category")
    header_indices = df.index[header_mask].tolist()
    if not header_indices:
        print("[!] TEM_OUTPUT 헤더 행(Category)을 찾을 수 없습니다.")
        return None

    output = BytesIO()
    
    # xlsxwriter 엔진 임포트 시도
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
            # 데이터 시작 행 (헤더 다음 행)
            start_row = header_index + 1
            # 데이터 끝 행 (다음 헤더 행이거나 데이터프레임의 끝)
            end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
            if start_row >= end_row:
                continue

            # 헤더 행 데이터 (A열 PID 제외, B열부터 시작)
            header_row = df.iloc[header_index, 1:]
            # 데이터 청크 (A열 PID 제외, B열부터 시작, 시작 행부터 끝 행까지)
            chunk_df = df.iloc[start_row:end_row, 1:].copy()

            # Category 표준화 (첫 번째 데이터 컬럼이 Category 컬럼일 경우)
            if not chunk_df.empty and chunk_df.shape[1] > 0 and header_key(header_row.iloc[0]) == "category":
                # 카테고리 중간 공백 및 하이픈 정규화
                chunk_df.iloc[:, 0] = chunk_df.iloc[:, 0].astype(str).str.replace(r"\s*-\s*", "-", regex=True)

            # 컬럼 이름 설정 (헤더 행 사용)
            columns = header_row.astype(str).tolist()
            if len(columns) != chunk_df.shape[1]:
                # 컬럼 개수가 맞지 않을 경우 보정
                if len(columns) < chunk_df.shape[1]:
                    columns += [f"col_{k}" for k in range(len(columns), chunk_df.shape[1])]
                else:
                    columns = columns[: chunk_df.shape[1]]
            chunk_df.columns = columns

            # 시트 이름 설정 (Top-level Category 기반)
            cat_col_name = next((c for c in columns if c.lower() == "category"), None)
            first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"
            top_level_name = top_of_category(first_cat) or "UNKNOWN"
            # 시트 이름은 31자 제한 및 특수문자 제거
            sheet_name = re.sub(r"[\s/\\*?:\\[\\]]", "_", str(top_level_name).title())[:31]

            # 엑셀 파일에 쓰기
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
            # 헤더 행 찾기 (B열='Category'인 행)
            if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                current_headers = row[1:]
                processed_vals.append(current_headers)
                continue
            
            # 데이터 행 처리 (PID A열 제거)
            if current_headers and len(row) > 1:
                data_row = row[1:]
                # 카테고리 정규화 (B열부터 시작하는 데이터에서 0번째 인덱스는 Category)
                if len(data_row) > 0 and header_key(current_headers[0]) == "category":
                    data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                processed_vals.append(data_row)
            elif len(row) > 0:
                # 헤더가 아닌 행 중 데이터가 있는 행 (PID만 남을 경우)
                processed_vals.append(row[1:])

        if not processed_vals:
            return None
            
        # CSV 인코딩 (UTF-8 with BOM)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(processed_vals)
        return buf.getvalue().encode("utf-8-sig")
    except Exception as e:
        print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
        return None


# -------------------------------------------------------------------
# 호환용 별칭 (기존 호출부가 기대하는 이름)
# -------------------------------------------------------------------
run_c1_collect = run_step_C1
run_c2_tem = run_step_C2
run_c3_fda = run_step_C3_fda
run_c4_price = run_step_C4_prices
run_c5_images = run_step_C5_images
run_c6_swb = run_step_C6_stock_weight_brand

def run_c5_images(sh, base_url, shop_code):
    return run_step_C5_images(sh=sh, base_url=base_url, shop_code=shop_code)
