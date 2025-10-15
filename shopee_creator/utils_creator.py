# -*- coding: utf-8 -*-
"""
utils_common.py (MASTER VERSION - All required functions included)

- 환경/Secrets 로딩
- gspread 인증 (authorize_gspread)
- 문자열/헤더 정규화 유틸
- Google Sheets 접근 유틸 (with_retry, safe_worksheet)
- 신규 생성(item_creator) 지원 유틸 (get_env, forward_fill_by_group 등)
"""

from __future__ import annotations

import os
import re
import time
import random
from pathlib import Path
from typing import Optional, List, Dict, Callable, Iterable, Sequence, Any # Any 추가

import gspread
from gspread.exceptions import WorksheetNotFound
from dotenv import load_dotenv


# Streamlit / Google Auth (서비스계정)
try:
    import streamlit as st
    from google.oauth2.service_account import Credentials
except Exception:  # 로컬 스크립트 실행 등
    st = None  # type: ignore
    Credentials = None  # type: ignore

# =============================
# 환경 변수 & .env 로딩
# =============================
def load_env():
    """여러 위치에서 .env 탐색하여 로드 (로컬 개발용)"""
    base = Path(__file__).resolve().parent
    for p in [base / ".env", base.parent / ".env", Path.cwd() / ".env"]:
        if p.exists():
            load_dotenv(p, override=True)
            return
    load_dotenv(override=True)  # fallback

def get_env(name: str, default: str = "") -> str:
    """Streamlit secrets, OS ENV, .env 순서로 값을 찾음"""
    val = default

    # 1. Streamlit Secrets (최우선)
    if st is not None and hasattr(st, "secrets"):
        try:
            val = st.secrets.get(name, val)
        except Exception:
            pass

    # 2. OS Environment
    val = os.getenv(name, val)

    return str(val).strip()

def get_bool_env(name: str, default: bool = False) -> bool:
    """환경 변수/Secrets에서 T/F/1/0 등 bool 값을 파싱"""
    s = get_env(name, str(default))
    if not s:
        return default
    s_lower = s.lower()
    return s_lower in ("true", "t", "1", "y", "yes")

# =============================
# gspread 인증
# =============================

def _authorize_gspread_via_secrets():
    """Streamlit secrets를 사용하여 인증"""
    if st is None or not hasattr(st, "secrets"):
        return None
    
    try:
        if "gcp_service_account" in st.secrets:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass
    return None

def authorize_gspread() -> gspread.Client:
    """인증 방식 우선순위에 따라 gspread.Client를 반환"""
    # 1. Streamlit Secrets 인증 시도
    gc = _authorize_gspread_via_secrets()
    if gc is not None: 
        return gc
    
    # 2. GOOGLE_APPLICATION_CREDENTIALS 또는 service_account.json (개발 용)
    try:
        return gspread.service_account()
    except Exception as e:
        # 모든 시도가 실패하면 RuntimeError 발생
        raise RuntimeError(
            "Google 인증 실패: secrets['gcp_service_account'] / GOOGLE_APPLICATION_CREDENTIALS / service_account.json 을 확인하세요."
        ) from e


# =============================
# 문자열/헤더 유틸
# =============================
def header_key(s: str) -> str:
    """헤더 정규화: 소문자화, 공백/특수문자 제거"""
    return re.sub(r"[\W_]+", "", str(s or "").lower())

def top_of_category(s: str) -> str:
    """
    카테고리 문자열에서 최상위 카테고리만 추출합니다. 
    (예: '101643 - Beauty/Makeup/Lips/Lip Gloss' -> 'Beauty')
    """
    # 1. 문자열 전체에서 슬래시 주변 공백 제거
    normalized_s = re.sub(r'\s*/\s*', '/', str(s or "").strip())
    # 2. 첫 번째 슬래시까지만 자름
    parts = normalized_s.split("/", 1)
    
    if not parts or not parts[0].strip():
        return ""
    
    top_part = parts[0].strip()
    
    # 3. "101643 - Beauty" 패턴에서 숫자 코드와 하이픈 제거
    # \s*-\s* 대신 더 명확하게 \s+-\s+ 또는 \s*-\s*를 사용 (현재는 \s*-\s*가 적용되어 있음)
    match = re.match(r'^\s*\d+\s*-\s*(.*)', top_part)
    if match:
        return match.group(1).strip()
        
    return top_part # 숫자 코드가 없는 경우 그대로 반환

