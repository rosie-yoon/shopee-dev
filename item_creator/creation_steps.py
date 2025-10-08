# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, List
import io
import csv

import gspread
from gspread.exceptions import WorksheetNotFound
from gspread.utils import rowcol_to_a1

# 업로더 공용 유틸 재사용 (인증, 시트 접근, 리트라이 등)
from item_uploader.utils_common import (
    authorize_gspread,
    extract_sheet_id,
    with_retry,
    safe_worksheet,
)

# --------------------------------------------------------------------------
# [수정]: 순환 임포트를 유발하는 'from .creation_steps import ...' 구문을 제거합니다.
# 대신, 모듈이 로드될 수 있도록 임시로 단계 함수들을 정의합니다.
# 실제 코드를 작성할 때는 이 위치에 run_step_C1, run_step_C2 등의 구현이 들어와야 합니다.
# --------------------------------------------------------------------------

def run_step_C1(sh, ref):
    print("Step C1: TEM_OUTPUT 초기화 (임시)")
def run_step_C2(sh, ref):
    print("Step C2: Collection → TEM_OUTPUT (임시)")
def run_step_C4_prices(sh):
    print("Step C4: MARGIN → TEM SKU Price (임시)")
def run_step_C5_images(sh, **kwargs):
    print("Step C5: 이미지 URL 매핑 (임시)")
def run_step_C6_stock_weight_brand(sh):
    print("Step C6: Stock/Weight/Brand 보정 (임시)")


class ShopeeCreator:
    """
    신규 상품 템플릿 생성 파이프라인 컨트롤러.
    Streamlit 페이지(3_Create Items.py)에서 호출됨.
    """

    def __init__(self, sheet_url: str, ref_url: Optional[str] = None) -> None:
        """
        Args:
            sheet_url: 사용자 개인 상품등록 시트 URL (MARGIN / Collection 포함)
            ref_url:   템플릿 참조용 시트 (REFERENCE_SPREADSHEET_ID)
        """
        if not sheet_url:
            raise ValueError("sheet_url is required.")
        self.sheet_url = sheet_url
        self.ref_url = ref_url

        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

    # ----------------------------------------------------------
    # 내부 유틸
    # ----------------------------------------------------------

    def _connect(self) -> None:
        """gspread 인증 및 대상/레퍼런스 스프레드시트 오픈"""
        self.gc = authorize_gspread()
        ss_id = extract_sheet_id(self.sheet_url)
        if not ss_id:
            raise ValueError("Invalid sheet_url: cannot extract spreadsheet ID.")
        # [주의] 이 부분은 실제 실행 시 gspread 연결 문제로 오류가 발생할 수 있습니다.
        # 실행 환경에 따라 적절한 인증 정보가 필요합니다.
        self.sh = with_retry(lambda: self.gc.open_by_key(ss_id))

        if self.ref_url:
            ref_id = extract_sheet_id(self.ref_url)
            if ref_id:
                try:
                    self.ref = with_retry(lambda: self.gc.open_by_key(ref_id))
                except Exception:
                    self.ref = None
            else:
                self.ref = None

    def _reset_failures(self) -> None:
        """실행 시마다 Failures 시트를 초기화"""
        assert self.sh is not None
        try:
            ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: ws.clear())
        except WorksheetNotFound:
            ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=10))
        with_retry(lambda: ws.update(values=[["PID", "Category", "Name", "Reason", "Detail"]], range_name="A1"))

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C4 → C5 → C6
        """
        try:
            # 인증 및 시트 연결
            self._connect()
            assert self.sh is not None

            # 실패 로그 초기화
            self._reset_failures()

            # 단계 실행
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C4_prices(self.sh)
            run_step_C5_images(
                self.sh,
                shop_code=getattr(self, "shop_code", None), # main_controller 래퍼에서 주입될 수 있음
                cover_base_url=getattr(self, "cover_base_url", None),
                details_base_url=getattr(self, "details_base_url", None),
                option_base_url=getattr(self, "option_base_url", None),
            )
            run_step_C6_stock_weight_brand(self.sh)

            print("✅ 모든 단계 완료되었습니다.")
            return True

        except Exception as e:
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False


    # ----------------------------------------------------------
    # CSV Export
    # ----------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """TEM_OUTPUT 시트를 CSV 바이트로 반환"""
        if not self.sh:
            return None

        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals:
                return None

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerows(vals)
            return buf.getvalue().encode("utf-8-sig")
        except Exception as e:
            print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
            return None
