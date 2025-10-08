# ui_theme.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import base64
import streamlit as st

# 아이콘 파일 위치 (PNG)
ICON_DIR = Path("assets/icons")

def _find_icon_path(name: str) -> Path | None:
    """name.png -> name@3x.png 우선순위로 탐색"""
    cands = [ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"]
    for p in cands:
        if p.exists():
            return p
    return None

def _icon_b64(name: str) -> str | None:
    p = _find_icon_path(name)
    if not p:
        return None
    return base64.b64encode(p.read_bytes()).decode()

def title_with_icon(title: str, icon_name: str, size: int = 28) -> None:
    """타이틀 왼쪽에 PNG 아이콘을 인라인으로 붙여 렌더링"""
    b64 = _icon_b64(icon_name)
    if b64:
        st.markdown(
            f"""
            <h1 style="display:flex; align-items:center; gap:10px; margin:0 0 1rem 0;">
              <img src="data:image/png;base64,{b64}" alt="{icon_name}" width="{size}" height="{size}" style="display:inline-block; vertical-align:middle;"/>
              <span>{title}</span>
            </h1>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.title(title)

def apply_theme(
    *,
    hide_sidebar: bool = False,
) -> None:
    """
    • 다크 모노톤 배경 + 글래스 스타일
    • 사이드바 톤(배경/블러/활성/기본 링크)
    • 폼 컨트롤(입력, 셀렉트, 플레이스홀더) 톤
    • 업로더(Drag&Drop) 톤
    • 버튼/다운로드 버튼 톤(활성/호버/비활성)
    """
    css_sidebar_hide = "section[data-testid='stSidebar']{display:none !important;}" if hide_sidebar else ""

    st.markdown(
        f"""
<style>
/* ---------- App 배경/기본 폰트 ---------- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"] {{
  background: linear-gradient(135deg,#1E293B 0%, #334155 100%);
  color:#fff;
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, 'Noto Sans';
}}
[data-testid="stHeader"] {{
  background: rgba(30,41,59,.8);
}}
h1,h2,h3,h4 {{ color:#fff; }}

/* ---------- 사이드바(공통) ---------- */
section[data-testid="stSidebar"] {{
  background: rgba(0,0,0,.2) !important;
  backdrop-filter: blur(8px) !important;
  -webkit-backdrop-filter: blur(8px) !important;
}}
section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] span {{
  color:#D1D5DB !important; /* 기본 링크 텍스트 */
}}
section[data-testid="stSidebar"] [aria-current="page"] {{
  background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
  color:#1E293B !important;
  border-radius:10px !important;
  font-weight:800 !important;
}}
section[data-testid="stSidebar"] [aria-current="page"] * {{
  color:#1E293B !important; /* 활성 텍스트 */
}}

/* (옵션) 홈에서 사이드바 완전 숨김 */
{css_sidebar_hide}
[data-testid="stAppViewContainer"] {{
  margin-left: 0 !important;  /* 사이드바 숨겼을 때 컨텐츠 여백 보정 */
}}

/* ---------- 카드 공용(홈/폼 컨테이너에서 재사용 가능) ---------- */
.glass-card {{
  background: rgba(255,255,255,.08);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 4px 18px rgba(0,0,0,.25), inset 0 0 0 1px rgba(255,255,255,.05);
  transition: background .25s ease, transform .15s ease;
}}
.glass-card:hover {{
  background: rgba(255,255,255,.12);
  transform: translateY(-1px);
}}

/* ---------- 폼 컨트롤(입력/텍스트에어리어/플레이스홀더) ---------- */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea {{
  background: rgba(255,255,255,.10) !important;
  border: 1px solid rgba(255,255,255,.15) !important;
  color:#fff !important;
  border-radius: 8px !important;
  transition: all .2s ease;
}}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {{
  border-color:#93C5FD !important;
  box-shadow: 0 0 0 2px rgba(147,197,253,.30) !important;
}}
input::placeholder, textarea::placeholder {{
  color: rgba(255,255,255,.60) !important;
}}
/* Selectbox & baseweb Select(멀티 포함) 보더/배경 */
div[data-testid="stSelectbox"] > div,
div[data-baseweb="select"] > div {{
  background: rgba(255,255,255,.10) !important;
  border: 1px solid rgba(255,255,255,.15) !important;
  color:#fff !important;
  border-radius: 8px !important;
}}
/* select 내부 텍스트 대비 */
div[data-baseweb="select"] * {{ color: rgba(255,255,255,.95) !important; }}

/* ---------- 업로더(Drag & Drop) ---------- */
div[data-testid="stFileUploaderDropzone"] {{
  background: rgba(255,255,255,.08) !important;
  border: 1px solid rgba(255,255,255,.15) !important;
  border-radius: 12px !important;
  color: rgba(255,255,255,.92) !important;
}}
div[data-testid="stFileUploaderDropzone"] * {{
  color: rgba(255,255,255,.92) !important;   /* 내부 텍스트/아이콘 가독성 ↑ */
}}
/* 업로더 내부 placeholder/헬프 */
[data-testid="stCaption"], .stAlert, .streamlit-expanderHeader {{
  color: rgba(255,255,255,.70) !important;
}}

/* ---------- 버튼(공통) : stButton / stDownloadButton ---------- */
div.stButton > button,
div.stDownloadButton > button {{
  width: 100% !important;
  font-weight: 800 !important;
  font-size: 1.05rem !important;
  padding: 12px 16px !important;
  border: none !important;
  border-radius: 12px !important;
  color: #1E293B !important;  /* 요구사항: 버튼 텍스트는 진한 남색 */
  background: linear-gradient(90deg,#93C5FD,#67E8F9) !important;
  box-shadow: 0 10px 15px -3px rgba(59,130,246,.5),
              0 4px 6px -2px rgba(59,130,246,.05) !important;
  transition: transform .15s ease, box-shadow .2s ease;
}}
div.stButton > button:hover,
div.stDownloadButton > button:hover {{
  transform: translateY(-1px);
  box-shadow: 0 10px 15px -3px rgba(59,130,246,.7),
              0 4px 6px -2px rgba(59,130,246,.05) !important;
}}
div.stButton > button:active,
div.stDownloadButton > button:active {{
  transform: scale(.98);
}}
div.stButton > button:disabled,
div.stDownloadButton > button:disabled {{
  background: #4B5563 !important; /* Gray-600 */
  color: #D1D5DB !important;       /* Gray-300 */
  box-shadow: none !important;
}}
</style>
        """,
        unsafe_allow_html=True,
    )
