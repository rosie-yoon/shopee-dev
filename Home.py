# Home.py
# -*- coding: utf-8 -*-
import base64
from pathlib import Path
import streamlit as st

# 공통 테마 (사이드바 톤/숨김 관리)
from ui_theme import apply_theme

# --------------------------------------------------------------------
# 기본 설정
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",  # 홈에서는 기본 접힘
)

# 홈은 사이드바 완전 숨김(다른 페이지는 hide_sidebar=False로 호출)
apply_theme(hide_sidebar=True)

# --------------------------------------------------------------------
# 아이콘 유틸
# --------------------------------------------------------------------
ICON_DIR = Path("assets/icons")

def resolve_icon(name: str) -> Path:
    """@3x 우선, 없으면 1x PNG 사용"""
    hi = ICON_DIR / f"{name}@3x.png"
    lo = ICON_DIR / f"{name}.png"
    return hi if hi.exists() else lo

def icon_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

ICONS = {
    "cover":  resolve_icon("cover"),
    "copy":   resolve_icon("copy"),
    "create": resolve_icon("create"),
}

# --------------------------------------------------------------------
# 페이지 전용 스타일 (카드/버튼만)
# --------------------------------------------------------------------
st.markdown(
    """
    <style>
      /* 카드: 단일 레이어 */
      .ui-card{
        background: rgba(255,255,255,.08);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius:16px; padding:14px 16px 16px;
        box-shadow:0 4px 18px rgba(0,0,0,.25), inset 0 0 0 1px rgba(255,255,255,.05);
        transition: background .25s ease;
        min-height: 130px;
      }
      .ui-card:hover{ background: rgba(255,255,255,.12); }

      /* 헤더(아이콘+타이틀) 가로 정렬 */
      .row{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }
      .row img{ width:36px; height:36px; flex:0 0 auto; }
      .row .title{ font-weight:800; font-size:1.1rem; margin:0; }

      .desc{ margin:0; color:rgba(255,255,255,.85); }

      /* 시작하기 버튼(카드 밖) — 흰 글자 */
      div.stButton > button{
        width:100% !important; padding:12px 16px !important; border-radius:12px !important;
        font-weight:800 !important; font-size:1.05rem !important; border:none !important;
        color:#1E293B !important;
        background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
        box-shadow:0 10px 15px -3px rgba(59,130,246,.5),0 4px 6px -2px rgba(59,130,246,.05) !important;
        transition: transform .15s ease; margin-top:8px;
      }
      div.stButton > button:hover { transform: translateY(-1px); }
      div.stButton > button:active { transform: scale(.98); }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------
# 본문
# --------------------------------------------------------------------
st.title("Shopee Support Tools")
st.divider()

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

cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        b64 = icon_b64(c["icon"]) if Path(c["icon"]).exists() else ""
        st.markdown(
            f"""
            <div class="ui-card">
              <div class="row">
                {'<img src="data:image/png;base64,'+b64+'" alt="icon"/>' if b64 else ''}
                <div class="title">{c["title"]}</div>
              </div>
              <p class="desc">{c["desc"]}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if hasattr(st, "switch_page"):
            if st.button("시작하기", use_container_width=True, key=c["key"]):
                st.switch_page(c["path"])
        else:
            st.page_link(c["path"], label="시작하기")

st.divider()
st.caption("Version: v3")
