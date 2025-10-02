# item_uploader/app.py
# -*- coding: utf-8 -*-
"""ITEM UPLOADER Streamlit app (clean multipage version, without settings dialog)."""

from __future__ import annotations

from pathlib import Path
import streamlit as st

# ---- 패키지 내부 모듈: 상대 임포트로 통일 ----
from .utils_common import (
    get_env, load_env
)
from .upload_apply import collect_xlsx_files, apply_uploaded_files
from .main_controller import ShopeeAutomation


def run() -> None:
    """Bridge(멀티페이지) 환경에서 호출되는 진입점."""
    # (중요) 환경/설정 로드: import 시점이 아니라 실행 시점에 로드
    load_env()

    # ---- 세션 상태 초기화 ----
    defaults = {
        "upload_success": False,
        "automation_success": False,
        "download_file": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    # ---- 헤더 / 타이틀 ----
    st.title("⬆️ Copy Template")

    # ---- CSS ----
    st.markdown(
        """
<style>
html, body, [class*="st-"] { font-family: 'Inter','Noto Sans KR',sans-serif; }
div[data-testid="stAppViewContainer"] > .main .block-container {
  padding-top: 2rem; padding-bottom: 2rem; max-width: 900px;
}
.stButton>button {
  border-radius: 8px; padding: 8px 18px; font-weight: 600; border: none;
  color: white; background-color: #1A73E8; transition: background-color 0.3s ease;
}
.stButton>button:hover { background-color: #0e458c; }
.stButton>button:disabled { background-color: #E0E0E0; color: #A0A0A0; }
.stFileUploader { border: 2px dashed #E0E0E0; border-radius: 12px; padding: 20px; background-color: #F9F9F9; }
.log-container {
  background-color: #F9F9F9; border-radius: 8px; padding: 15px; margin-top: 15px;
  font-family: 'SF Mono','Menlo',monospace; font-size: 0.9em; max-height: 400px; overflow-y: auto; border: 1px solid #E0E0E0;
}
.log-success { color: #2E7D32; } .log-error { color: #C62828; } .log-warn { color: #EF6C00; } .log-info { color: #333; }
h1, h2, h3, h5 { font-weight: 700; }
.dialog-description { font-size: 0.9rem; color: #4A4A4A; margin-top: -5px; margin-bottom: 1.5rem; line-height: 1.5; }
</style>
""",
        unsafe_allow_html=True,
    )

    # ---- 메인 앱 ----
    def main_application():
        # 상단 가이드 (설정 다이얼로그 버튼 제거됨)
        st.markdown(
            """
<p>아래 영역에 BASIC, MEDIA, SALES 엑셀 파일을 업로드하고 샵 코드를 입력한 후, 실행 버튼을 눌러주세요.</p>
""",
            unsafe_allow_html=True,
        )

        # --- 입력 영역 ---
        st.subheader("1. 파일 및 샵 코드 입력")
        uploaded_files = st.file_uploader(
            "BASIC, MEDIA, SALES 파일을 한 번에 선택하거나 드래그 앤 드롭하세요.",
            type="xlsx",
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        shop_code = st.text_input(
            "샵 코드 (Shop Code) 입력",
            placeholder="예: RO, VN 등 국가 코드를 입력하세요.",
            key="shop_code_input",
        )

        is_ready = bool(uploaded_files and shop_code)

        if st.button("🚀 파일 업로드 및 전체 자동화 실행", key="run_all", disabled=not is_ready):
            # 상태 초기화
            st.session_state.upload_success = False
            st.session_state.automation_success = False
            st.session_state.download_file = None

            with st.status("자동화 실행 중...", expanded=True) as status:
                try:
                    # 1) 업로드 반영
                    st.write("1/3 - Shop SKU 파일 업로드 중...")
                    files_dict = collect_xlsx_files(uploaded_files)
                    if len(files_dict) < 3:
                        st.session_state.upload_success = False
                        status.update(label="업로드 실패", state="error", expanded=True)
                        st.error(
                            f"파일 3개(BASIC, MEDIA, SALES)를 모두 업로드해야 합니다. (현재 {len(files_dict)}개)"
                        )
                        return

                    logs = apply_uploaded_files(files_dict)
                    if any("[OK]" in log for log in logs):
                        st.session_state.upload_success = True
                        st.write("✅ 파일 업로드 완료!")
                    else:
                        status.update(label="업로드 실패", state="error", expanded=True)
                        st.error("파일을 Google Sheets에 반영하는 데 실패했습니다. 로그를 확인하세요.")
                        st.json(logs)
                        return

                    # 2) 자동화
                    st.write("2/3 - 템플릿 생성 자동화 진행 중... (Step 1~6)")
                    automation = ShopeeAutomation()
                    progress_bar = st.progress(0, text="자동화 단계를 시작합니다...")
                    log_container = st.empty()

                    success, results = automation.run_all_steps_with_progress(
                        progress_bar, log_container, shop_code
                    )
                    st.session_state.automation_success = success

                    if not success:
                        status.update(label="자동화 실패", state="error", expanded=True)
                        st.error("자동화 실행 중 오류가 발생했습니다. 위 로그를 확인하세요.")
                        return

                    # 3) 다운로드 파일 생성
                    st.write("3/3 - 최종 엑셀 파일 생성 중... (Step 7)")
                    download_data = automation.run_step7_generate_download()

                    if download_data:
                        st.session_state.download_file = download_data
                        status.update(label="🎉 모든 단계 완료!", state="complete", expanded=True)
                        st.success("모든 자동화 단계가 성공적으로 완료되었습니다!")
                    else:
                        st.session_state.automation_success = False
                        status.update(label="다운로드 파일 생성 실패", state="error", expanded=True)
                        st.error("최종 엑셀 파일을 생성하는 데 실패했습니다.")

                except Exception as e:
                    status.update(label="치명적인 오류 발생", state="error", expanded=True)
                    st.error("프로그램 실행 중 예상치 못한 심각한 오류가 발생했습니다.")
                    st.exception(e)

        st.divider()

        # --- 다운로드 섹션 ---
        st.subheader("2. 최종 파일 다운로드")
        if st.session_state.automation_success and st.session_state.download_file:
            st.download_button(
                label="⬇️ 템플릿 파일 다운로드 (.xlsx)",
                data=st.session_state.download_file,
                file_name="Shopee_Upload_Template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.info("자동화가 성공적으로 완료되면 여기에 다운로드 버튼이 나타납니다.")

    # 설정 다이얼로그/호출 제거 → 메인 앱만 실행
    main_application()


# 단독 실행 지원(브릿지 없이 app.py만 직접 실행 시)
if __name__ == "__main__":
    st.set_page_config(page_title="ITEM UPLOADER", page_icon="⬆️", layout="wide")
    run()
