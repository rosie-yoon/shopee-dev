# ui_theme.py
import streamlit as st

def apply_theme(hide_sidebar: bool = False):
    """앱 공통 테마 적용. hide_sidebar=True면 완전 숨김."""
    sidebar_block = (
        # 완전 숨김 (홈 같은 곳)
        """
        section[data-testid="stSidebar"]{ display:none !important; }
        [data-testid="stAppViewContainer"]{ margin-left:0 !important; }
        """
        if hide_sidebar else
        # 보이되 톤 적용 (다른 페이지들)
        """
        section[data-testid="stSidebar"]{
          background: rgba(0,0,0,.2) !important;
          backdrop-filter: blur(8px) !important;
          -webkit-backdrop-filter: blur(8px) !important;
        }
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] span { color:#D1D5DB !important; }
        section[data-testid="stSidebar"] [aria-current="page"]{
          background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
          color:#1E293B !important;
          border-radius:10px !important;
          font-weight:800 !important;
        }
        section[data-testid="stSidebar"] [aria-current="page"] *{
          color:#1E293B !important;
        }
        """
    )

    css = f"""
    <style>
      html, body, [data-testid="stAppViewContainer"]{{
        background: linear-gradient(135deg,#1E293B 0%, #334155 100%);
        color:#fff; font-family: Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,'Noto Sans';
      }}
      [data-testid="stHeader"]{{ background: rgba(30,41,59,.8); }}
      h1, h2, h3, h4 {{ color:#fff; }}
      {sidebar_block}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
