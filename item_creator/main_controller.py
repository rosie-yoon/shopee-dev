# item_creator/main_controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable, Optional, Dict, Any, List
import traceback
import gspread

# utils: 이제 item_creator 쪽에서 직접 임포트 (표준 인터페이스)
from item_creator.utils_common import authorize_gspread, extract_sheet_id

# 생성 단계 로직
from .creation_steps import (
    run_step_C1,           # TEM_OUTPUT 초기화
    run_step_C2,           # Collection -> TEM_OUTPUT 생성 (Variation 공란 보정 포함)
    run_step_C4_prices,    # MARGIN 가격 → TEM 'SKU Price'
    run_step_C5_images,    # 이미지 URL 채우기 + Variation 복원
)

ProgressCB = Callable[[int, str], None]

def _progress(cb: Optional[ProgressCB], p: int, msg: str):
    if cb:
        try:
            cb(p, msg)
        except Exception:
            pass  # 진행표시 실패는 무시

class ShopeeCreator:
    """
    pages/3_Create Items.py에서 사용하는 컨트롤러.

    __init__(creation_spreadsheet_id, cover_base_url, details_base_url, option_base_url, ref_spreadsheet_id=None)
    run(progress_callback=...) -> dict
    """
    def __init__(
        self,
        creation_spreadsheet_id: str,
        cover_base_url: str,
        details_base_url: str,
        option_base_url: str,
        ref_spreadsheet_id: Optional[str] = None,
    ):
        self.creation_spreadsheet_id = extract_sheet_id(creation_spreadsheet_id)
        self.cover_base_url = cover_base_url
        self.details_base_url = details_base_url
        self.option_base_url = option_base_url
        self.ref_spreadsheet_id = extract_sheet_id(ref_spreadsheet_id) if ref_spreadsheet_id else None

        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

    def _connect(self):
        self.gc = authorize_gspread()
        if not self.creation_spreadsheet_id:
            raise RuntimeError("상품등록 시트 ID가 비어 있습니다.")
        self.sh = self.gc.open_by_key(self.creation_spreadsheet_id)
        self.ref = self.gc.open_by_key(self.ref_spreadsheet_id) if self.ref_spreadsheet_id else None

    def run(self, progress_callback: Optional[ProgressCB] = None) -> Dict[str, Any]:
        logs: List[str] = []

        def log_step(msg: str, p: int):
            logs.append(msg)
            _progress(progress_callback, p, msg)

        try:
            # 0) 연결
            log_step("Google Sheets 연결 중...", 5)
            self._connect()

            # 1) TEM_OUTPUT 초기화
            log_step("C1: TEM_OUTPUT 초기화...", 15)
            run_step_C1(self.sh, self.ref)

            # 2) Collection → TEM_OUTPUT
            log_step("C2: Collection → TEM_OUTPUT 생성...", 45)
            if not self.ref:
                raise RuntimeError("레퍼런스 시트가 필요합니다. (TemplateDict 등)")
            run_step_C2(self.sh, self.ref)

            # 3) 가격 매핑 (MARGIN → TEM 'SKU Price')
            log_step("C4: 가격 매핑(MARGIN → TEM 'SKU Price')...", 65)
            run_step_C4_prices(self.sh)

            # 4) 이미지 URL + Variation 복원
            log_step("C5: 이미지 URL 채우기 + Variation 복원...", 85)
            run_step_C5_images(
                sh=self.sh,
                shop_code="",  # 필요 시 env/폼에서 받은 값으로 교체 가능
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )

            log_step("완료!", 100)
            return {"logs": logs}

        except Exception:
            logs.append(f"[오류]\n{traceback.format_exc()}")
            return {"logs": logs, "error": "처리 중 오류가 발생했습니다."}
