# -*- coding: utf-8 -*-
"""
utils_common.py (Streamlit Secrets + Service Account 우선, OAuth 파일 fallback 지원)

- 환경/Secrets 로딩 (Secrets 우선)
- gspread 인증 (서비스계정 권장, 로컬 OAuth 폴백)
- 문자열/헤더 정규화 유틸
- Google Sheets 접근 유틸 (429 완화: 지수 백오프 + 워크시트 캐시)
- [NEW] 신규 생성(item_creator) 지원 유틸:
    - open_creation_by_env()
    - ensure_worksheet()
    - join_url(), choose_cover_key()
    - forward_fill_by_group()
"""

from __future__ import annotations

import os
import re
import time
import random
from pathlib import Path
from typing import Optional, List, Dict, Callable, Iterable, Sequence

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

def get_bool_env(name: str, default: bool = False) -> bool:
    v = _get_from_secrets(name).lower()
    if not v:
        v = os.getenv(name, "").strip().lower()
    if v in ["1", "true", "yes", "y"]:
        return True
    if v in ["0", "false", "no", "n"]:
        return False
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
# 워크시트 캐시 (동일 시트/탭 반복 접근 시 Read 요청 절약)
_WS_CACHE: dict[tuple[str, str], gspread.Worksheet] = {}

def _ws_cache_key(sh, name: str):
    sid = getattr(sh, "id", None) or getattr(sh, "spreadsheet_id", None) or ""
    return (sid, name)

def with_retry(
    fn: Callable,
    retries: int = 6,
    delay: float = 0.8,
    backoff: float = 1.8,
    jitter: float = 0.3,
):
    """
    gspread 호출용 재시도. 429면 지수 백오프(+지터)로 재시도.
    """
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is None and "429" in str(e):
                status = 429
            sleep_s = delay * (backoff ** i) + random.uniform(0, jitter)
            time.sleep(sleep_s if status == 429 else delay)
    if last_err:
        raise last_err

def safe_worksheet(sh, name: str):
    if not sh:
        raise ValueError(f"Spreadsheet object is not valid. Cannot get worksheet '{name}'.")
    key = _ws_cache_key(sh, name)
    if key in _WS_CACHE:
        return _WS_CACHE[key]
    ws = with_retry(lambda: sh.worksheet(name))
    _WS_CACHE[key] = ws
    return ws

def ensure_worksheet(sh, name: str, rows: int = 1000, cols: int = 26) -> gspread.Worksheet:
    """
    탭이 없으면 생성 후 반환. 있으면 캐시 포함 안전 반환.
    """
    try:
        return safe_worksheet(sh, name)
    except WorksheetNotFound:
        ws = with_retry(lambda: sh.add_worksheet(title=name, rows=rows, cols=cols))
        _WS_CACHE[_ws_cache_key(sh, name)] = ws
        return ws

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

def hex_to_rgb01(hex_str: str) -> Dict[str, float]:
    """#RRGGBB → {red,green,blue} (0~1 float)"""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return {"red": 1, "green": 1, "blue": 0.7}
    r, g, b = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
    return {"red": r / 255.0, "green": g / 255.0, "blue": b / 255.0}

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
            tail = tail.split(sep, 1)[0]
            break
    tail = tail.strip()
    return tail.lower() if tail else None

def get_tem_sheet_name() -> str:
    return get_env("TEM_OUTPUT_SHEET_NAME", "TEM_OUTPUT")

# ---- URL/키 헬퍼 (신규 생성 공용) ------------------------------------------
def join_url(base: str, *parts: str) -> str:
    """
    슬래시 중복/누락을 처리하며 안전하게 URL을 결합.
    join_url("https://x.com/", "A", "B") -> "https://x.com/A/B"
    """
    b = (base or "").strip()
    if not b:
        return ""
    b = b.rstrip("/")
    segs = [str(p).strip().strip("/") for p in parts if str(p or "").strip()]
    return b + ("/" + "/".join(segs) if segs else "")

def choose_cover_key(variation_integration_no: str | None, sku: str | None) -> str | None:
    """신규 생성 규칙: Variation Integration No.가 있으면 그 값을, 없으면 SKU를 사용."""
    v = (variation_integration_no or "").strip()
    if v:
        return v
    s = (sku or "").strip()
    return s if s else None

# ---- 간단 포워드필 유틸 -----------------------------------------------------
def forward_fill_by_group(
    rows: List[List[str]],
    group_idx: int,
    fill_col_indices: Sequence[int],
    reset_when: Callable[[List[str]], bool] = lambda r: False,
) -> List[List[str]]:
    """
    동일 그룹(예: Variation)이 이어지는 구간에서만 지정 컬럼을 forward-fill.
    - rows: 헤더 포함 2차원 배열(get_all_values 결과)
    - group_idx: 그룹 키 컬럼 인덱스(0-based). 예: Variation이 B열이면 1
    - fill_col_indices: 채워야 할 컬럼 인덱스 목록(0-based)
    - reset_when: True면 누적값 리셋(예: 빈 행, Create=False 등 조건)
    반환: 새로운 2차원 배열(원본을 얕게 복사 후 채움)
    """
    if not rows:
        return rows
    out = [list(r) for r in rows]
    current_key = None
    last_vals: Dict[int, str] = {}
    # 헤더는 그대로
    for i in range(1, len(out)):
        r = out[i]
        if reset_when(r):
            current_key = None
            last_vals = {}
            continue
        gval = (r[group_idx] if group_idx < len(r) else "").strip()
        if gval:
            # 새 그룹 시작
            current_key = gval
            last_vals = {idx: (r[idx] if idx < len(r) else "") for idx in fill_col_indices}
        else:
            # 그룹 키가 비었지만 같은 그룹의 연속행으로 간주 → 전개
            if current_key is not None:
                for idx in fill_col_indices:
                    if idx < len(r) and not (r[idx] or "").strip():
                        r[idx] = last_vals.get(idx, "")
        # 전개 이후 비어 있지 않은 값은 캐시 갱신
        for idx in fill_col_indices:
            if idx < len(r) and (r[idx] or "").strip():
                last_vals[idx] = r[idx]
    return out

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
            authorized_user_filename=str(token_path),
        )
    return None

