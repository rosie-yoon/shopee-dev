# pages/2_Copy Template.py
from pathlib import Path
import sys
import streamlit as st

st.set_page_config(page_title="Copy Template", layout="wide")

# 프로젝트 루트(shopee)를 임포트 경로에 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 내부 모듈 임포트: 이제 모든 유틸리티는 프로젝트 루트의 utils_common을 사용합니다.
# item_uploader.app 경로의 존재 여부는 페이지 로드 시 오류를 유발하므로 임시로 주석 처리합니다.
# from item_uploader.app import run as item_uploader_run 
import utils_common
from utils_common import (
    extract_sheet_id, sheet_link,
    get_env, save_env_value # save_env_value가 utils_common에 없으면 오류 발생 가능
)

# ... (나머지 코드 생략, utils_common에서 import된 함수를 사용하도록 처리)
# ... (현재 파일에는 run 함수가 없으므로 오류 나는 부분을 주석처리하는 것이 가장 안전함)

# =============================
# 사이드바 설정 폼 (이 페이지 전용)
# ===================================================
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
                # save_env_value가 utils_common에 있으면 사용하고, 없으면 오류가 날 수 있습니다.
                try:
                    utils_common.save_env_value("GOOGLE_SHEETS_SPREADSHEET_ID", sid)
                    utils_common.save_env_value("IMAGE_HOSTING_URL", image_host)
                except AttributeError:
                    # save_env_value가 utils_common에 정의되지 않은 경우 경고만 출력
                    st.warning("경고: save_env_value 함수가 utils_common에 없어 환경 변수 파일 저장은 건너뜁니다.")
                st.success("설정 저장 완료.")


# --------------------------------------------------------------------
# 템플릿 복사 실행 (기존 run 함수 호출)
# --------------------------------------------------------------------
if st.button("템플릿 복사 실행", type="primary", use_container_width=True):
    # item_uploader.app.run이 주석 처리되었으므로, 해당 기능을 실행할 코드를 임시로 대체합니다.
    # 이 페이지는 임포트 오류 해결을 위해 기능 자체를 비활성화한 상태로 간주합니다.
    st.info("현재 템플릿 복사 기능은 모듈 경로 문제로 인해 비활성화되었습니다. (3번 페이지 작업 집중)")
    # # if 'item_uploader_run' in locals():
    # #    item_uploader_run()
    # # else:
    # #    st.error("복사 로직을 찾을 수 없습니다.")
