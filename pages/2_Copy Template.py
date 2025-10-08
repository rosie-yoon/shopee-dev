# pages/2_Copy Template.py
from pathlib import Path
import sys
import streamlit as st

st.set_page_config(page_title="Copy Template", layout="wide")

# 프로젝트 루트(shopee)를 임포트 경로에 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 내부 모듈 임포트
from item_uploader.app import run as item_uploader_run
from item_uploader.utils_common import (
    extract_sheet_id, sheet_link,
    get_env, save_env_value
)

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
                st.success("설정이 저장되었습니다!")
                st.rerun()

apply_theme(hide_sidebar=False, components_glass=True)

# ==============================
# 메인 실행
# ==============================
item_uploader_run()
