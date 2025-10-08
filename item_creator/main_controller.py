# item_creator/main_controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, Dict, Any, List, Callable, Tuple
import io
import csv
import traceback

import gspread
from gspread.exceptions import WorksheetNotFound

# ---------------------------------------------------------------------
# (안전) URL → Sheet ID 추출 유틸: item_creator → item_uploader → 폴백
# ---------------------------------------------------------------------
try:
    from item_creator.utils_common import extract_sheet_id  # 있으면 사용
except Exception:
    try:
        from item_uploader.utils_common import extract_sheet_id  # 검증된 경로
    except Exception:
        import re
        def extract_sheet_id(url_or_id: str | None) -> str:
            if not url_or_id:
                return ""
            s = str(url_or_id).strip()
            if s.startswith("http"):
                m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", s)
                return m.group(1) if m else s
            return s  # 이미 ID인 경우 그대로

# ---------------------------------------------------------------------
# (안전) gspread 인증 유틸
# ---------------------------------------------------------------------
try:
    # 업로더 쪽 유틸에는 검증된 authorize_gspread가 존재
    from item_uploader.utils_common import authorize_gspread
except Exception:
    # item_creator에 별도 구현이 있다면 여기에 추가하거나, 에러 발생
    raise ImportError("authorize_gspread 를 찾을 수 없습니다. item_uploader.utils_common 에서 제공되는 함수를 사용하세요.")

# ---------------------------------------------------------------------
# 생성 단계 함수들(신규 생성 전용)
# ---------------------------------------------------------------------
from item_uploader.automation_steps import get_tem_sheet_name  # TEM 시트명 규칙
from item_creator.creation_steps import (
    run_step_C1,                  # TEM_OUTPUT 초기화
    run_step_C2,                  # Collection → TEM 생성(+그룹 보정)
    run_step_C4_prices,           # MARGIN → TEM 가격 매핑
    run_step_C5_images,           # 이미지 URL 채우기 + Variation 복원
    run_step_C6_stock_weight_brand,  # 재고/무게/브랜드 기본값 처리
)

# ---------------------------------------------------------------------
# (선택) 진행률 콜백 타입 & 헬퍼
# ---------------------------------------------------------------------
ProgressCB = Callable[[int, str], None]
def _progress(cb: Optional[ProgressCB], percent: int, message: str) -> None:
    if cb:
        cb(percent, message)

# =====================================================================
# 컨트롤러
# =====================================================================
class ShopeeCreator:
    """
    페이지 코드와 완전 호환:
      - __init__(sheet_url, ref_url, cover_base_url, details_base_url, option_base_url, shop_code)
      - run(shop_code=..., cover_base_url=..., details_base_url=..., option_base_url=...)  ← 페이지에서 이렇게 호출
    """

    def __init__(
        self,
        sheet_url: str,
        ref_url: Optional[str] = None,
        cover_base_url: str = "",
        details_base_url: str = "",
        option_base_url: str = "",
        shop_code: str = "",
    ):
        # URL → ID
        self.sheet_url = sheet_url
        self.ref_url = ref_url
        self.sheet_id = extract_sheet_id(sheet_url)
        self.ref_id = extract_sheet_id(ref_url) if ref_url else None

        # 기본 URL / 샵코드(초깃값)
        self.cover_base_url = cover_base_url
        self.details_base_url = details_base_url
        self.option_base_url = option_base_url
        self.shop_code = shop_code

        # 연결 핸들
        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

    # ----------------------------------------------------------
    # 내부: Google Sheets 연결
    # ----------------------------------------------------------
    def _connect(self) -> None:
        if not self.sheet_id:
            raise RuntimeError("상품등록 시트 URL/ID가 비었습니다.")
        self.gc = authorize_gspread()
        self.sh = self.gc.open_by_key(self.sheet_id)
        if self.ref_id:
            self.ref = self.gc.open_by_key(self.ref_id)

    # ----------------------------------------------------------
    # 내부: Failures 시트 초기화(헤더만 남김)
    # ----------------------------------------------------------
    def _clear_failures(self) -> None:
        assert self.sh is not None
        try:
            ws = self.sh.worksheet("Failures")
        except WorksheetNotFound:
            ws = self.sh.add_worksheet(title="Failures", rows=1000, cols=10)
        ws.clear()
        ws.update("A1:E1", [["PID", "Category", "Name", "Reason", "Detail"]])

    # ----------------------------------------------------------
    # 내부: TEM_OUTPUT CSV 바이트 + 파일명 반환
    # ----------------------------------------------------------
    def _get_tem_values_csv(self) -> Tuple[bytes, str]:
        assert self.sh is not None
        tem_ws = self.sh.worksheet(get_tem_sheet_name())
        vals = tem_ws.get_all_values() or [[""]]
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerows(vals)
        data = buf.getvalue().encode("utf-8-sig")
        return data, "TEM_OUTPUT.csv"

    # ----------------------------------------------------------
    # 실행(페이지와 호환): 인자 넘기면 필드 업데이트 후 파이프라인 실행
    # ----------------------------------------------------------
    def run(
        self,
        shop_code: Optional[str] = None,
        cover_base_url: Optional[str] = None,
        details_base_url: Optional[str] = None,
        option_base_url: Optional[str] = None,
        progress_callback: Optional[ProgressCB] = None,
    ) -> Dict[str, Any]:
        """C1 → C2 → C4 → C5 → C6 전체 파이프라인 실행."""
        logs: List[str] = []

        def log_step(msg: str, p: int):
            logs.append(msg)
            _progress(progress_callback, p, msg)

        # 필요 시 필드 최신화(페이지에서 run()에 넘긴 값 우선)
        if shop_code is not None:
            self.shop_code = shop_code
        if cover_base_url is not None:
            self.cover_base_url = cover_base_url
        if details_base_url is not None:
            self.details_base_url = details_base_url
        if option_base_url is not None:
            self.option_base_url = option_base_url

        try:
            log_step("Google Sheets 연결 중...", 5)
            self._connect()
            assert self.sh is not None

            log_step("실패 로그 초기화...", 10)
            self._clear_failures()

            log_step("C1: TEM_OUTPUT 초기화...", 20)
            run_step_C1(self.sh, self.ref)

            log_step("C2: Collection → TEM_OUTPUT 생성...", 50)
            if not self.ref:
                raise RuntimeError("레퍼런스 시트(TemplateDict 등) 연결 필요")
            run_step_C2(self.sh, self.ref)

            log_step("C4: MARGIN → TEM 가격 매핑...", 70)
            run_step_C4_prices(self.sh)

            log_step("C5: 이미지 URL 채우기 + Variation 복원...", 85)
            run_step_C5_images(
                sh=self.sh,
                shop_code=self.shop_code or "",
                cover_base_url=self.cover_base_url or "",
                details_base_url=self.details_base_url or "",
                option_base_url=self.option_base_url or "",
            )

            log_step("C6: 재고/무게/브랜드 기본값 처리...", 92)
            run_step_C6_stock_weight_brand(self.sh)

            log_step("CSV 내보내기 준비...", 97)
            data, name = self._get_tem_values_csv()

            log_step("완료!", 100)
            return {
                "logs": logs,
                "download_bytes": data,
                "download_name": name,
            }

        except Exception as e:
            logs.append(f"[오류]\n{traceback.format_exc()}")
            return {"logs": logs, "error": str(e)}
