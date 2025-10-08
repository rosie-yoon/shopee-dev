# pages/1_Cover Image.py
import streamlit as st
from pathlib import Path
import sys

# (중요) 프로젝트 루트(shopee_v1) 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# 공통 테마
from ui_theme import apply_theme

# 하위 앱 임포트 (폴더명 유지)
from image_compose.app import run as image_compose_run

# 페이지 설정 (항상 첫 호출)
st.set_page_config(page_title="Cover Image", layout="wide", initial_sidebar_state="expanded")


# 실제 페이지 실행
image_compose_run()
