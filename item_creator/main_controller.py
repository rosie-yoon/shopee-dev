# item_creator/main_controller.py

from __future__ import annotations
from typing import Callable, Optional, Dict, Any, List
import io, csv   # ⬅️ 추가
import traceback
import gspread
from gspread.exceptions import WorksheetNotFound  # ⬅️ 추가

# ... (생략)

class ShopeeCreator:
    def __init__(
        self,
        sheet_url: str,
        ref_url: Optional[str] = None,
        cover_base_url: str = "",
        details_base_url: str = "",
        option_base_url: str = "",
        shop_code: str = "",
    ):
        """Initialize with Google Sheet URLs (user-facing)."""

        # URL → ID 변환
        self.sheet_url = sheet_url
        self.ref_url = ref_url
        self.sheet_id = extract_sheet_id(sheet_url)
        self.ref_id = extract_sheet_id(ref_url) if ref_url else None

        # 기본 URL 설정
        self.cover_base_url = cover_base_url
        self.details_base_url = details_base_url
        self.option_base_url = option_base_url

        # 샵코드 저장
        self.shop_code = shop_code


        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

    def _connect(self):
        self.gc = authorize_gspread()
        # ... (그대로)

    def _clear_failures(self):
        """Failures 시트 헤더만 남기고 비우기(없으면 생성)."""
        try:
            ws = self.sh.worksheet("Failures")
        except WorksheetNotFound:
            ws = self.sh.add_worksheet(title="Failures", rows=1000, cols=10)
        ws.clear()
        ws.update("A1:E1", [["PID","Category","Name","Reason","Detail"]])

    def _get_tem_values_csv(self) -> tuple[bytes, str]:
        """TEM_OUTPUT 전체를 CSV 바이트와 파일명으로 반환."""
        tem_ws = self.sh.worksheet(get_tem_sheet_name())
        vals = tem_ws.get_all_values() or [[""]]
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerows(vals)
        data = buf.getvalue().encode("utf-8-sig")
        return data, "TEM_OUTPUT.csv"

    def run(self, progress_callback: Optional[ProgressCB] = None) -> Dict[str, Any]:
        logs: List[str] = []

        def log_step(msg: str, p: int):
            logs.append(msg); _progress(progress_callback, p, msg)

        try:
            log_step("Google Sheets 연결 중...", 5)
            self._connect()

            # ⬇️ 매 실행 시 Failures 초기화
            self._clear_failures()

            log_step("C1: TEM_OUTPUT 초기화...", 15)
            run_step_C1(self.sh, self.ref)

            log_step("C2: Collection → TEM_OUTPUT 생성...", 45)
            if not self.ref:
                raise RuntimeError("레퍼런스 시트가 필요합니다. (TemplateDict 등)")
            run_step_C2(self.sh, self.ref)

            log_step("C4: 가격/기본값/무게 매핑...", 65)
            run_step_C4_prices(self.sh)  # (아래 2)에서 확장)

            log_step("C5: 이미지 URL 채우기 + Variation 복원...", 85)
            run_step_C5_images(
                sh=self.sh,
                shop_code=self.shop_code,  # ⬅️ 샵코드 전달
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )

            # ⬇️ CSV 생성해서 페이지로 반환
            data, name = self._get_tem_values_csv()
            log_step("완료!", 100)
            return {"logs": logs, "download_bytes": data, "download_name": name}

        except Exception as e:
            logs.append(f"[오류]\n{traceback.format_exc()}")
            return {"logs": logs, "error": str(e)}
