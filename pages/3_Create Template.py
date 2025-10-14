# pages/3_Create Template.py
# -*- coding: utf-8 -*-
import streamlit as st
from shopee_creator.controller import ShopeeCreator
from shopee_creator.creation_steps import export_tem_xlsx, export_tem_csv

# --------------------------------------------------------------------
# 1) 페이지 설정
# --------------------------------------------------------------------
st.set_page_config(page_title="Create Template (Item-Creator)", layout="wide")
st.title("Create Template")
st.caption("상품등록 시트를 기반으로 신규 Mass Upload 템플릿을 생성합니다.")

# --------------------------------------------------------------------
# 2) Secrets 기반 레퍼런스 URL 가져오기
# --------------------------------------------------------------------
def _get_ref_url_from_secrets() -> str | None:
    try:
        s = st.secrets
    except Exception:
        return None

    sid = s.get("REFERENCE_SPREADSHEET_ID")
    if sid:
        sid = str(sid).strip()
        if sid.startswith("http"):
            return sid
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"

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
if not REF_URL:
    st.warning("`secrets`에 레퍼런스 시트 ID가 없습니다. "
               "`.streamlit/secrets.toml`에 `REFERENCE_SPREADSHEET_ID`를 설정해 주세요.")

# --------------------------------------------------------------------
# 3) 입력 폼
# --------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    shop_code = st.text_input("샵코드 (필수)", placeholder="예: RO", max_chars=8)
with c2:
    sheet_url = st.text_input("상품등록 시트 URL (필수)", placeholder="https://docs.google.com/...")

base_url = st.text_input(
    "이미지 Base URL (필수)",
    placeholder="https://example.com/assets/"
)

all_filled = all([shop_code, sheet_url, base_url, REF_URL])
st.divider()

# --------------------------------------------------------------------
# 4) 실행 버튼
# --------------------------------------------------------------------
run_disabled = not all_filled

if st.button("실행", type="primary", use_container_width=True, disabled=run_disabled):
    try:
        ctrl = ShopeeCreator(st.secrets)
        ctrl.set_image_bases(
            shop_code=shop_code,
            cover=base_url,
            details=base_url,
            option=base_url
        )
        with st.spinner("C1~C6 단계 실행 중..."):
            results = ctrl.run(input_sheet_url=sheet_url)

        st.success("템플릿 생성 완료 ✅")
        for log in results:
            with st.expander(f"{'✅' if log.ok else '❌'} {log.name}", expanded=not log.ok):
                st.write({
                    "ok": log.ok,
                    "count": log.count,
                    "error": log.error
                })

        # TEM_OUTPUT 시트에서 XLSX 추출
        try:
            sh = ctrl.gs.open_by_url(sheet_url)  # ✅ 수정됨 (sheet_by_url → open_by_url)
            xlsx_io = export_tem_xlsx(sh)
            if xlsx_io:
                st.download_button(
                    "TEM_OUTPUT 내려받기 (XLSX)",
                    data=xlsx_io.getvalue(),
                    file_name=f"{shop_code}_TEM_OUTPUT.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                csv_bytes = export_tem_csv(sh)
                if csv_bytes:
                    st.download_button(
                        "TEM_OUTPUT 내려받기 (CSV - 폴백)",
                        data=csv_bytes,
                        file_name=f"{shop_code}_TEM_OUTPUT.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                else:
                    st.info("다운로드 데이터가 없습니다. TEM_OUTPUT 시트를 확인해 주세요.")
        except Exception as ex:
            st.warning(f"다운로드 생성 중 오류: {ex}")

    except Exception as e:
        st.exception(e)
