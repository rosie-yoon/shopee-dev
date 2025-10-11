# shopee_creator/controller.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import traceback
import json
import gspread
from google.oauth2.service_account import Credentials

from . import creation_steps as steps  # C1~C6 & export helpers


@dataclass
class StepLog:
    name: str
    ok: bool
    count: int | None = None
    error: str | None = None


class ShopeeCreator:
    """
    - secrets로부터 서비스계정 JSON/REFERENCE_SPREADSHEET_ID를 읽어 gspread 클라이언트(`self.gs`)를 준비
    - run(input_sheet_url=...) 호출 시 C1~C6 순차 실행
    - 페이지에서 export가 필요하면, self.gs로 스프레드시트를 열어 넘겨주면 됩니다.
    """
    def __init__(self, secrets):
        self.secrets = secrets or {}
        self.gs = self._build_gspread_client()
        self.ref_url = self._get_reference_url()

        # 이미지 base URL (있으면 보관; C5 단계에서 필요 시 전달)
        self.cover_base_url: Optional[str] = None
        self.details_base_url: Optional[str] = None
        self.option_base_url: Optional[str] = None
        self.shop_code: Optional[str] = None

    # --- public helpers -------------------------------------------------
    def set_image_bases(self, *, cover: str, details: str, option: str, shop_code: str):
        self.cover_base_url = cover
        self.details_base_url = details
        self.option_base_url = option
        self.shop_code = shop_code

    # --- core -----------------------------------------------------------
    def run(self, *, input_sheet_url: str) -> List[StepLog]:
        logs: List[StepLog] = []

        # 열기
        sh = self.gs.open_by_url(input_sheet_url)
        ref = self._open_ref_sheet()

        pipeline = [
            ("C1 Prepare TEM_OUTPUT", lambda: steps.run_step_C1(sh, ref)),
            ("C2 Collection → TEM",  lambda: steps.run_step_C2(sh, ref)),
            ("C3 FDA Fill",          lambda: steps.run_step_C3_fda(sh, ref)),
            ("C4 Prices",            lambda: steps.run_step_C4_prices(sh)),
            ("C5 Images",            self._run_c5_images),
            ("C6 Stock/Weight/Brand",lambda: steps.run_step_C6_stock_weight_brand(sh)),
        ]

        for name, fn in pipeline:
            try:
                fn()
                logs.append(StepLog(name=name, ok=True))
            except Exception as e:
                logs.append(StepLog(name=name, ok=False, error=f"{e}\n{traceback.format_exc()}"))
                break  # 실패 시 중단 (원하면 계속 진행으로 바꿀 수 있음)

        return logs

    # --- internals ------------------------------------------------------
    def _run_c5_images(self):
        # C5는 우리가 클린본에서 아직 미구현(pass) 상태입니다.
        # 이미지 베이스가 세팅되어 있다면 여기서 전달하도록 뼈대만 둡니다.
        sh = None  # 필요 시 self.gs.open_by_url(...) 으로 가져오도록 확장 가능
        if all([self.cover_base_url, self.details_base_url, self.option_base_url, self.shop_code]):
            # 구현 완료 시 아래처럼 연결:
            # steps.run_step_C5_images(
            #     sh,
            #     shop_code=self.shop_code,
            #     cover_base_url=self.cover_base_url,
            #     details_base_url=self.details_base_url,
            #     option_base_url=self.option_base_url,
            # )
            return
        # 아직 넘길 값이 없으면 스킵
        return

    def _open_ref_sheet(self):
        url = self.ref_url
        if not url:
            raise RuntimeError("REFERENCE_SPREADSHEET_ID (or REF_URL) is not set in secrets.")
        if url.startswith("http"):
            return self.gs.open_by_url(url)
        # id만 있으면 key로 오픈
        return self.gs.open_by_key(url)

    def _get_reference_url(self) -> str | None:
        s = self.secrets
        sid = s.get("REFERENCE_SPREADSHEET_ID")
        if sid:
            sid = str(sid).strip()
            # URL 그대로 넣어도 허용
            if sid.startswith("http"):
                return sid
            return sid  # id는 open_by_key에서 사용
        # 폴백 키들
        for v in (
            s.get("REF_SHEET_URL"),
            s.get("REF_URL"),
            s.get("ref_url"),
            (s.get("refs") or {}).get("sheet_url") if isinstance(s.get("refs"), dict) else None,
        ):
            if v:
                return str(v)
        return None

    def _build_gspread_client(self):
        # secrets에 JSON 문자열 혹은 dict 로 저장된 서비스 계정 키 기대
        s = self.secrets or {}
        creds_json = s.get("GOOGLE_SERVICE_ACCOUNT_JSON") or s.get("google_service_account_json")
        if not creds_json:
            # Streamlit Cloud 에서는 st.secrets에 dict 형태로 들어올 수 있음
            # 없으면 환경변수/기본 인증 등으로 확장 가능
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing in secrets.")

        if isinstance(creds_json, str):
            try:
                info = json.loads(creds_json)
            except Exception:
                raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not a valid JSON string.")
        else:
            info = creds_json  # already dict

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
