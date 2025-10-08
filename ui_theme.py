# ui_theme.py
import streamlit as st

PRIMARY_GRADIENT = "linear-gradient(90deg,#93C5FD,#67E8F9)"

def apply_theme(hide_sidebar: bool = False, components_glass: bool = False) -> None:
    """앱 공통 테마 적용.
    - hide_sidebar=True  : 사이드바 완전 숨김 (Home)
    - hide_sidebar=False : 사이드바 노출 + 지정 톤
    - components_glass   : 버튼/업로더/입력 위젯을 글래스 톤으로 통일
    """
    sidebar_css = (
        # 완전 숨김 (Home)
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
          background: """ + PRIMARY_GRADIENT + """ !important;
          color:#1E293B !important;
          border-radius:10px !important;
          font-weight:800 !important;
        }
        section[data-testid="stSidebar"] [aria-current="page"] *{
          color:#1E293B !important;
        }
        """
    )

    components_css = (
        f"""
        /* ===== 버튼 (공통) ===== */
        div.stButton > button{{
          width:100% !important; padding:12px 16px !important; border-radius:12px !important;
          font-weight:800 !important; font-size:1.05rem !important; border:none !important;
          color:#FFFFFF !important;
          background: {PRIMARY_GRADIENT} !important;
          box-shadow:0 10px 15px -3px rgba(59,130,246,.5),0 4px 6px -2px rgba(59,130,246,.05) !important;
          transition: transform .15s ease;
        }}
        div.stButton > button:hover {{ transform: translateY(-1px); }}
        div.stButton > button:active {{ transform: scale(.98); }}

        /* ===== 파일 업로더 ===== */
        [data-testid="stFileUploaderDropzone"]{{
          background: rgba(255,255,255,.08) !important;
          border: 1px solid rgba(255,255,255,.12) !important;
          border-radius: 12px !important;
          backdrop-filter: blur(8px) !important;
          -webkit-backdrop-filter: blur(8px) !important;
        }}
        [data-testid="stFileUploaderDropzone"]:hover{{
          background: rgba(255,255,255,.12) !important;
          border-color: rgba(255,255,255,.18) !important;
        }}
        [data-testid="stFileUploader"] *{{ color: rgba(255,255,255,.9) !important; }}

        /* ===== 입력/선택 위젯 ===== */
        div[data-baseweb="input"],
        div[data-baseweb="select"],
        div[data-baseweb="textarea"]{{
          background: rgba(255,255,255,.08) !important;
          border: 1px solid rgba(255,255,255,.12) !important;
          border-radius: 10px !important;
        }}
        div[data-baseweb="input"] input,
        div[data-baseweb="select"] *{{ color:#fff !important; }}
        textarea{{
          background: rgba(255,255,255,.08) !important;
          border: 1px solid rgba(255,255,255,.12) !important;
          color:#fff !important; border-radius:10px !important;
        }}
        """
        if components_glass else
        ""
    )

    st.markdown(f"""
    <style>
      /* ===== 앱 베이스 ===== */
      html, body, [data-testid="stAppViewContainer"]{{
        background: linear-gradient(135deg,#1E293B 0%, #334155 100%);
        color:#fff; font-family: Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,'Noto Sans';
      }}
      [data-testid="stHeader"]{{ background: rgba(30,41,59,.8); }}
      h1, h2, h3, h4 {{ color:#fff; }}

      {sidebar_css}
      {components_css}
    </style>
    """, unsafe_allow_html=True)
