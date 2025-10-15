# pages/3_Create Template.py
# -*- coding: utf-8 -*-
import streamlit as st
from shopee_creator.controller import ShopeeCreator
from shopee_creator.creation_steps import export_tem_xlsx, export_tem_csv
from shopee_creator.utils_creator import extract_sheet_id, get_env

# --------------------------------------------------------------------
# 1) 페이지 설정
# --------------------------------------------------------------------
st.set_page_config(page_title="Create Template (Item-Creator)", layout="wide")
st.title("Create Template")
st.caption("상품등록 시트를 기반으로 신규 Mass Upload 템플릿을 생성합니다.")

# --------------------------------------------------------------------
# 2) Secrets 기반 레퍼런스 URL 체크(옵션)
# --------------------------------------------------------------------
def _get_ref_url_from_secrets() -> str | None:
    try:
        s = st.secrets
    except Exception:
        return None
    sid = s.get("REFERENCE_SPREADSHEET_ID")
    if sid:
        sid = str(sid).strip()
        if sid.startswith("http"):
            return sid
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    return None

REF_URL = _get_ref_url_from_secrets()
if not REF_URL:
    st.info("참고: secrets에 REFERENCE_SPREADSHEET_ID가 없으면 컨트롤러에서 별도 처리합니다.")

# --------------------------------------------------------------------
# 3) 세션 기본값
# --------------------------------------------------------------------
for k, v in {
    "SHEET_URL": "",
    "BASE_URL": get_env("IMAGE_HOSTING_URL", ""),
    "SHOP_CODE": "",
    "LAST_RUN_RESULTS": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --------------------------------------------------------------------
# 4) 초기 설정 폼
# --------------------------------------------------------------------
st.subheader("⚙️ 초기 설정")
with st.form("settings_form", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        sheet_url_input = st.text_input(
            "상품등록 시트 URL (필수)",
            value=st.session_state.SHEET_URL,
            placeholder="https://docs.google.com/spreadsheets/d/....",
        )
    with col2:
        base_url_input = st.text_input(
            "이미지 Base URL (필수, 입력 그대로 사용)",
            value=st.session_state.BASE_URL,
            placeholder="https://example.com/assets/",
        )
    submitted = st.form_submit_button("저장")

if submitted:
    if not sheet_url_input or not base_url_input:
        st.error("상품등록 시트 URL과 이미지 Base URL을 모두 입력해 주세요.")
    else:
        try:
            extract_sheet_id(sheet_url_input)  # 유효성 간단 체크
            st.session_state.SHEET_URL = sheet_url_input.strip()
            st.session_state.BASE_URL = base_url_input  # 보정 없음
            st.session_state.LAST_RUN_RESULTS = None
            st.success("저장 완료. 아래에서 샵코드를 입력하고 실행하세요.")
        except ValueError:
            st.error("올바른 Google Sheets URL 형식이 아닙니다.")

st.markdown("---")
st.subheader("샵 코드 입력 및 실행")

# --------------------------------------------------------------------
# 5) 샵코드 입력 + 실행
# --------------------------------------------------------------------
if st.session_state.SHEET_URL:
    col_shop, col_btn = st.columns([0.7, 0.3])
    with col_shop:
        shop_code_input = st.text_input(
            "샵 코드 (입력 그대로 사용: 예 RO / ro / RO. 01 등)",
            value=st.session_state.SHOP_CODE,
            placeholder="예: RO, RO. 01",
        )
    with col_btn:
        run_disabled = not shop_code_input
        if st.button("🚀 실행", type="primary", use_container_width=True, disabled=run_disabled):
            st.session_state.SHOP_CODE = shop_code_input  # 보정 없음
            st.session_state.RUN_TRIGGERED = True
            st.session_state.LAST_RUN_RESULTS = None
            st.rerun()

# --------------------------------------------------------------------
# 6) 실행 로직
# --------------------------------------------------------------------
if st.session_state.get("RUN_TRIGGERED") and st.session_state.SHOP_CODE:
    st.session_state.RUN_TRIGGERED = False
    sheet_url = st.session_state.SHEET_URL
    base_url  = st.session_state.BASE_URL
    shop_code = st.session_state.SHOP_CODE

    st.subheader("실행 로그")
    progress = st.progress(0, text="C1~C6 실행 중...")

    try:
        ctrl = ShopeeCreator(st.secrets)
        # ✅ run() 전에 반드시 값 주입 (입력 그대로 사용)
        ctrl.set_image_base(base_url=base_url, shop_code=shop_code)

        # 한 번에 실행 (내부에서 실패 시 중단)
        logs = ctrl.run(input_sheet_url=sheet_url)
        progress.progress(1.0, text="✅ 모든 단계 완료")

        st.session_state.LAST_RUN_RESULTS = {
            "sheet_url": sheet_url,
            "shop_code": shop_code,
            "results": logs,
        }
        st.success("템플릿 생성 완료 ✅")

    except Exception as e:
        progress.empty()
        st.exception(e)
        st.error("템플릿 생성 중 오류가 발생했습니다. 로그를 확인해 주세요.")

# --------------------------------------------------------------------
# 7) 결과 표시 + 다운로드
# --------------------------------------------------------------------
if st.session_state.LAST_RUN_RESULTS:
    data = st.session_state.LAST_RUN_RESULTS
    results = data["results"]
    sheet_url = data["sheet_url"]
    shop_code = data["shop_code"]

    with st.expander("세부 실행 로그 (C1~C6)", expanded=False):
        for log in results:
            status = "✅" if log.ok else "❌"
            st.markdown(f"**{status} {log.name}**")
            if log.error:
                st.error(f"오류: {log.error}")

    st.markdown("---")
    st.subheader("최종 파일 다운로드")

    try:
        # Export는 별도 gspread client로 열어도 무방
        ctrl = ShopeeCreator(st.secrets)
        sh = ctrl.gs.open_by_url(sheet_url)

        xlsx_io = export_tem_xlsx(sh)
        if xlsx_io:
            st.download_button(
                "📥 TEM_OUTPUT 내려받기 (XLSX)",
                data=xlsx_io.getvalue(),
                file_name=f"{shop_code}_TEM_OUTPUT.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            csv_bytes = export_tem_csv(sh)
            if csv_bytes:
                st.download_button(
                    "📥 TEM_OUTPUT 내려받기 (CSV - 폴백)",
                    data=csv_bytes,
                    file_name=f"{shop_code}_TEM_OUTPUT.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.info("다운로드 데이터가 없습니다. TEM_OUTPUT 시트를 확인해 주세요.")
    except Exception as ex:
        st.warning(f"다운로드 생성 중 오류: {ex}")