def get_tem_sheet_name() -> str:
    """TEM_OUTPUT 시트 이름"""
    return get_env("TEM_OUTPUT_SHEET_NAME", "TEM_OUTPUT")

def sheet_link(ss_id: str) -> str:
    """스프레드시트 ID로 링크 생성"""
    return f"https://docs.google.com/spreadsheets/d/{ss_id}/edit"


# =============================
# Sheets 접근 유틸
# =============================
def extract_sheet_id(url_or_id: str) -> str:
    """Google Sheets URL 또는 순수 ID를 모두 허용. URL이면 d/<ID> 패턴에서 ID 추출."""
    if not url_or_id:
        raise ValueError("빈 시트 URL/ID 입니다.")
    try:
        # URL에서 ID 추출 패턴: /d/<ID>/edit
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
        if m:
            return m.group(1)
        # 순수 ID로 간주
        return url_or_id
    except Exception as e:
        raise ValueError(f"올바른 Google Sheets URL 또는 ID 형식이 아닙니다: {e}") from e

def with_retry[T](func: Callable[[], T], max_tries=5, delay=1.0) -> Optional[T]:
    """gspread 요청에 대한 지수 백오프/재시도 래퍼"""
    for i in range(max_tries):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            # 429 Rate Limit이나 일시적 에러 시 재시도
            if i == max_tries - 1 or e.response.status_code not in (429, 500, 503):
                raise
            time.sleep(delay * (2 ** i) + random.random())
        except Exception:
            if i == max_tries - 1:
                raise
            time.sleep(delay * (2 ** i) + random.random())
    return None

def safe_worksheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    """시트가 존재하는지 확인하고 반환. 없으면 WorksheetNotFound 발생."""
    return with_retry(lambda: sh.worksheet(title))


# =============================
# 신규 생성(item_creator) 지원 유틸
# =============================

def _is_true(v: Any) -> bool: # v의 타입을 Any로 변경
    """
    gspread에서 읽어온 값이 True인지 확인 (불리언, 문자열 'TRUE', 't', '1', '✔' 등 포함)
    """
    if isinstance(v, bool):
        return v
    
    s = str(v or "").strip().lower()
    return s in ("true", "t", "1", "y", "yes", "✔", "✅")


def forward_fill_by_group(
    data: Sequence[List[str]],
    group_idx: int,
    fill_col_indices: List[int],
    reset_when: Callable[[List[str]], bool],
    header_rows: int = 1,
) -> List[List[str]]:
    """
    특정 그룹 컬럼(group_idx)의 값이 같거나 비어있을 경우,
    지정된 컬럼(fill_col_indices)의 유효한 값을 하위 행에 채워넣음 (Forward Fill).
    reset_when: 이 함수가 True를 반환하면 그룹이 단절된 것으로 간주하고 필링 중단.
    """
    output = [list(row) for row in data]
    
    # 헤더는 필링하지 않음
    for r in range(header_rows, len(output)):
        row = output[r]
        
        # 1. 그룹 단절 체크
        if reset_when(row):
            # 그룹이 단절되면 이전에 필링된 값들을 초기화
            for j in fill_col_indices:
                if j < len(row):
                    row[j] = ""
            continue
        
        # 2. 그룹 값이 바뀌지 않았거나 비어있는 경우 (이전 그룹과 동일)
        prev_row = output[r-1]
        
        # 이전 행의 그룹 값(group_idx)이 현재 행의 그룹 값과 같거나, 현재 행의 그룹 값이 비어있다면 필링 시도
        is_same_group = (
            (group_idx < len(row) and not (row[group_idx] or "").strip()) or # 현재 그룹 값 비어있음
            (group_idx < len(row) and group_idx < len(prev_row) and (row[group_idx] or "").strip() == (prev_row[group_idx] or "").strip())
        )

        # 3. 필링 실행 (fill_col_indices의 값이 비어있을 경우, 이전 행 값으로 채움)
        for j in fill_col_indices:
            if j < len(row) and j < len(prev_row):
                current_val = (row[j] or "").strip()
                prev_val = (prev_row[j] or "").strip()
                
                if not current_val and prev_val:
                    row[j] = prev_val
    
    return output

# end of MASTER UTILS