def _get_ss_id_from_secrets_or_env(*keys: str) -> str:
    """
    Secrets → ENV 순서로 여러 키 이름(alias)을 검색하여 첫 값을 반환.
    예) _get_ss_id_from_secrets_or_env("REFERENCE_SPREADSHEET_ID", "REFERENCE_SHEET_KEY")
    """
    for k in keys:  # Secrets 우선
        val = _get_from_secrets(k)
        if val:
            return val
    for k in keys:  # 없으면 ENV
        val = os.getenv(k, "").strip()
        if val:
            return val
    return ""

def _authorize_and_open_by_key(ss_id: str):
    gc = _authorize_gspread_via_service_account() or _authorize_gspread_via_local_oauth()
    if gc is None:
        raise RuntimeError(
            "No valid Google credentials. Set Streamlit secrets or place client_secret.json for local OAuth."
        )
    return gc.open_by_key(ss_id)

def open_sheet_by_env():
    """
    본 작업 대상 Sheet 열기.
    허용 키: GOOGLE_SHEETS_SPREADSHEET_ID (권장), GOOGLE_SHEET_KEY (별칭)
    """
    load_env()
    ss_id = _get_ss_id_from_secrets_or_env("GOOGLE_SHEETS_SPREADSHEET_ID", "GOOGLE_SHEET_KEY")
    if not ss_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID (or GOOGLE_SHEET_KEY) not set in secrets/env.")
    return _authorize_and_open_by_key(ss_id)

def open_ref_by_env():
    """
    Reference Sheet 열기 (선택적)
    허용 키: REFERENCE_SPREADSHEET_ID (권장), REFERENCE_SHEET_KEY (별칭)
    """
    load_env()
    ref_id = _get_ss_id_from_secrets_or_env("REFERENCE_SPREADSHEET_ID", "REFERENCE_SHEET_KEY")
    if not ref_id:
        return None
    return _authorize_and_open_by_key(ref_id)

# [NEW] 신규 생성(item_creator) 전용 시트 열기
def open_creation_by_env():
    """
    '상품등록' 개인 시트를 엽니다.
    허용 키: CREATION_SPREADSHEET_ID (권장), CREATION_SHEET_KEY (별칭)
    - pages/3_Create ... 에서 URL을 입력받아 extract_sheet_id()로 ID를 추출 후
      save_env_value("CREATION_SPREADSHEET_ID", id) 형태로 저장하는 것을 권장.
    """
    load_env()
    ss_id = _get_ss_id_from_secrets_or_env("CREATION_SPREADSHEET_ID", "CREATION_SHEET_KEY")
    if not ss_id:
        raise RuntimeError("CREATION_SPREADSHEET_ID (or CREATION_SHEET_KEY) not set in secrets/env.")
    return _authorize_and_open_by_key(ss_id)

# ==== [APPEND AT BOTTOM OF FILE] ============================================
# 필요한 경우에만 인증 클라이언트를 돌려주는 범용 함수 + 시트ID 파서
# 기존 코드와 충돌하지 않도록 함수 내부에 필요한 모듈을 import 합니다.

def authorize_gspread():
    """인증된 gspread.Client 인스턴스를 반환합니다.
    우선순위: st.secrets['gcp_service_account'] → GOOGLE_APPLICATION_CREDENTIALS → service_account.json
    """
    # 1) Streamlit secrets (권장)
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            from google.oauth2.service_account import Credentials
            import gspread
            creds_info = dict(st.secrets["gcp_service_account"])
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass

    # 2) GOOGLE_APPLICATION_CREDENTIALS (서비스 계정 키 파일 경로)
    try:
        import os
        from google.oauth2.service_account import Credentials
        import gspread
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if cred_path and os.path.exists(cred_path):
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass

    # 3) 로컬 service_account.json (개발 용)
    try:
        import gspread
        return gspread.service_account()
    except Exception as e:
        raise RuntimeError(
            "Google 인증 실패: st.secrets['gcp_service_account'] / "
            "GOOGLE_APPLICATION_CREDENTIALS / service_account.json 을 확인하세요."
        ) from e


def extract_sheet_id(url_or_id: str) -> str:
    """Google Sheets URL 또는 순수 ID를 모두 허용. URL이면 d/<ID> 패턴에서 ID 추출."""
    if not url_or_id:
        raise ValueError("빈 시트 URL/ID 입니다.")
    try:
        import re
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id)
        return m.group(1) if m else url_or_id.strip()
    except Exception:
        return url_or_id.strip()
# ==== [END APPEND] ===========================================================

