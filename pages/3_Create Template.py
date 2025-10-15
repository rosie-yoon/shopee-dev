# pages/3_Create Template.py
# -*- coding: utf-8 -*-
import streamlit as st
from shopee_creator.controller import ShopeeCreator
from shopee_creator.creation_steps import export_tem_xlsx, export_tem_csv
from shopee_creator.utils_creator import extract_sheet_id, get_env # 유틸리티 함수 임포트

# --------------------------------------------------------------------
# 1) 페이지 설정
# --------------------------------------------------------------------
st.set_page_config(page_title="Create Template (Item-Creator)", layout="wide")
st.title("Create Template")
st.caption("상품등록 시트를 기반으로 신규 Mass Upload 템플릿을 생성합니다.")


# --------------------------------------------------------------------
# 2) Secrets 기반 레퍼런스 URL 가져오기
# --------------------------------------------------------------------
def _get_ref_url_from_secrets() -> str | None:
    # secrets에서 REFERENCE_SPREADSHEET_ID를 읽어 URL을 구성합니다.
    try:
        s = st.secrets
    except Exception:
        return None

    # controller.py의 로직과 유사하게 REFERENCE_SPREADSHEET_ID를 처리
    sid = s.get("REFERENCE_SPREADSHEET_ID")
    if sid:
        sid = str(sid).strip()
        if sid.startswith("http"):
            return sid
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"

    # 폴백 키는 생략하고 핵심 키만 체크
    return None

REF_URL = _get_ref_url_from_secrets()
if not REF_URL:
    st.error("`secrets`에 레퍼런스 시트 ID가 없습니다. `REFERENCE_SPREADSHEET_ID`를 설정해 주세요.")

# --------------------------------------------------------------------
# 3) UI 구성 및 입력 폼
# --------------------------------------------------------------------

# 세션 초기화 (필요한 경우)
if "SHEET_URL" not in st.session_state:
    st.session_state.SHEET_URL = ""
if "BASE_URL" not in st.session_state:
    st.session_state.BASE_URL = get_env("IMAGE_HOSTING_URL", "")
if "SHOP_CODE" not in st.session_state:
    st.session_state.SHOP_CODE = ""


st.subheader("⚙️ 초기 설정")
st.write("상품등록 시트 URL과 이미지 Base URL을 설정하고 저장합니다.")

# 초기 설정 폼 (저장 버튼으로 세션 상태 업데이트)
with st.form("settings_form", clear_on_submit=False):
    col_sheet, col_base = st.columns(2)
    
    with col_sheet:
        sheet_url_input = st.text_input(
            "상품등록 시트 URL (필수)",
            value=st.session_state.SHEET_URL,
            placeholder="https://docs.google.com/...",
            key="sheet_url_input"
        )
    
    with col_base:
        base_url_input = st.text_input(
            "이미지 Base URL (필수)",
            value=st.session_state.BASE_URL,
            placeholder="https://example.com/assets/",
            key="base_url_input"
        )
        
    submitted = st.form_submit_button("저장")
    
    if submitted:
        if not sheet_url_input or not base_url_input:
            st.error("상품등록 시트 URL과 이미지 Base URL을 모두 입력해 주세요.")
        else:
            # 유효성 검사 (시트 ID 추출 시도)
            try:
                extract_sheet_id(sheet_url_input)
                st.session_state.SHEET_URL = sheet_url_input
                st.session_state.BASE_URL = base_url_input
                st.success("초기 설정이 저장되었습니다. 아래에서 샵코드를 입력하고 실행해 주세요.")
            except ValueError:
                st.error("올바른 Google Sheets URL 형식이 아닙니다.")


st.markdown("---")
st.subheader("샵 코드 입력 및 실행")

# 샵 코드 입력 및 실행 버튼 섹션
if st.session_state.SHEET_URL and REF_URL:
    
    col_shopcode, col_run = st.columns([0.7, 0.3])
    
    with col_shopcode:
        shop_code_input = st.text_input(
            "샵 코드 입력", 
            value=st.session_state.SHOP_CODE,
            placeholder="예: RO. 01 등 커버 이미지 코드와 동일하게 입력하세요.",
            key="shop_code_input",
            label_visibility="collapsed" # 레이블 숨김
        )
        st.caption("예: RO. 01 등 커버 이미지 코드와 동일하게 입력하세요.")
        
    with col_run:
        # 샵코드 저장 및 실행 로직
        run_disabled = not shop_code_input
        
        if st.button("🚀 실행", type="primary", use_container_width=True, disabled=run_disabled):
            st.session_state.SHOP_CODE = shop_code_input # 샵코드 세션에 저장
            st.session_state.RUN_TRIGGERED = True
            st.rerun() # 실행 로직으로 이동
        

# --------------------------------------------------------------------
# 4) 실행 로직
# --------------------------------------------------------------------

if st.session_state.get("RUN_TRIGGERED") and st.session_state.SHOP_CODE:
    
    st.session_state.RUN_TRIGGERED = False # 실행 트리거 초기화
    
    sheet_url = st.session_state.SHEET_URL
    base_url = st.session_state.BASE_URL
    shop_code = st.session_state.SHOP_CODE
    
    st.markdown("---")
    st.subheader("실행 로그")

    try:
        ctrl = ShopeeCreator(st.secrets)
        ctrl.set_image_bases(
            shop_code=shop_code,
            cover=base_url,
            details=base_url,
            option=base_url
        )
        
        with st.spinner(f"C1~C6 단계 실행 중... (URL: {sheet_url})"):
            results = ctrl.run(input_sheet_url=sheet_url)

        st.success("템플릿 생성 완료 ✅")
        
        # --------------------------------------------------------------------
        # 5) 최종 파일 다운로드 섹션
        # --------------------------------------------------------------------
        st.markdown("---")
        st.subheader("2. 최종 파일 다운로드")
        
        for log in results:
            with st.expander(f"{'✅' if log.ok else '❌'} {log.name}", expanded=not log.ok):
                st.json({
                    "ok": log.ok,
                    "count": log.count,
                    "error": log.error
                })

        # TEM_OUTPUT 시트에서 XLSX 추출
        try:
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

    except Exception as e:
        st.exception(e)
        st.error("템플릿 생성 중 치명적인 오류가 발생했습니다. 로그를 확인해 주세요.")

elif not st.session_state.SHEET_URL:
    st.info("상품등록 시트 URL과 이미지 Base URL을 '초기 설정'에서 입력 후 저장해 주세요.")
