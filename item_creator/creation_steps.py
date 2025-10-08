# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Optional, Any
import io
import csv
import re
from io import BytesIO

import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound
import pandas as pd

# [최종 수정] 모든 공용 유틸리티는 이제 main_controller.py가 로드한
# utils_common (최상위 모듈 또는 item_creator.utils_common)에서
# 직접 가져오거나, item_uploader 대신 item_creator의 utils_common을 사용하도록 변경합니다.
from utils_common import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, authorize_gspread, extract_sheet_id,
    get_env
)
from .utils_common import get_env, join_url, forward_fill_by_group

# _find_col_index 함수가 utils_common.py에 없으므로, 여기에 재정의합니다.
def _find_col_index(keys: List[str], name: str, extra_alias: List[str]=[]) -> int:
    """헤더 키 목록(keys=header_key 적용된 리스트)에서 name 또는 alias를 찾음"""
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
        out[header_key(r[0])] = [str(x or "").strip() for x in row[1:]]
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
    with_retry(lambda: tem_ws.update(values=[[""]], range_name="A1")) 
    print("C1 Done.")


# Collection 헤더 인덱스 수집
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

    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]
    def _reset_when(row: List[str]) -> bool:
        return not any(str(x or "").strip() for x in row)
    
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

        top_norm = header_key(top_of_category(category) or "")
        headers = template_dict.get(top_norm)
        if not headers:
            failures.append(["", category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND", f"top={top_of_category(category)}"])
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

    out_matrix: List[List[str]] = []
    for _, pack in buckets.items():
        out_matrix.append(["PID"] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))

    if failures:
        # Failures 기록 로직... (생략)
        pass

    print(f"C2 Done. Buckets: {len(buckets)}")


# C3: FDA Registration No. 채우기 (새로 추가)
def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False):
    print("\n[ Create ] Step C3: Fill FDA Code...")
    
    tem_name = get_tem_sheet_name()
    # FDA 대상 카테고리 시트 이름 (automation_steps.py 참조)
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"

    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values('A:A', value_render_option='UNFORMATTED_VALUE'))
        target_categories = {str(r[0]).strip().lower() for r in (fda_vals_2d or []) if r and str(r[0]).strip()}
    except Exception as e:
        print(f"[!] '{fda_sheet_name}' 탭을 읽는 데 실패했습니다: {e}. Step C3을 건너뜁니다.")
        return

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음. Step C1/C2 선행 필요."); return

    if not vals: return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

    for r0, row in enumerate(vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue
        if not current_keys or col_fda_B < 0 or col_category_B < 0: continue

        pid = (row[0] if len(row) > 0 else "").strip()
        if not pid: continue
        
        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        category_val_normalized = category_val_raw.lower()
        
        if category_val_normalized and category_val_normalized in target_categories:
            c_fda_sheet_col = col_fda_B + 2
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()
            
            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C3 Done. FDA codes applied: {len(updates)} cells.")


# C4: MARGIN → TEM 가격 매핑 (SKU 기준, 'SKU Price' 채우기)
def run_step_C4_prices(sh: gspread.Spreadsheet):
    # C4 로직... (생략)
    pass


# C5: 이미지 URL 채우기 (Option/Cover/Details) + Variation 복원
def run_step_C5_images(
    sh: gspread.Spreadsheet,
    shop_code: str,
    cover_base_url: str,
    details_base_url: str,
    option_base_url: str,
):
    # C5 로직... (생략)
    pass


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
            # [수정 반영] F열(header="weight" 또는 "f")을 명시적으로 참조
            idx_mg_weight = _find_col_index(
                mg_keys, "weight", extra_alias=["무게", "f", "package weight"] 
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
    
    # ... (생략) Stock, Brand, Weight 매핑 로직 ...
    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku    = _find_col_index(cur_headers, "sku")
            idx_t_stock  = _find_col_index(cur_headers, "stock")
            idx_t_weight = _find_col_index(cur_headers, "weight")
            idx_t_brand  = _find_col_index(cur_headers, "brand")
            continue
        if not cur_headers or idx_t_sku == -1: continue
        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku: continue

        # Stock (M열 = 1000)
        if idx_t_stock != -1:
            val = "1000"
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != val:
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
    # ... (생략)

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))
    
    print(f"C6 Done. Updates: {len(updates)} cells")


