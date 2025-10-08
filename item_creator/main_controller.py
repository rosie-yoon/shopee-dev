# item_creator/main_controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import traceback
from typing import Callable, Dict, Any, List, Optional

import streamlit as st
from gspread.exceptions import WorksheetNotFound

from item_creator.utils_common import (
    load_env,
    open_creation_by_env,
    open_ref_by_env,
    with_retry,
    safe_worksheet,
    get_env,
    extract_sheet_id,
    _authorize_and_open_by_key,  # type: ignore
)

# 업로드 파이프라인의 공용 스텝 활용(규격/속성/가격/설명 등)
import item_uploader.automation_steps as automation_steps

# 신규 생성 전용 스텝(템플릿 만들기/이미지 URL 매핑 등)
try:
    from item_creator import creation_steps
except Exception:
    creation_steps = None


class ShopeeCreator:
    """
    신규 아이템 업로드 템플릿을 생성하는 상위 컨트롤러.

    - 생성 스프레드시트(sh): 사용자의 '상품등록(개인)' 시트
    - ref 스프레드시트(ref): 공통 레퍼런스 시트(규격/규제/속성 등)
    - creation_steps: TEM_OUTPUT 템플릿 생성, 이미지 URL 매핑 등
    - automation_steps: 공용 규칙 채우기 / 최종 결과물 생성
    """

    def __init__(
        self,
        creation_spreadsheet_id: Optional[str] = None,
        cover_base_url: str = "",
        details_base_url: str = "",
        option_base_url: str = "",
        ref_spreadsheet_id: Optional[str] = None,
    ):
        """시트 연결 및 기본 파라미터 설정."""
        try:
            load_env()

            # 생성 대상 시트
            if creation_spreadsheet_id:
                sid = extract_sheet_id(creation_spreadsheet_id) or creation_spreadsheet_id
                self.sh = _authorize_and_open_by_key(sid)
            else:
                self.sh = open_creation_by_env()

            # 레퍼런스 시트
            if ref_spreadsheet_id:
                rid = extract_sheet_id(ref_spreadsheet_id) or ref_spreadsheet_id
                self.ref = _authorize_and_open_by_key(rid)
            else:
                self.ref = open_ref_by_env()

        except Exception as e:
            st.error(f"Google Sheets 연결에 실패했습니다: {e}")
            st.stop()

        # 이미지 베이스 URL & 샵 코드
        self.cover_base_url = (cover_base_url or "").strip()
        self.details_base_url = (details_base_url or "").strip()
        self.option_base_url = (option_base_url or "").strip()
        self.shop_code = get_env("SHOP_CODE", "").strip()

    # ------------------------- 내부 유틸 -------------------------

    def _initialize_failures_sheet(self) -> None:
        """실행 오류/스킵 행을 쌓는 Failures 시트를 초기화."""
        try:
            failures_ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: failures_ws.clear())
        except WorksheetNotFound:
            failures_ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=16))

        header = [["PID", "Category", "Name", "Reason", "Detail"]]
        with_retry(lambda: failures_ws.update(values=header, range_name="A1:E1"))

    @staticmethod
    def _cb(progress_callback: Optional[Callable[[int, str], Any]], pct: int, msg: str) -> None:
        """프로그레스 콜백이 있으면 안전하게 호출."""
        if progress_callback:
            try:
                progress_callback(pct, msg)
            except Exception:
                pass

    # ------------------------- 실행 엔진 -------------------------

    def run(self, progress_callback: Optional[Callable[[int, str], Any]] = None) -> Dict[str, Any]:
        """
        전체 파이프라인 실행.
        반환: {"download_path": str|None, "download_name": str|None, "logs": list[str]}
        """
        logs: List[str] = []
        download_path: Optional[str] = None
        download_name: Optional[str] = None

        try:
            # Failures 초기화
            self._cb(progress_callback, 5, "Failures 시트 초기화...")
            self._initialize_failures_sheet()
            logs.append("✅ Failures 초기화 완료")

            # C1: TEM_OUTPUT 템플릿 생성
            self._cb(progress_callback, 15, "Step C1: TEM_OUTPUT 템플릿 생성...")
            if creation_steps is None:
                raise RuntimeError("creation_steps 모듈이 없습니다. item_creator/creation_steps.py 를 생성하세요.")
            creation_steps.run_step_C1(self.sh, self.ref)
            logs.append("✅ C1 완료")

            # C2: Collection → TEM_OUTPUT 매핑
            self._cb(progress_callback, 35, "Step C2: Collection → TEM_OUTPUT 매핑...")
            creation_steps.run_step_C2(self.sh, self.ref)
            logs.append("✅ C2 완료")

            # C3: Mandatory 기본값 채우기 (공용 스텝2)
            self._cb(progress_callback, 50, "Step C3: Mandatory 기본값 채우기...")
            automation_steps.run_step_2(self.sh, self.ref)
            logs.append("✅ C3(=Step2) 완료")

            # C4: 규제/기본속성/설명·가격 채우기 (공용 스텝3/4/5)
            self._cb(progress_callback, 65, "Step C4: 규제/기본속성/설명·가격 채우기...")
            automation_steps.run_step_3(self.sh, self.ref, overwrite=True)
            automation_steps.run_step_4(self.sh, self.ref)
            automation_steps.run_step_5(self.sh)  # ← 여기서 BASIC 시트를 참조함 (오류 발생 지점)
            logs.append("✅ C4(=Step3/4/5) 완료")

            # C5: 이미지 URL 생성(커버/상세/옵션)
            self._cb(progress_callback, 80, "Step C5: 이미지 URL 생성(커버/상세/옵션)...")
            creation_steps.run_step_C5_images(
                sh=self.sh,
                shop_code=self.shop_code,
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )
            logs.append("✅ C5 완료")

            # Step 7: 최종 결과 생성 및 다운로드 파일 경로 추출
            self._cb(progress_callback, 92, "Step 7: 최종 결과 파일 생성...")
            result7 = automation_steps.run_step_7(self.sh)
            if isinstance(result7, dict):
                download_path = result7.get("download_path")
                download_name = result7.get("download_name")
            elif isinstance(result7, (list, tuple)) and result7:
                download_path = result7[0]
                download_name = os.path.basename(download_path) if download_path else None
            elif isinstance(result7, str):
                download_path = result7
                download_name = os.path.basename(download_path)
            logs.append("✅ Step7 완료")

            self._cb(progress_callback, 100, "완료!")

        except Exception as e:
            logs.append(f"❌ 오류: {e}")
            st.error("실행 중 오류가 발생했습니다.")
            st.code(traceback.format_exc())

        return {
            "download_path": download_path,
            "download_name": download_name,
            "logs": logs,
        }
