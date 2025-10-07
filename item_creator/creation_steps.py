# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Optional
import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound

from item_uploader.automation_steps import (
    header_key, top_of_category, get_tem_sheet_name,
    _find_col_index, with_retry, safe_worksheet,
)

from item_creator.utils_common import get_env, join_url, forward_fill_by_group

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

def _collect_indices(header_row: List[str]) -> Dict[str, int]:
    keys = [header_key(x) for x in header_row]
    def idx(name: str, aliases: List[str] = []) -> int:
        return _find_col_index(keys, name, extra_alias=aliases)

    return {
        "create": idx("create", ["use","apply"]),
        "variation": idx("variation", ["variationno","variationintegrationno","var code","variation code"]),
        "sku": idx("sku", ["seller_sku"]),
        "brand": idx("brand", ["brandname"]),
        "option_eng": idx("option(eng)", ["optioneng","option","option1","option name","option for variation 1"]),
        "prod_name": idx("product name", ["item(eng)","itemeng","name"]),
        "desc": idx("description", ["product description"]),
        "category": idx("category"),
        "detail_idx": idx("details index", ["detail image count","details count","detailindex"]),
    }

def _is_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("true","t","1","y","yes","✔","✅")

def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet):
    print("\n[ Create ] Step C2: Build TEM from Collection ...")
    tem_name = get_tem_sheet_name()
    template_dict = _load_template_dict(ref)

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []
    if not coll_vals or len(coll_vals) < 2:
        print("[C2] Collection 비어 있음."); return

    colmap = _collect_indices(coll_vals[0])
    create_i     = colmap["create"]      if colmap["create"]      >= 0 else 0
    variation_i  = colmap["variation"]   if colmap["variation"]   >= 0 else 1
    sku_i        = colmap["sku"]         if colmap["sku"]         >= 0 else 2
    brand_i      = colmap["brand"]       if colmap["brand"]       >= 0 else 3
    option_i     = colmap["option_eng"]  if colmap["option_eng"]  >= 0 else 5
    pname_i      = colmap["prod_name"]   if colmap["prod_name"]   >= 0 else 7
    desc_i       = colmap["desc"]        if colmap["desc"]        >= 0 else 9
    category_i   = colmap["category"]    if colmap["category"]    >= 0 else 10
    dcount_i     = colmap["detail_idx"]  if colmap["detail_idx"]  >= 0 else 11

    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]
    def _reset_when(row: List[str]) -> bool:
        if not any(str(x or "").strip() for x in row):
            return True
        return not _is_true(row[create_i] if create_i < len(row) else "")
    ff_vals = forward_fill_by_group(coll_vals, group_idx=variation_i, fill_col_indices=fill_cols, reset_when=_reset_when)

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
            failures.append(["", "", pname, "CATEGORY_MISSING", f"row={r+1}"]); continue

        top_norm = header_key(top_of_category(category) or "")
        headers = template_dict.get(top_norm)
        if not headers:
            failures.append(["", category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND", f"top={top_of_category(category)}"]); continue

        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)   # F
        set_if_exists(headers, tem_row, "variation name1", "Options")        # G
        set_if_exists(headers, tem_row, "option for variation 1", opt1)      # H
        set_if_exists(headers, tem_row, "sku", sku)                           # N
        set_if_exists(headers, tem_row, "brand", brand)                       # AE

        pid = variation or sku or f"ROW{r}"
        b = buckets.setdefault(top_norm, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid]); b["rows"].append(tem_row)

    out_matrix: List[List[str]] = []
    for _, pack in buckets.items():
        out_matrix.append([""] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))

    if failures:
        try:
            ws_f = safe_worksheet(sh, "Failures")
        except WorksheetNotFound:
            ws_f = with_retry(lambda: sh.add_worksheet(title="Failures", rows=1000, cols=10))
            with_retry(lambda: ws_f.update(values=[["PID","Category","Name","Reason","Detail"]], range_name="A1"))
        vals = with_retry(lambda: ws_f.get_all_values()) or []
        start = len(vals) + 1
        with_retry(lambda: ws_f.update(values=failures, range_name=f"A{start}"))

    print(f"C2 Done. Buckets: {len(buckets)}")

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
        print("[C5] TEM_OUTPUT 비어 있음."); return

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []

    sku_to_var: Dict[str, str] = {}
    var_to_count: Dict[str, int] = {}

    if coll_vals and len(coll_vals) >= 2:
        colmap = _collect_indices(coll_vals[0])
        create_i     = colmap["create"]      if colmap["create"]      >= 0 else 0
        variation_i  = colmap["variation"]   if colmap["variation"]   >= 0 else 1
        sku_i        = colmap["sku"]         if colmap["sku"]         >= 0 else 2
        dcount_i     = colmap["detail_idx"]  if colmap["detail_idx"]  >= 0 else 11

        fill_cols = [variation_i, dcount_i]
        def _reset_when(row: List[str]) -> bool:
            if not any(str(x or "").strip() for x in row):
                return True
            return not _is_true(row[create_i] if create_i < len(row) else "")
        ff_vals = forward_fill_by_group(coll_vals, group_idx=variation_i, fill_col_indices=fill_cols, reset_when=_reset_when)

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
            if sku: sku_to_var[sku] = var
            if var and var not in var_to_count:
                var_to_count[var] = cnt

    updates: List[Cell] = []
    cur_headers = None
    idx_cover = idx_optimg = idx_sku = idx_varno = -1
    idx_items: List[int] = []

    suffix = f"_C_{shop_code}" if shop_code else ""

    for r0, row in enumerate(tem_vals):
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

        sku = (row[idx_sku + 1] if idx_sku != -1 and len(row) > idx_sku + 1 else "").strip()
        var = sku_to_var.get(sku, (row[idx_varno + 1] if idx_varno != -1 and len(row) > idx_varno + 1 else "").strip())
        key = var if var else sku

        if idx_varno != -1 and var and (row[idx_varno + 1] if len(row) > idx_varno + 1 else "") != var:
            updates.append(Cell(row=r0 + 1, col=idx_varno + 2, value=var))

        if idx_optimg != -1 and sku:
            opt_url = join_url(option_base_url, sku)
            if (row[idx_optimg + 1] if len(row) > idx_optimg + 1 else "") != opt_url:
                updates.append(Cell(row=r0 + 1, col=idx_optimg + 2, value=opt_url))

        if idx_cover != -1 and key:
            cov_url = f"{join_url(cover_base_url, key)}{suffix}.jpg"
            if (row[idx_cover + 1] if len(row) > idx_cover + 1 else "") != cov_url:
                updates.append(Cell(row=r0 + 1, col=idx_cover + 2, value=cov_url))

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
