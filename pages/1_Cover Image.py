# pages/1_Cover Image.py
# -*- coding: utf-8 -*-
import streamlit as st
from pathlib import Path
import sys

# 프로젝트 루트(shopee_v1) 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# 페이지 메타
st.set_page_config(page_title="Cover Image", layout="wide")

# 모듈 실행
from image_compose.app import run as image_compose_run
image_compose_run()
