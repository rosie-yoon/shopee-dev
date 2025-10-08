# Home.py
# -*- coding: utf-8 -*-
import streamlit as st
from pathlib import Path

# --------------------------------------------------------------------
# 기본 설정
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
)

# --------------------------------------------------------------------
# 아이콘 경로
# --------------------------------------------------------------------
ICON_DIR = Path("assets/icons")
ICONS = {
    "cover":  ICON_DIR / "cover@3x.png",
    "copy":   ICON_DIR / "copy@3x.png",
    "create": ICON_DIR / "create@3x.png",
}

# --------------------------------------------------------------------
# 스타일 (Glassmorphism + 버튼 통일)
# --------------------------------------------------------------------
st.markdown(
    """
    <style>
      html, body, [data-testid="stAppViewContainer"]{
        background: linear-gradient(135deg,#1E293B 0%, #334155 100%);
        color: #fff;
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, 'Noto Sans';
      }
      [data-testid="stHeader"]{ background: rgba(30,41,59,.8); }
      h1, h2, h3, h4 { color: #fff; }

      .glass-card{
        background: rgba(255,255,255,.08);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 16px;
        padding: 22px;
        min-height: 250px;
        box-shadow: 0 4px 18px rgba(0,0,0,.25),
                    inset 0 0 0 1px rgba(255,255,255,.05);
        transition: background .25s ease;
      }
      .glass-card:hover{ background: rgba(255,255,255,.12); }

      div.stButton > button{
        width: 100% !important;
        padding: 12px 16px !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        font-size: 1.05rem !important;
        border: none !important;
        color: #1E293B !important;
        background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
        box-shadow: 0 10px 15px -3px rgba(59,130,246,.5),
                    0 4px 6px -2px rgba(59,130,246,.05) !important;
        transition: transform .15s ease;
      }
      div.stButton > button:hover { transform: translateY(-1px); }
      div.stButton > button:active { transform: scale(.98); }

      .card-title{ margin: 6px 0 8px; font-weight: 800; font-size: 1.25rem; }
      .card-desc{ margin: 0 0 14px; color: rgba(255,255,255,.75); }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------
# 카드 데이터
# --------------------------------------------------------------------
cards = [
    {
        "icon": ICONS["cover"],
        "title": "Cover Image",
        "desc": "썸네일로 사용할 커버 이미지 생성",
        "path": "pages/1_Cover Image.py",
        "key": "card_cover",
    },
    {
        "icon": ICONS["copy"],
        "title": "Copy Template",
        "desc": "복제용 Mass Upload 템플릿 생성",
        "path": "pages/2_Copy Template.py",
        "key": "card_copy",
    },
    {
        "icon": ICONS["create"],
        "title": "Create Template",
        "desc": "신규 상품 Mass Upload 템플릿 생성",
        "path": "pages/3_Create Items.py",
        "key": "card_create",
    },
]

# --------------------------------------------------------------------
# 3열 레이아웃 카드 렌더
# --------------------------------------------------------------------
cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)

        # 아이콘
        if Path(c["icon"]).exists():
            st.image(str(c["icon"]), width=48)

        # 텍스트
        st.markdown(f'<div class="card-title">{c["title"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card-desc">{c["desc"]}</div>', unsafe_allow_html=True)

        # 버튼 (신버전: switch_page, 구버전: page_link)
        if hasattr(st, "switch_page"):
            if st.button("시작하기", use_container_width=True, key=c["key"]):
                st.switch_page(c["path"])
        else:
            st.page_link(c["path"], label="시작하기")  # use_container_width 제거

        st.markdown("</div>", unsafe_allow_html=True)

st.divider()
st.caption("Version: v3")
