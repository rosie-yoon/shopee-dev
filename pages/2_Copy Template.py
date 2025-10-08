# pages/2_Copy Template.py
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


from pathlib import Path
import sys
import streamlit as st

st.set_page_config(page_title="Copy Template", layout="wide")

# --------------------------------------------------------------------
# 1) 패키지 임포트 경로 주입 (루트 폴더)
# --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------
# 2) 내부 모듈 임포트: 레거시 경로(item_uploader.*) 대신 루트 utils_common 사용
# --------------------------------------------------------------------
# [수정] 레거시 item_uploader 경로를 모두 제거하고 루트 utils_common 사용
import utils_common
from shopee_v1.utils_common import (
    extract_sheet_id, sheet_link,
    get_env, save_env_value
)

# ====================================================================
# 페이지 로직
# ====================================================================

# 레거시 item_uploader.app.run 호출 로직은 페이지 로드 오류를 막기 위해 제거
try:
    pass
except Exception:
    pass

# ==============================
# 사이드바 설정 폼 (이 페이지 전용)
# ==============================
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
                st.success("설정이 저장되었습니다.")
                st.experimental_rerun()
