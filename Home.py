# Home.py (final)
import streamlit as st

__APP_VERSION__ = "v3"

st.set_page_config(
    page_title="Shopee Support",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
:root{
  --btn-bg: #2563EB;
  --btn-bg-hover: #1D4ED8;
  --btn-fg: #FFFFFF;
  --btn-radius: 14px;
  --btn-pad: 18px 24px;
  --btn-shadow: 0 8px 20px rgba(37,99,235,.20);
  --btn-font-size: 30px;
}
.stButton > button{
  background: var(--btn-bg) !important;
  color: var(--btn-fg) !important;
  border: 0 !important;
  border-radius: var(--btn-radius) !important;
  padding: var(--btn-pad) !important;
  font-weight: 700 !important;
  letter-spacing: .2px;
  height: auto !important;
  box-shadow: var(--btn-shadow);
  transition: transform .12s ease, filter .12s ease, background-color .12s ease;
  font-size: var(--btn-font-size) !important;
  line-height: 1.2 !important;
}
.stButton > button:hover{
  background: var(--btn-bg-hover) !important;
  transform: translateY(-1px);
  filter: brightness(1.02);
}
.stButton > button:active{
  transform: translateY(0) scale(.99);
}
@media (min-width: 1200px){
  .stButton > button{ font-size: 22px !important; }
}
</style>
""", unsafe_allow_html=True)

st.title("🌐 Shopee Support Tools")
st.info(
    "Cover Image : 썸네일로 사용할 커버 이미지를 생성하는 메뉴입니다.\n\n"
    "Copy Template : 샵 복제 시 사용할 Mass Upload 파일을 생성하는 메뉴입니다.\n\n"
    "Create New Items : ‘상품등록’ 개인 시트를 기반으로 신규 아이템 업로드 템플릿을 생성합니다."
)

st.divider()

col1, col2 = st.columns(2)
with col1:
    if hasattr(st, "switch_page"):
        if st.button("Cover Image", use_container_width=True, key="btn_cover"):
            st.switch_page("pages/1_Cover Image.py")
    else:
        st.page_link("pages/1_Cover Image.py", label="Cover Image", use_container_width=True)

with col2:
    if hasattr(st, "switch_page"):
        if st.button("Copy Template", use_container_width=True, key="btn_copy"):
            st.switch_page("pages/2_Copy Template.py")
    else:
        st.page_link("pages/2_Copy Template.py", label="Copy Template", use_container_width=True)

st.divider()
if hasattr(st, "switch_page"):
    if st.button("🧩 Create New Items", use_container_width=True, key="btn_create"):
        st.switch_page("pages/3_Create Items.py")
else:
    st.page_link("pages/3_Create Items.py", label="🧩 Create New Items", use_container_width=True)

st.caption(f"Version: {__APP_VERSION__}")

