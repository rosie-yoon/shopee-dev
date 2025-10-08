# pages/3_Create Items.py
# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import streamlit as st

# --------------------------------------------------------------------
# 1) 패키지 임포트용 경로 주입 (중요)
# --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# --------------------------------------------------------------------
# 2) 컨트롤러 안전 임포트
# --------------------------------------------------------------------
try:
    from item_creator.main_controller import ShopeeCreator
except Exception as e:
    st.set_page_config(page_title="Create Template", layout="wide")
    st.error(f"컨트롤러 모듈 로드 실패: {e}")
    st.stop()

# --------------------------------------------------------------------
# 3) 레퍼런스 URL은 secrets에서만 로드 (값은 화면에 표시하지 않음)
#    - 우선순위: REF_SHEET_URL > REF_URL > ref_url > refs.sheet_url
# --------------------------------------------------------------------
def _get_ref_url_from_secrets() -> str | None:
    try:
        s = st.secrets
    except Exception:
        return None

    # 여러 키 패턴 지원
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
# 4) 페이지 설정 & 제목
# --------------------------------------------------------------------
st.set_page_config(page_title="Create Template", layout="wide")
st.title("Create Template")
st.caption("‘상품등록’ 개인 시트 기반으로 신규 Mass Upload 템플릿을 생성합니다.")

# --------------------------------------------------------------------
# 5) 입력 폼 (사용자에겐 레퍼런스 URL 입력란을 노출하지 않음)
# --------------------------------------------------------------------
c1, c2 = st.columns([1, 1])

with c1:
    shop_code = st.text_input("샵코드 (필수)", placeholder="예: RO", max_chars=8)

with c2:
    sheet_url = st.text_input("상품등록 시트 URL (필수)", placeholder="https://docs.google.com/...")

cover_url   = st.text_input("Cover base URL (필수)",   placeholder="https://example.com/covers/")
details_url = st.text_input("Details base URL (필수)", placeholder="https://example.com/details/")
option_url  = st.text_input("Option base URL (필수)",  placeholder="https://example.com/options/")

# 레퍼런스 URL이 없으면 실행 비활성화 + 경고
if not REF_URL:
    st.warning("레퍼런스 시트 URL이 secrets에 설정되어 있지 않습니다. 관리자에게 문의하세요. (예: REF_SHEET_URL)")
all_filled = all([shop_code, sheet_url, cover_url, details_url, option_url, REF_URL is not None])

st.divider()

# --------------------------------------------------------------------
# 6) 실행
# --------------------------------------------------------------------
run_disabled = not all_filled
if st.button("실행", type="primary", use_container_width=True, disabled=run_disabled):
    try:
        ctl = ShopeeCreator(sheet_url=sheet_url, ref_url=REF_URL)  # ← 사용자 입력 대신 secrets 사용
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

            # CSV 내려받기 (값 자체는 노출 X)
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
