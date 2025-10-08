# pages/3_Create Items.py (핵심만)
from item_creator.main_controller import ShopeeCreator

# ... (URL 입력란들 그대로)

c1, c2 = st.columns([1,1])
with c1:
    shop_code = st.text_input("샵코드 (필수)", placeholder="예: RO", max_chars=10)

# 실행 버튼
run_disabled = not (sheet_url and details_base and cover_base and sku_base and shop_code)
if st.button("🚀 실행 (Create)", type="primary", use_container_width=True, disabled=run_disabled):
    sheet_id = extract_sheet_id(sheet_url)
    ref_id = extract_sheet_id(ref_sheet_url) if (ref_sheet_url or "").strip() else None

    ctrl = ShopeeCreator(
        creation_spreadsheet_id=sheet_id,
        cover_base_url=cover_base,
        details_base_url=details_base,
        option_base_url=sku_base,
        ref_spreadsheet_id=ref_id,
        shop_code=shop_code,                # ⬅️ 추가
    )
    result = ctrl.run(progress_callback=lambda p,m: progress_bar.progress(p/100.0, text=m))

    # 로그 표시
    for ln in result.get("logs", []):
        st.text(ln)

    # 다운로드 버튼
    data = result.get("download_bytes")
    name = result.get("download_name")
    if data and name:
        st.download_button("⬇️ TEM_OUTPUT 다운로드", data=data, file_name=name, mime="text/csv", use_container_width=True)
