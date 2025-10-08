# pages/2_Copy Template.py
from pathlib import Path
import sys
import streamlit as st
import os # get_env/save_env_value를 위한 추가

st.set_page_config(page_title="Copy Template", layout="wide")

# --------------------------------------------------------------------
# 1) 패키지 임포트 경로 주입 (프로젝트 루트를 sys.path에 추가)
# --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # insert(0)로 최우선 경로로 주입하여 utils_common을 찾게 함
    sys.path.insert(0, str(ROOT)) 

# --------------------------------------------------------------------
# 2) 내부 모듈 임포트
# --------------------------------------------------------------------
# 레거시 item_uploader.app 임포트 오류 방지 (주석 처리 유지)
# from item_uploader.app import run as item_uploader_run # 원본 (오류 발생)

# [수정] item_uploader.utils_common 대신, repo root에 존재하는 utils_common에서 직접 임포트 시도
try:
    from utils_common import (
        extract_sheet_id, sheet_link,
        get_env, save_env_value
    )
except ImportError as e:
    st.error(f"유틸리티 모듈 로드 실패: {e}. [Root]에 utils_common.py가 있는지 확인하세요.")
    st.stop()


# =============================
# 사이드바 설정 폼 (이 페이지 전용)
# =============================
with st.sidebar:
    st.subheader("⚙️ 초기 설정")

    # 현재 세션에 저장된 값 or env 값
    cur_sid = st.session_state.get(
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
    )
    cur_host = st.session_state.get(
        "IMAGE_HOSTING_URL",
        get_env("IMAGE_HOSTING_URL")
    )

    with st.form("settings_form_copy_template"):
        sheet_url = st.text_input(
            "Google Sheets URL",
            value=sheet_link(cur_sid) if cur_sid else "",
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        image_host = st.text_input(
            "Image Hosting URL",
            value=cur_host or "",
            placeholder="예: https://shopeecopy.com/COVER/"
        )
        submitted = st.form_submit_button("저장")
        if submitted:
            sid = extract_sheet_id(sheet_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
            elif not image_host or not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요.")
            else:
                # 세션/환경 모두 업데이트
                st.session_state["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
                st.session_state["IMAGE_HOSTING_URL"] = image_host
                save_env_value("GOOGLE_SHEETS_SPREADSHEET_ID", sid)
                save_env_value("IMAGE_HOSTING_URL", image_host)
                st.success("설정이 저장되었습니다. 페이지를 새로고침합니다.")
                st.rerun()

# =============================
# 메인 페이지 (기존 run() 함수 대신 임시 메시지)
# =============================
st.title("Copy Template")
st.caption("Google Sheets 템플릿을 복사하고 초기 설정을 저장합니다.")

# 원래 run() 함수가 실행되어야 할 자리
# if 'item_uploader_run' in locals():
#     item_uploader_run()
# else:
st.warning("현재 'Copy Template' 페이지의 핵심 실행 로직을 불러올 수 없습니다. 임포트 경로 문제 해결 후 재시도해주세요.")
st.info("이 페이지의 오류는 현재 작업 중인 'Create Items' 페이지와는 별개입니다.")
