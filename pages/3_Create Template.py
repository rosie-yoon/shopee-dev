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
if "LAST_RUN_RESULTS" not in st.session_state:
    st.session_state.LAST_RUN_RESULTS = None


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
                st.session_state.LAST_RUN_RESULTS = None # 설정 변경 시 이전 결과 초기화
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
            st.session_state.LAST_RUN_RESULTS = None # 새로운 실행 시 이전 결과 초기화
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

    # 프로세스 바 설정
    STATUS_MAP = [
        "C1 Prepare TEM_OUTPUT",
        "C2 Collection → TEM",
        "C3 FDA Fill",
        "C4 Prices",
        "C5 Images",
        "C6 Stock/Weight/Brand",
    ]
    progress_bar = st.progress(0, text="프로세스 시작 대기 중...")
    
    # 빈 컨테이너 설정 (로그 및 결과 표시용)
    log_container = st.empty()
    download_container = st.empty()


    try:
        ctrl = ShopeeCreator(st.secrets)
        ctrl.set_image_bases(
            base_url=base_url,
            shop_code=shop_code,
        )
        
        results = []
        # ctrl.run() 내부 로직을 재구성하여 단계별로 실행 및 업데이트
        
        # 💡 StepLog를 반환하는 ctrl.run() 대신, 각 단계를 직접 호출하며 업데이트
        
        pipeline = [
            ("C1 Prepare TEM_OUTPUT", lambda: ctrl.run_single_step(0, sheet_url)),
            ("C2 Collection → TEM",  lambda: ctrl.run_single_step(1, sheet_url)),
            ("C3 FDA Fill",          lambda: ctrl.run_single_step(2, sheet_url)),
            ("C4 Prices",            lambda: ctrl.run_single_step(3, sheet_url)),
            ("C5 Images",            lambda: ctrl.run_single_step(4, sheet_url)),
            ("C6 Stock/Weight/Brand",lambda: ctrl.run_single_step(5, sheet_url)),
        ]
        
        # [주의]: ctrl.run() 대신 임시로 StepLog 반환 함수를 모킹 (실제 환경에서는 controller.py 수정 필요)
        # 현재는 ctrl.run(input_sheet_url)을 호출하는 방식만 지원되므로, run_single_step을 대신 사용합니다.
        
        total_steps = len(STATUS_MAP)
        results = []
        all_ok = True

        for i, (name, run_fn) in enumerate(pipeline):
            progress_bar.progress((i + 1) / total_steps, text=f"진행 중: {name}")
            
            # 여기서 실제 ctrl.run()을 호출하고, 결과를 분석하여 결과를 업데이트합니다.
            # 하지만 Streamlit에서는 단일 실행으로 결과를 받아야 하므로,
            # run()을 호출하고 전체 결과를 받은 후, 진행률만 시각적으로 표시합니다.
            # *[NOTE: 실제 ctrl.run()은 단계별로 중단되므로, 이 방식이 정확하지 않을 수 있습니다.]*
            # 
            # ➡️ run() 함수를 한 번만 호출하도록 구조를 다시 단순화하고,
            #    프로세스 바는 단순 시각화 용도로만 사용합니다.

        # 🚨 [중요]: 단계별 진행 표시를 위해 st.rerun()을 사용할 수 없으므로,
        #            run()을 한 번 호출하고 최종 결과만 받아와 진행 바를 완료 상태로 만듭니다.
        
        progress_bar.progress(0, text="C1~C6 단계 실행 준비 중...")
        results = ctrl.run(input_sheet_url=sheet_url)
        progress_bar.progress(1.0, text="✅ 모든 단계 완료.")

        st.session_state.LAST_RUN_RESULTS = {
            "sheet_url": sheet_url,
            "shop_code": shop_code,
            "results": results
        }
        
        st.success("템플릿 생성 완료 ✅")

    except Exception as e:
        progress_bar.empty()
        st.exception(e)
        st.error("템플릿 생성 중 치명적인 오류가 발생했습니다. 로그를 확인해 주세요.")

# --------------------------------------------------------------------
# 5) 최종 파일 다운로드 및 로그 표시 (실행 완료 후)
# --------------------------------------------------------------------

if st.session_state.LAST_RUN_RESULTS:
    
    results_data = st.session_state.LAST_RUN_RESULTS
    results = results_data["results"]
    shop_code = results_data["shop_code"]
    sheet_url = results_data["sheet_url"]
    
    # 1. C1~C6 로그를 Expander 안에 배치
    with st.expander("세부 실행 로그 (C1 ~ C6 단계)", expanded=False):
        for log in results:
            log_status = "✅" if log.ok else "❌"
            st.markdown(f"**{log_status} {log.name}**")
            # 에러 발생 시 상세 정보 표시
            if log.error:
                 st.error(f"오류: {log.error}")
            else:
                st.json({
                    "ok": log.ok,
                    "count": log.count,
                    "error": log.error
                })
        
    
    st.markdown("---")
    st.subheader("2. 최종 파일 다운로드")

    # 2. 다운로드 버튼만 노출
    try:
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
