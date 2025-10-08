# Home.py
# -*- coding: utf-8 -*-
import streamlit as st
from pathlib import Path
import base64

st.set_page_config(page_title="Shopee Support Tools", layout="wide")

ICON_DIR = Path("assets/icons")
ICONS = {
    "cover":  ICON_DIR / "cover@3x.png",
    "copy":   ICON_DIR / "copy@3x.png",
    "create": ICON_DIR / "create@3x.png",
}

def icon_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ------------------------ CSS ------------------------
st.markdown("""
<style>
  html, body, [data-testid="stAppViewContainer"]{
    background: linear-gradient(135deg,#1E293B 0%, #334155 100%);
    color:#fff; font-family: Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,'Noto Sans';
  }
  [data-testid="stHeader"]{ background: rgba(30,41,59,.8); }
  h1, h2, h3, h4 { color:#fff; }

  /* 카드(전체) */
  .ui-card{
    background: rgba(255,255,255,.08);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-radius:16px; padding:16px;
    box-shadow:0 4px 18px rgba(0,0,0,.25), inset 0 0 0 1px rgba(255,255,255,.05);
    transition: background .25s ease;
  }
  .ui-card:hover{ background: rgba(255,255,255,.12); }

  /* 카드 상단 헤더 박스(아이콘 들어갈 영역) */
  .ui-card .head{
    height:140px; border-radius:12px;
    background: rgba(255,255,255,.06);
    box-shadow: 0 10px 20px rgba(0,0,0,.25) inset;
    position: relative; overflow:hidden; margin-bottom:10px;
  }
  .ui-card .head img{
    width:48px; height:48px;
    position:absolute; left:12px; bottom:12px;
  }

  /* 텍스트 */
  .ui-card .title{ margin:6px 0 6px; font-weight:800; font-size:1.1rem; }
  .ui-card .desc{ margin:0 0 12px; color:rgba(255,255,255,.75); }

  /* 버튼 */
  div.stButton > button{
    width:100% !important; padding:12px 16px !important; border-radius:12px !important;
    font-weight:800 !important; font-size:1.05rem !important; border:none !important;
    color:#1E293B !important;
    background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
    box-shadow:0 10px 15px -3px rgba(59,130,246,.5),0 4px 6px -2px rgba(59,130,246,.05) !important;
    transition: transform .15s ease;
    margin-top:6px; /* 카드와 버튼 간격 */
  }
  div.stButton > button:hover { transform: translateY(-1px); }
  div.stButton > button:active { transform: scale(.98); }
</style>
""", unsafe_allow_html=True)

# ------------------------ 카드 데이터 ------------------------
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

# ------------------------ 렌더 ------------------------
st.title("Shopee Support Tools")
st.divider()

cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        # 1) 카드 본문(아이콘/타이틀/설명)을 하나의 HTML로 렌더 → 아이콘이 카드 안에 고정
        b64 = icon_b64(c["icon"]) if Path(c["icon"]).exists() else ""
        st.markdown(
            f"""
            <div class="ui-card">
              <div class="head">
                {'<img src="data:image/png;base64,'+b64+'" alt="icon"/>' if b64 else ''}
              </div>
              <div class="title">{c["title"]}</div>
              <div class="desc">{c["desc"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 2) 버튼 (Streamlit 위젯 → 카드 아래에 밀착 표시)
        if hasattr(st, "switch_page"):
            if st.button("시작하기", use_container_width=True, key=c["key"]):
                st.switch_page(c["path"])
        else:
            st.page_link(c["path"], label="시작하기")  # 구버전 호환

st.divider()
st.caption("Version: v3")
