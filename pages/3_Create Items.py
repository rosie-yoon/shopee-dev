# pages/3_Create Items.py
# -*- coding: utf-8 -*-
import os
import traceback
from pathlib import Path
import sys
from urllib.parse import urlparse
import streamlit as st

# 프로젝트 루트(shopee_v1) 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui_theme import apply_theme, title_with_icon
from item_creator.utils_common import (
    get_env,
    save_env_value,
    extract_sheet_id,
    sheet_link,
)

# ---------------------------------------------------------
# 페이지 기본 설정 (page_icon 미사용)
# ---------------------------------------------------------
st.set_page_config(page_title="Create Template", layout="wide", initial_sidebar_state="expanded")

# 전역 테마 (사이드바 노출, 컴포넌트 글래스)
apply_theme(hide_sidebar=False)

# 타이틀 + PNG 아이콘
title_with_icon("Create Template", "create")

st.caption("‘상품등록’ 개인 시트(MARGIN / Collection)를 기반으로 TEM_OUTPUT를 생성합니다.")

# ---------------------------------------------------------
# 페이지 전용 CSS (카드/입력/버튼 시각 정리)
# ---------------------------------------------------------
custom_css = """
<style>
  .glass-card {
    background-color: rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 4px 18px rgba(0,0,0,0.25), inset 0 0 0 1px rgba(255,255,255,0.05);
    border-radius: 16px;
    padding: 24px;
    margin: 8px 0 18px;
  }
  .field-row { display:flex; gap:14px; align-items:flex-end; }
  .hint { color: rgba(255,255,255,.75); font-size: 0.9rem; margin-top: 4px; }
  .ok { color:#86efac; font-weight:700; }     /* ✅ */
  .warn { color:#fca5a5; font-weight:700; }   /* ⚠️ */
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# ---------------------------------------------------------
# 유틸: URL 검증
# ---------------------------------------------------------
def is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

# ---------------------------------------------------------
# 저장된 값 프리필
# ---------------------------------------------------------
_saved_creation_id = get_env("CREATION_SPREADSHEET_ID", "")
_saved_cover_base  = get_env("CREATION_COVER_BASE_URL", "")
_saved_detail_base = get_env("CREATION_DETAILS_BASE_URL", "")
_saved_option_base = get_env("CREATION_OPTION_BASE_URL", "")

_prefill_url = sheet_link(_saved_creation_id) if _saved_creation_id else ""

# =========================================================
# 1) 입력 + 저장 + 실행  (한 폼으로 통합)
# =========================================================
with st.form("create_form"):
    st.subheader("설정 (필수)")

    # 폼 그리드
    c1, c2 = st.columns(2)
    with c1:
        creation_url = st.text_input(
            "상품등록 시트 URL",
            value=_prefill_url,
            placeholder="https://docs.google.com/spreadsheets/d/XXXXXXXXXXXX/edit",
            help="MARGIN / Collection 탭이 존재하는 '상품등록' 시트 URL 전체를 붙여넣으세요.",
        )
        cover_base = st.text_input(
            "커버 호스팅 주소",
            value=_saved_cover_base,
            placeholder="예) https://img.example.com/COVER/",
            help="Variation 코드가 없으면 SKU와 맵핑하여 커버 이미지를 지정합니다.",
        )
    with c2:
        detail_base = st.text_input(
            "상세 호스팅 주소",
            value=_saved_detail_base,
            placeholder="예) https://img.example.com/DETAILS/",
            help="Item Image 1~8(상세 이미지)의 베이스 URL입니다.",
        )
        option_base = st.text_input(
            "옵션(SKU) 호스팅 주소",
            value=_saved_option_base,
            placeholder="예) https://img.example.com/SKU/",
            help="옵션 이미지의 베이스 URL입니다.",
        )

    # ---- 즉시 검증 표시 (가벼운 시각 피드백) ----
    sid_preview = extract_sheet_id(creation_url)
    url_ok = {
        "cover":  bool(cover_base  and is_valid_url(cover_base)),
        "detail": bool(detail_base and is_valid_url(detail_base)),
        "option": bool(option_base and is_valid_url(option_base)),
    }
    cols_chk = st.columns(4)
    with cols_chk[0]:
        st.markdown(f"**시트 ID** : {'✅' if sid_preview else '⚠️'} "
                    f"<span class='{'ok' if sid_preview else 'warn'}'>{sid_preview or '미검출'}</span>",
                    unsafe_allow_html=True)
    with cols_chk[1]:
        st.markdown(f"**Cover** : {'✅' if url_ok['cover'] else '⚠️'}", unsafe_allow_html=True)
    with cols_chk[2]:
        st.markdown(f"**Details** : {'✅' if url_ok['detail'] else '⚠️'}", unsafe_allow_html=True)
    with cols_chk[3]:
        st.markdown(f"**Option** : {'✅' if url_ok['option'] else '⚠️'}", unsafe_allow_html=True)

    # ---- 카드 스타일로 감싸기 ----
    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hint'>Tips: 기본값을 저장해두면 다음 방문 시 자동으로 채워집니다. "
        "URL은 반드시 http(s)로 시작해야 합니다.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- 폼 내 액션 (둘 다 submit 가능) ----
    a1, a2 = st.columns([1, 1])
    with a1:
        save_btn = st.form_submit_button("저장")
    with a2:
        # 모든 값이 올바르면 실행 버튼 활성화
        all_valid = bool(sid_preview and url_ok["cover"] and url_ok["detail"] and url_ok["option"])
        run_btn = st.form_submit_button("실행 (Create)", disabled=not all_valid)

# =========================================================
# 1-1) 저장 처리
# =========================================================
if save_btn:
    sid = extract_sheet_id(creation_url)
    if not sid:
        st.error("유효한 Google Sheets URL이 아닙니다. 전체 URL을 붙여넣었는지 확인하세요.")
    elif not (cover_base and detail_base and option_base):
        st.error("Cover / Details / Option Base URL을 모두 입력하세요.")
    elif not (is_valid_url(cover_base) and is_valid_url(detail_base) and is_valid_url(option_base)):
        st.error("Base URL 형식이 올바르지 않습니다. http(s):// 로 시작하는지 확인하세요.")
    else:
        save_env_value("CREATION_SPREADSHEET_ID", sid)
        save_env_value("CREATION_COVER_BASE_URL", cover_base.strip())
        save_env_value("CREATION_DETAILS_BASE_URL", detail_base.strip())
        save_env_value("CREATION_OPTION_BASE_URL", option_base.strip())
        st.success("저장 완료! (로컬 .env 업데이트)")
        st.info(f"상품등록 시트: {sheet_link(sid)}")

# =========================================================
# 1-2) 실행 처리
# =========================================================
if 'run_btn' in locals() and run_btn:
    log_area = st.empty()
    prog = st.progress(0, text="초기화 중...")

    sid = extract_sheet_id(creation_url)
    cover = (cover_base or "").strip()
    detail = (detail_base or "").strip()
    option = (option_base or "").strip()

    try:
        try:
            from item_creator.main_controller import ShopeeCreator
        except Exception:
            st.error("컨트롤러 모듈(item_creator/main_controller.py)이 아직 준비되지 않았습니다.")
            st.stop()

        creator = ShopeeCreator(
            creation_spreadsheet_id=sid,
            cover_base_url=cover,
            details_base_url=detail,
            option_base_url=option,
            ref_spreadsheet_id=get_env("REFERENCE_SPREADSHEET_ID", "") or None,
        )

        prog.progress(5, text="Step 준비 중...")
        result = creator.run(
            progress_callback=lambda p, msg: (
                prog.progress(min(max(int(p), 0), 100), text=msg),
                log_area.write(msg),
            )
        )
        prog.progress(100, text="완료!")
        st.success("생성 완료!")

        if isinstance(result, dict):
            if result.get("logs"):
                with st.expander("실행 로그", expanded=False):
                    for ln in result["logs"]:
                        st.write(ln)
            if result.get("download_path"):
                fp = result["download_path"]
                fname = result.get("download_name") or os.path.basename(fp)
                with open(fp, "rb") as f:
                    st.download_button(
                        "📥 파일 다운로드",
                        data=f,
                        file_name=fname,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
        else:
            st.info("컨트롤러에서 반환된 결과 포맷을 확인하세요. dict 형태를 권장합니다.")
    except Exception:
        st.error("실행 중 오류가 발생했습니다.")
        st.code(traceback.format_exc())

# (선택) 저장된 값 간단 보기
with st.expander("저장된 기본값 보기", expanded=False):
    st.markdown(f"- **CREATION_SPREADSHEET_ID**: `{_saved_creation_id or '(미설정)'} `{'' if not _saved_creation_id else f'→ {sheet_link(_saved_creation_id)}`'}")
    st.markdown(f"- **CREATION_COVER_BASE_URL**: `{_saved_cover_base or '(미설정)'}`")
    st.markdown(f"- **CREATION_DETAILS_BASE_URL**: `{_saved_detail_base or '(미설정)'}`")
    st.markdown(f"- **CREATION_OPTION_BASE_URL**: `{_saved_option_base or '(미설정)'}`")
