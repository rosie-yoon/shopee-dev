# pages/3_Create Items.py
# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import streamlit as st

# --------------------------------------------------------------------
# 1) 패키지 임포트 경로 주입
# --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# --------------------------------------------------------------------
# 2) 컨트롤러 임포트
# --------------------------------------------------------------------
try:
    from item_creator.main_controller import ShopeeCreator
except Exception as e:
    st.set_page_config(page_title="Create Template", layout="wide")
    st.error(f"컨트롤러 모듈 로드 실패: {e}")
    st.stop()

# --------------------------------------------------------------------
# 3) 레퍼런스 URL은 secrets에서만 로드 (노출 금지)
#    우선순위:
#    1) REFERENCE_SPREADSHEET_ID  ← (권장) 시트 ID
#       - ID가 'http'로 시작하면 그대로 URL로 간주
#       - 그 외에는 ID로 판단해 URL로 변환
#    2) (폴백) REF_SHEET_URL / REF_URL / ref_url / refs.sheet_url
# --------------------------------------------------------------------
def _get_ref_url_from_secrets() -> str | None:
    try:
        s = st.secrets
    except Exception:
        return None

    # 1) 권장: 시트 ID
    sid = s.get("REFERENCE_SPREADSHEET_ID")
    if sid:
        sid = str(sid).strip()
        # 혹시 URL을 넣어도 작동하도록 허용
        if sid.startswith("http"):
            return sid
        # 순수 ID이면 URL로 변환
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"

    # 2) 폴백 키들(기존 호환)
    for v in (
        s.get("REF_SHEET_URL"),
        s.get("REF_URL"),
        s.get("ref_url"),
        (s.get("refs") or {}).get("sheet_url") if isinstance(s.get("refs"), dict) else None,
    ):
        if v:
            return str(v)

    return None

REF_URL = _get_ref_url_from_secrets()

# --------------------------------------------------------------------
# 4) 페이지 설정 & 헤더
# --------------------------------------------------------------------
st.set_page_config(page_title="Create Template", layout="wide")
st.title("Create Template")
st.caption("‘상품등록’ 개인 시트 기반으로 신규 Mass Upload 템플릿을 생성합니다.")

# --------------------------------------------------------------------
# 5) 입력 폼 (레퍼런스 URL은 비노출)
# --------------------------------------------------------------------
c1, c2 = st.columns([1, 1])

with c1:
    shop_code = st.text_input("샵코드 (필수)", placeholder="예: RO", max_chars=8)

with c2:
    sheet_url = st.text_input("상품등록 시트 URL (필수)", placeholder="https://docs.google.com/...")

cover_url   = st.text_input("Cover base URL (필수)",   placeholder="https://example.com/covers/")
details_url = st.text_input("Details base URL (필수)", placeholder="https://example.com/details/")
option_url  = st.text_input("Option base URL (필수)",  placeholder="https://example.com/options/")

if not REF_URL:
    st.warning("`secrets`에 레퍼런스 시트 ID가 없습니다. `.streamlit/secrets.toml`에 "
               "`REFERENCE_SPREADSHEET_ID = \"<스프레드시트 ID>\"` 를 설정해 주세요.")
all_filled = all([shop_code, sheet_url, cover_url, details_url, option_url, REF_URL is not None])

st.divider()

# --------------------------------------------------------------------
# 6) 실행
# --------------------------------------------------------------------
run_disabled = not all_filled
if st.button("실행", type="primary", use_container_width=True, disabled=run_disabled):
    try:
        ctl = ShopeeCreator(sheet_url=sheet_url, ref_url=REF_URL)
        ok = ctl.run(
            shop_code=shop_code,
            cover_base_url=cover_url,
            details_base_url=details_url,
            option_base_url=option_url,
        )
        if not ok:
            st.error("실행 중 문제가 발생했습니다. Failures 시트를 확인하세요.")
        else:
            st.success("생성 완료! TEM_OUTPUT 시트를 확인하세요.")

            # TEM_OUTPUT CSV 내려받기
            try:
                csv_bytes = ctl.get_tem_values_csv()
                if csv_bytes:
                    st.download_button(
                        label="TEM_OUTPUT 내려받기 (CSV)",
                        data=csv_bytes,
                        file_name=f"{shop_code}_TEM_OUTPUT.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                else:
                    st.info("CSV 데이터가 비어 있습니다. TEM_OUTPUT 시트를 확인해 주세요.")
            except Exception as csv_err:
                st.warning(f"CSV 생성 중 오류: {csv_err}")

    except Exception as e:
        st.exception(e)
