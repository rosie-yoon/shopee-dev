# shopee_creator/controller.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import traceback
import json
import gspread
from google.oauth2.service_account import Credentials

from .utils_creator import with_retry, extract_sheet_id
from . import creation_steps as steps  # C1~C6 & export helpers


# ---- module-level helper -----------------------------------------------------
def _raise_missing(what: str):
    # Streamlit에서 보기 좋은 메시지로 즉시 중단
    raise RuntimeError(f"[C5] {what}이(가) 설정되지 않았습니다. 페이지에서 set_image_base()를 먼저 호출하세요.")


@dataclass
class StepLog:
    name: str
    ok: bool
    count: int | None = None
    error: str | None = None


class ShopeeCreator:
    def __init__(self, secrets):
        self.secrets = secrets

        # gspread 클라이언트/레퍼런스 URL 준비
        self.gs = self._build_gspread_client()
        self.ref_url: Optional[str] = self._get_reference_url()
        self._current_sh = None

        # ✅ C5에서 사용하는 입력값(요구사항: 입력 그대로 사용, 보정 없음)
        self._image_base_url: Optional[str] = None
        self.shop_code: Optional[str] = None

        # (구버전 호환용) 멀티 베이스 보관 필드 — 현재는 미사용
        self.cover_base_url = None
        self.details_base_url = None
        self.option_base_url = None

    # ---- C5용 입력 세팅 -------------------------------------------------------
    def set_image_base(self, base_url: str, shop_code: str) -> None:
        """Base URL/Shop Code를 입력 그대로 보관 (대소문자/슬래시 보정 절대 금지)."""
        self._image_base_url = base_url
        self.shop_code = shop_code

    # (구버전 호환) 여러 베이스를 받던 세터
    def set_image_bases(self, *, cover: str, details: str, option: str, shop_code: str):
        self.cover_base_url = cover
        self.details_base_url = details
        self.option_base_url = option
        self.shop_code = shop_code

    # ---- 실행 파이프라인 ------------------------------------------------------
    def run(self, *, input_sheet_url: str) -> List[StepLog]:
        logs: List[StepLog] = []

        # 입력 시트 오픈
        sh = with_retry(lambda: self.gs.open_by_url(input_sheet_url))
        self._current_sh = sh

        # 레퍼런스 시트 오픈
        ref = self._open_ref_sheet()

        # 디버그 (원하면 주석처리)
        print("[DEBUG] sh.title =", getattr(sh, "title", None), "| sh.id =", getattr(sh, "id", None))
        print("[DEBUG] ref.title =", getattr(ref, "title", None), "| ref.id =", getattr(ref, "id", None))
        print("[DEBUG] same_book? ", getattr(sh, "id", None) == getattr(ref, "id", None))

        pipeline = [
            ("C1 Prepare TEM_OUTPUT", lambda: steps.run_step_C1(sh, ref)),
            ("C2 Collection → TEM",  lambda: steps.run_step_C2(sh, ref)),
            ("C3 FDA Fill",          lambda: steps.run_step_C3_fda(sh, ref)),
            ("C4 Prices",            lambda: steps.run_step_C4_prices(sh)),
            # ✅ C5: creation_steps.run_step_C5_images 사용 (입력 그대로 전달)
            ("C5 Images",            lambda: steps.run_step_C5_images(
                sh=sh,
                base_url=(self._image_base_url if self._image_base_url is not None else _raise_missing("Image Base URL")),
                shop_code=(self.shop_code      if self.shop_code      is not None else _raise_missing("Shop Code")),
            )),
            ("C6 Stock/Weight/Brand",lambda: steps.run_step_C6_stock_weight_brand(sh)),
        ]

        for name, fn in pipeline:
            try:
                fn()
                logs.append(StepLog(name=name, ok=True))
            except Exception as e:
                logs.append(StepLog(name=name, ok=False, error=f"{e}\n{traceback.format_exc()}"))
                break  # 실패 시 파이프라인 중단 (원하면 계속 진행으로 변경 가능)

        return logs

    # ---- internals ------------------------------------------------------------
    def _open_ref_sheet(self):
        url = self.ref_url
        if not url:
            # secrets에 ID/URL 어느 형태든 하나는 있어야 함
            raise RuntimeError("REFERENCE_SPREADSHEET_ID (or REF_URL) is not set in secrets.")

        # URL 또는 ID 처리
        sheet_id = extract_sheet_id(url)
        # URL이면 open_by_url, ID만이면 open_by_key
        if url.startswith("http"):
            return with_retry(lambda: self.gs.open_by_url(url))
        return with_retry(lambda: self.gs.open_by_key(sheet_id))

    def _get_reference_url(self) -> Optional[str]:
        s = self.secrets or {}
        sid = s.get("REFERENCE_SPREADSHEET_ID")
        if sid:
            sid = str(sid).strip()
            if sid:
                # URL 그대로 넣어도 허용
                return sid

        # 폴백 키들
        for v in (
            s.get("REF_SHEET_URL"),
            s.get("REF_URL"),
            s.get("ref_url"),
            (s.get("refs") or {}).get("sheet_url") if isinstance(s.get("refs"), dict) else None,
        ):
            if v:
                return str(v).strip()
        return None

    def _build_gspread_client(self):
        s = self.secrets or {}
        creds_json = s.get("GOOGLE_SERVICE_ACCOUNT_JSON") or s.get("google_service_account_json")
        if not creds_json:
            # Streamlit Cloud에서는 st.secrets에 dict로 들어올 수 있음
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing in secrets.")

        if isinstance(creds_json, str):
            try:
                info = json.loads(creds_json)
            except Exception:
                raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not a valid JSON string.")
        else:
            info = creds_json  # already dict

        client_email = info.get("client_email", "N/A")
        print(f"[AUTH_CHECK] Authenticating as service account: {client_email}")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    # (과거 미구현 메서드 - 현재 파이프라인에서 직접 호출하므로 사용 안 함)
    def _run_c5_images(self):
        return