class ShopeeCreator:
    # ShopeeCreator 클래스 정의 (생략)
    # ...

    def _reset_failures(self) -> None:
        # _reset_failures 로직 (생략)
        # ...
        pass

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C3 (FDA) → C4 → C5 → C6
        """
        try:
            # 인증 및 시트 연결 (생략)
            # ...
            self._connect()
            assert self.sh is not None
            assert self.ref is not None

            # 실패 로그 초기화 (요구사항)
            self._reset_failures()

            # 단계 실행: C3 (FDA) 추가
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C3_fda(self.sh, self.ref) # [추가] FDA 코드 채우기
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
            # 오류 처리 로직 (생략)
            # ...
            import traceback
            traceback.print_exc()
            return False


    # ----------------------------------------------------------
    # 엑셀 다운로드 (xlsx)
    # ----------------------------------------------------------

    def get_tem_values_xlsx(self) -> Optional[BytesIO]:
        """
        [추가/수정] TEM_OUTPUT 시트를 엑셀(xlsx) 파일로 분할하여 반환합니다.
        - A열 PID 제거, Category 형식 정규화 조건 반영.
        """
        tem_name = get_tem_sheet_name()
        tem_ws = safe_worksheet(self.sh, tem_name)

        all_data = with_retry(lambda: tem_ws.get_all_values())
        if not all_data:
            print("[!] TEM_OUTPUT sheet is empty. Cannot generate file.")
            return None

        # pandas DataFrame으로 변환
        df = pd.DataFrame(all_data)
        for c in df.columns:
            df[c] = df[c].astype(str)

        # 헤더 행 탐지: 두 번째 컬럼(인덱스 1)이 'category' 인 행
        header_mask = df.iloc[:, 1].str.lower().eq("category")
        header_indices = df.index[header_mask].tolist()
        if not header_indices:
            print("[!] No valid header rows found in TEM_OUTPUT for XLSX generation.")
            return None

        output = BytesIO()

        try:
            import xlsxwriter # xlsxwriter가 있으면 xlsxwriter, 없으면 openpyxl 사용
            engine = "xlsxwriter"
        except ImportError:
            try:
                import openpyxl # openpyxl이 없으면 에러 발생
                engine = "openpyxl"
            except ImportError:
                print("[!] 엑셀(xlsx) 생성을 위해 'xlsxwriter' 또는 'openpyxl' 라이브러리가 필요합니다. CSV로 폴백할 수 있습니다.")
                return None


        with pd.ExcelWriter(output, engine=engine) as writer:
            for i, header_index in enumerate(header_indices):
                start_row = header_index + 1
                end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
                if start_row >= end_row:
                    continue

                # 1. A열 PID 제거 (2열부터: df.iloc[:, 1:])
                header_row = df.iloc[header_index, 1:]
                chunk_df = df.iloc[start_row:end_row, 1:].copy()

                # 2. Category 의 코드와 하이픈 사이의 공백 제거 (첫 번째 컬럼 = Category)
                if not chunk_df.empty and chunk_df.shape[1] > 0:
                    first_col = chunk_df.columns[0]
                    # 첫 번째 컬럼이 'Category'일 확률이 높지만, 안전하게 헤더를 확인
                    if header_key(header_row.iloc[0]) == "category":
                        # as-is: 101643 - Beauty/Makeup/Lips/Lip Gloss
                        # to-be: 101643-Beauty/Makeup/Lips/Lip Gloss
                        chunk_df.iloc[:, 0] = (
                            chunk_df.iloc[:, 0]
                            .astype(str)
                            .str.replace(r"\s*-\s*", "-", regex=True)
                        )

                # 컬럼명 설정
                columns = header_row.astype(str).tolist()
                if len(columns) != chunk_df.shape[1]:
                    columns = columns[: chunk_df.shape[1]] if len(columns) > chunk_df.shape[1] else columns + [f"col_{k}" for k in range(len(columns), chunk_df.shape[1])]
                chunk_df.columns = columns

                # 시트명 결정
                cat_col_name = next((c for c in columns if c.lower() == "category"), None)
                first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"
                top_level_name = top_of_category(first_cat) or "UNKNOWN"
                sheet_name = re.sub(r"[\s/\\*?:\[\]]", "_", str(top_level_name).title())[:31]

                # 엑셀에 쓰기 (헤더 유지, 인덱스 제거)
                chunk_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 편의 포맷 (생략)
                # ...

        output.seek(0)
        print("Final template file generated successfully (xlsx).")
        return output
    
    # ----------------------------------------------------------
    # CSV Export (main_controller가 fallback으로 사용)
    # ----------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """TEM_OUTPUT 시트를 CSV 바이트로 반환 (PID 제거 및 Category 정규화는 XLSX에서 처리)"""
        # main_controller.py가 CSV를 다운로드할 때 호출하는 메서드입니다.
        # PID 제거 및 정규화는 XLSX 로직에 있으므로, CSV는 원본 데이터를 제공하는 폴백으로 남겨둡니다.
        if not self.sh:
            return None

        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals:
                return None
            
            # [PID 제거] 엑셀 다운로드 조건에 따라 첫 번째 컬럼(PID)을 제거하고 CSV 생성 (폴백 CSV에도 적용)
            # 또한, 헤더 행(두 번째 컬럼이 'Category'인 행)도 첫 번째 컬럼을 제거해야 합니다.
            processed_vals = []
            current_headers = None
            
            for row in vals:
                if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                    current_headers = row[1:]
                    processed_vals.append(current_headers) # PID 제거된 헤더 추가
                    continue

                if current_headers and len(row) > 1:
                    # 데이터 행: PID 제거
                    data_row = row[1:]
                    
                    # Category 형식 정규화 (PID 제거 후 첫 번째 열)
                    if len(data_row) > 0 and current_headers and header_key(current_headers[0]) == "category":
                        data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                        
                    processed_vals.append(data_row)
                elif len(row) > 0:
                    # 헤더 행이 아니지만 PID가 있는 경우(예: PID만 있는 빈 행) PID 제거 시도
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
