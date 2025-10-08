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
# [수정 시작] item_uploader.app 대신, 레거시 컨트롤러 역할을 하는 모듈에서 run 함수를 가져오는 것으로 추정
# item_uploader 패키지 구조가 불분명하므로, 임시로 automation_steps에서 가져오거나 주석 처리할 수 있습니다.
# 여기서는 오류가 나는 모듈 대신, 현재 존재하는 item_creator.main_controller의 ShopeeCreator를 가져와 페이지를 로드합니다.
# NOTE: 실제로 run 함수가 필요한지는 불분명하므로, 임포트만 해제하여 페이지 로드를 가능하게 합니다.
# from item_uploader.app import run as item_uploader_run # 원본 (오류 발생)

# 만약 item_uploader 페이지도 run() 함수를 필요로 한다면, 
# from item_uploader.automation_steps import run as item_uploader_run
# 가 필요하지만, 현재는 페이지 로드 오류 해결이 우선이므로 임포트를 삭제합니다.

from item_uploader.utils_common import (
    extract_sheet_id, sheet_link,
    get_env, save_env_value
)

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
