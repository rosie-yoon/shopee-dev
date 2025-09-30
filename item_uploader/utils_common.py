# -*- coding: utf-8 -*-
"""
utils_common.py (Streamlit Secrets + Service Account 우선, OAuth 파일 fallback 지원)

- 환경/Secrets 로딩
- gspread 인증 (서비스계정 권장)
- 문자열/헤더 정규화
- Google Sheets 접근 유틸
"""

from __future__ import annotations
import os
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Callable

import gspread
from gspread.exceptions import WorksheetNotFound
from dotenv import load_dotenv

# Streamlit/Google Auth (서비스계정)
try:
    import streamlit as st
    from google.oauth2.service_account import Credentials
except Exception:
    st = None
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

def _get_from_secrets(name: str) -> str:
    if st is not None and hasattr(st, "secrets"):
        try:
            val = st.secrets.get(name, "")
            return (str(val) if val is not None else "").strip()
        except Exception:
            return ""
    return ""

def get_env(name: str, default: str = "") -> str:
    """Cloud에선 Secrets 우선 → 없으면 OS/.env"""
    val = _get_from_secrets(name)
    if val:
        return val
    return os.getenv(name, default).strip()

def get_bool_env(name: str, default: bool=False) -> bool:
    v = _get_from_secrets(name).lower()
    if not v:
        v = os.getenv(name, "").strip().lower()
    if v in ["1","true","yes","y"]: return True
    if v in ["0","false","no","n"]: return False
    return default

def _env_path() -> str:
    here = Path(__file__).resolve().parent
    p1 = here / ".env"
    return str(p1 if p1.exists() else Path.cwd() / ".env")

def save_env_value(key: str, value: str):
    """단순 .env 업데이트: 키 있으면 교체, 없으면 추가 (로컬에서만 사용)"""
    path = _env_path()
    kv: Dict[str, str] = {}
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.strip().startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()
    kv[key] = value
    lines = [f"{k}={v}" for k, v in kv.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# =============================
# 공통 유틸
# =============================
def with_retry(fn: Callable, retries: int=3, delay: float=2.0):
    """API 요청 재시도 래퍼"""
    last_err = None
    for _ in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            time.sleep(delay)
    if last_err:
        raise last_err

def safe_worksheet(sh, name: str):
    if not sh:
        raise ValueError(f"Spreadsheet object is not valid. Cannot get worksheet '{name}'.")
    try:
        return with_retry(lambda: sh.worksheet(name))
    except WorksheetNotFound:
        raise

# 문자열/헤더 정규화
def norm(s: str) -> str:
    return (
        str(s or "")
        .strip()
        .lower()
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
    )

def header_key(s: str) -> str:
    """헤더 비교용: 영숫자+하이픈만 남김"""
    return re.sub(r"[^a-z0-9\-]+", "", norm(s))

def hex_to_rgb01(hex_str: str) -> Dict[str,float]:
    """#RRGGBB → {red,green,blue} (0~1 float)"""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return {"red":1,"green":1,"blue":0.7}
    r,g,b = tuple(int(hex_str[i:i+2],16) for i in (0,2,4))
    return {"red":r/255.0,"green":g/255.0,"blue":b/255.0}

def extract_sheet_id(s: str) -> str | None:
    s = (s or "").strip()
    if re.fullmatch(r"[A-Za-z0-9\-_]{25,}", s):
        return s
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9\-_]+)", s)
    if m:
        return m.group(1)
    return None

def sheet_link(sid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"

def strip_category_id(cat: str) -> str:
    """'101814 - Home & Living/...' -> 'Home & Living/...'"""
    s = str(cat or "")
    m = re.match(r"^\s*\d+\s*-\s*(.+)$", s)
    return m.group(1) if m else s

def top_of_category(cat: str) -> Optional[str]:
    """TopLevel 추출"""
    if not cat:
        return None
    tail = strip_category_id(cat)
    for sep in ["/", ">", "|", "\\"]:
        if sep in tail:
            tail = tail.split(sep,1)[0]
            break
    tail = tail.strip()
    return tail.lower() if tail else None

def get_tem_sheet_name() -> str:
    return get_env("TEM_OUTPUT_SHEET_NAME", "TEM_OUTPUT")


# =============================
# Google Sheets 인증/열기
# =============================
def _authorize_gspread_via_service_account():
    """Streamlit Secrets의 서비스계정으로 인증 (권장 경로)."""
    if st is None or Credentials is None:
        return None  # Streamlit/Google libs 미존재 → fallback 시도
    if not hasattr(st, "secrets"):
        return None
    if "gcp_service_account" not in st.secrets:
        return None

    sa_info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)

def _authorize_gspread_via_local_oauth():
    """로컬 개발용 fallback: client_secret.json / token.json 이용"""
    base = Path(__file__).resolve().parent
    cred_path = base / "client_secret.json"
    token_path = base / "token.json"
    if cred_path.exists():
        return gspread.oauth(
            credentials_filename=str(cred_path),
            authorized_user_filename=str(token_path)
        )
    return None

def _get_ss_id_from_secrets_or_env(*keys: str) -> str:
    """
    Secrets → ENV 순서로 여러 키 이름(alias)을 검색하여 첫 값을 반환.
    예) _get_ss_id_from_secrets_or_env("REFERENCE_SPREADSHEET_ID","REFERENCE_SHEET_KEY")
    """
    # Secrets 우선
    for k in keys:
        val = _get_from_secrets(k)
        if val:
            return val
    # 없으면 ENV
    for k in keys:
        val = os.getenv(k, "").strip()
        if val:
            return val
    return ""

def open_sheet_by_env():
    """
    본 작업 대상 Sheet 열기.
    허용 키: GOOGLE_SHEETS_SPREADSHEET_ID (권장), GOOGLE_SHEET_KEY (별칭)
    """
    load_env()
    ss_id = _get_ss_id_from_secrets_or_env("GOOGLE_SHEETS_SPREADSHEET_ID", "GOOGLE_SHEET_KEY")
    if not ss_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID (or GOOGLE_SHEET_KEY) not set in secrets/env.")

    gc = _authorize_gspread_via_service_account() or _authorize_gspread_via_local_oauth()
    if gc is None:
        raise RuntimeError("No valid Google credentials. Set Streamlit secrets or place client_secret.json for local OAuth.")
    return gc.open_by_key(ss_id)

def open_ref_by_env():
    """
    Reference Sheet 열기 (선택적)
    허용 키: REFERENCE_SPREADSHEET_ID (권장), REFERENCE_SHEET_KEY (별칭)
    """
    load_env()
    ref_id = _get_ss_id_from_secrets_or_env("REFERENCE_SPREADSHEET_ID", "REFERENCE_SHEET_KEY")
    if not ref_id:
        return None

    gc = _authorize_gspread_via_service_account() or _authorize_gspread_via_local_oauth()
    if gc is None:
        raise RuntimeError("No valid Google credentials for reference sheet.")
    return gc.open_by_key(ref_id)
