# C4: MARGIN → TEM 가격/무게 매핑 + 기본값 채우기
def run_step_C4_prices(sh: gspread.Spreadsheet):
    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals: return

    # --- MARGIN 로드: SKU ↔ 소비자가(E), 무게(F) ---
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
    except WorksheetNotFound:
        return
    mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
    if len(mg_vals) < 2: return

    mg_keys = [header_key(h) for h in mg_vals[0]]
    idx_mg_sku   = _find_col_index(mg_keys, "sku", extra_alias=["seller_sku"])
    idx_mg_price = _find_col_index(mg_keys, "소비자가", extra_alias=["consumer price","price"])
    idx_mg_wt    = _find_col_index(mg_keys, "weight",     extra_alias=["무게","gross weight"])
    if idx_mg_sku == -1: return

    sku_to_price, sku_to_wt = {}, {}
    for r in range(1, len(mg_vals)):
        row = mg_vals[r]
        sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
        if not sku: continue
        if idx_mg_price != -1:
            val = (row[idx_mg_price] if idx_mg_price < len(row) else "").strip()
            if val: sku_to_price[sku] = val
        if idx_mg_wt != -1:
            wt = (row[idx_mg_wt] if idx_mg_wt < len(row) else "").strip()
            if wt: sku_to_wt[sku] = wt

    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_price = idx_t_stock = idx_t_weight = idx_t_brand = -1

    for r0, row in enumerate(tem_vals):
        # 헤더 경계
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku    = _find_col_index(cur_headers, "sku")
            idx_t_price  = _find_col_index(cur_headers, "sku price", extra_alias=["price"])
            idx_t_stock  = _find_col_index(cur_headers, "stock")
            idx_t_weight = _find_col_index(cur_headers, "weight")
            idx_t_brand  = _find_col_index(cur_headers, "brand")
            continue
        if not cur_headers or idx_t_sku == -1:
            continue

        sku = (row[idx_t_sku + 1] if len(row) > idx_t_sku + 1 else "").strip()
        if not sku: continue

        # (1) 가격
        if idx_t_price != -1 and sku in sku_to_price:
            cur = (row[idx_t_price + 1] if len(row) > idx_t_price + 1 else "").strip()
            val = sku_to_price[sku]
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_price + 2, value=val))

        # (2) 재고 = 1000
        if idx_t_stock != -1:
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != "1000":
                updates.append(Cell(row=r0 + 1, col=idx_t_stock + 2, value="1000"))

        # (3) 무게 = MARGIN 매핑(F열 추정)
        if idx_t_weight != -1 and sku in sku_to_wt:
            cur = (row[idx_t_weight + 1] if len(row) > idx_t_weight + 1 else "").strip()
            wt  = sku_to_wt[sku]
            if cur != wt:
                updates.append(Cell(row=r0 + 1, col=idx_t_weight + 2, value=wt))

        # (4) 브랜드 = "0"
        if idx_t_brand != -1:
            cur = (row[idx_t_brand + 1] if len(row) > idx_t_brand + 1 else "").strip()
            if cur != "0":
                updates.append(Cell(row=r0 + 1, col=idx_t_brand + 2, value="0"))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))
