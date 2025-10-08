# pages/3_Create Items.py
# -*- coding: utf-8 -*-
import os
import traceback
import streamlit as st

from item_creator.utils_common import (
    get_env,
    save_env_value,
    extract_sheet_id,
    sheet_link,
)

# ---------------------------------------------------------
# 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="Create New Items", layout="wide")
st.title("Create New Items (신규 생성)")
st.caption("‘상품등록’ 개인 시트(MARGIN / Collection)를 기반으로 TEM_OUTPUT를 생성합니다.")

# ---------------------------------------------------------
# 저장된 값(있으면) 불러와 폼에 프리필
# ---------------------------------------------------------
_saved_creation_id = get_env("CREATION_SPREADSHEET_ID", "")
_saved_cover_base  = get_env("CREATION_COVER_BASE_URL", "")
_saved_detail_base = get_env("CREATION_DETAILS_BASE_URL", "")
_saved_option_base = get_env("CREATION_OPTION_BASE_URL", "")

_prefill_url = sheet_link(_saved_creation_id) if _saved_creation_id else ""

with st.container():
    st.subheader("1) 필수 입력값")
    col1, col2 = st.columns(2)
    with col1:
        creation_url = st.text_input(
            "Google Sheets URL (상품등록 시트)",
            value=_prefill_url,
            placeholder="https://docs.google.com/spreadsheets/d/XXXXXXXXXXXX/edit",
            help="MARGIN / Collection 탭이 존재하는 '상품등록' 시트 URL 전체를 붙여넣으세요.",
        )
        cover_base = st.text_input(
            "Cover URL (Base)",
            value=_saved_cover_base,
            placeholder="예) https://img.example.com/covers",
            help="Cover 이미지의 베이스 URL. 예: https://img.example.com/covers",
        )
    with col2:
        detail_base = st.text_input(
            "Details URL (Base)",
            value=_saved_detail_base,
            placeholder="예) https://img.example.com/details",
            help="Item Image 1~8(상세 이미지)의 베이스 URL. 예: https://img.example.com/details",
        )
        option_base = st.text_input(
            "Option URL (Base)",
            value=_saved_option_base,
            placeholder="예) https://img.example.com/options",
            help="Image per Variation(옵션 이미지)의 베이스 URL. 예: https://img.example.com/options",
        )

    # -----------------------------------------------------
    # 입력값 저장(.env 업데이트) 섹션
    # -----------------------------------------------------
    st.subheader("2) 입력값 저장")
    st.caption("로컬 PC의 .env에 보관됩니다. 한번 저장하면 다음부터 자동으로 불러옵니다.")
    save_col1, save_col2 = st.columns([1, 3])
    with save_col1:
        if st.button("💾 입력값 저장", use_container_width=True):
            sid = extract_sheet_id(creation_url)
            if not sid:
                st.error("유효한 Google Sheets URL이 아닙니다. 전체 URL을 붙여넣었는지 확인하세요.")
            elif not (cover_base and detail_base and option_base):
                st.error("Cover / Details / Option Base URL을 모두 입력하세요.")
            else:
                save_env_value("CREATION_SPREADSHEET_ID", sid)
                save_env_value("CREATION_COVER_BASE_URL", cover_base.strip())
                save_env_value("CREATION_DETAILS_BASE_URL", detail_base.strip())
                save_env_value("CREATION_OPTION_BASE_URL", option_base.strip())
                st.success("저장 완료! (로컬 .env 업데이트)")
                st.info(f"상품등록 시트: {sheet_link(sid)}")

    with save_col2:
        with st.expander("현재 저장된 값 보기", expanded=False):
            st.markdown(f"- **CREATION_SPREADSHEET_ID**: `{_saved_creation_id or '(미설정)'} `{'' if not _saved_creation_id else f'→ {sheet_link(_saved_creation_id)}`'}")
            st.markdown(f"- **CREATION_COVER_BASE_URL**: `{_saved_cover_base or '(미설정)'}`")
            st.markdown(f"- **CREATION_DETAILS_BASE_URL**: `{_saved_detail_base or '(미설정)'}`")
            st.markdown(f"- **CREATION_OPTION_BASE_URL**: `{_saved_option_base or '(미설정)'}`")

# ---------------------------------------------------------
# 실행 섹션
# ---------------------------------------------------------
st.subheader("3) TEM_OUTPUT 생성 실행")

# 버튼 활성화 조건: 4개 모두 입력되어야 함 (화면 값 기준)
_sid = extract_sheet_id(creation_url) or ""
_is_ready = bool(_sid and cover_base and detail_base and option_base)

run_btn = st.button(
    "🚀 실행 (Create)",
    type="primary",
    disabled=not _is_ready,
)

if not _is_ready:
    st.warning("Google Sheets URL / Cover / Details / Option Base URL을 모두 입력하면 실행할 수 있어요.", icon="⚠️")

# ---------------------------------------------------------
# 실행 동작
# ---------------------------------------------------------
if run_btn:
    # 로그 영역 준비
    log_area = st.empty()
    prog = st.progress(0, text="초기화 중...")

    # 실행에 필요한 값(런타임 변이 최소화를 위해 지역 변수로 고정)
    sid = _sid
    cover = cover_base.strip()
    detail = detail_base.strip()
    option = option_base.strip()

    try:
        # 컨트롤러 임포트 시도
        try:
            from item_creator.main_controller import ShopeeCreator  # 사용자가 이후에 만들 파일
        except Exception as imp_err:
            st.error("컨트롤러 모듈(item_creator/main_controller.py)이 아직 준비되지 않았습니다.")
            st.code(traceback.format_exc())
            st.stop()

        # 컨트롤러 인스턴스 생성
        # 👉 컨트롤러 시그니처는 다음 중 하나로 구현하면 됩니다.
        # ShopeeCreator(creation_spreadsheet_id, cover_base_url, details_base_url, option_base_url, ref_spreadsheet_id=None)
        # 또는 키워드 인자 기반:
        creator = ShopeeCreator(
            creation_spreadsheet_id=sid,
            cover_base_url=cover,
            details_base_url=detail,
            option_base_url=option,
            ref_spreadsheet_id=get_env("REFERENCE_SPREADSHEET_ID", "") or None,
        )

        # 실행
        prog.progress(5, text="Step 준비 중...")
        result = creator.run(progress_callback=lambda p, msg: (prog.progress(min(max(int(p), 0), 100), text=msg), log_area.write(msg)))

        prog.progress(100, text="완료!")

        # 결과 처리
        st.success("생성 완료!")
        # result 예시 포맷 가이드:
        # {
        #   "download_path": "/tmp/output.xlsx",   # 로컬 파일 경로가 있으면 다운로드 버튼 표시
        #   "download_name": "TEM_OUTPUT_split.xlsx",
        #   "logs": ["..."]
        # }
        if isinstance(result, dict):
            if result.get("logs"):
                with st.expander("실행 로그", expanded=False):
                    for ln in result["logs"]:
                        st.write(ln)
            if result.get("download_path"):
                fp = result["download_path"]
                fname = result.get("download_name") or os.path.basename(fp)
                try:
                    with open(fp, "rb") as f:
                        st.download_button("📥 결과 파일 다운로드", data=f, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception:
                    st.info("결과 파일 경로를 열 수 없습니다. 컨트롤러에서 반환한 경로를 확인하세요.")
        else:
            st.info("컨트롤러에서 반환된 결과 포맷을 확인하세요. dict 형태를 권장합니다.")

    except Exception as e:
        st.error("실행 중 오류가 발생했습니다.")
        st.code(traceback.format_exc())
