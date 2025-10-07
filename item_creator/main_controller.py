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
)

# 내부 헬퍼(인증 + open_by_key)를 재사용합니다.
# utils_common.py에 정의된 내부 함수를 import 해 사용합니다.
from item_creator.utils_common import _authorize_and_open_by_key  # type: ignore

# 기존 공용 단계(2,3,4,7 등)는 automation_steps에서 재사용
import item_uploader.automation_steps as automation_steps  # run_step_2, run_step_3, run_step_4, run_step_7 재사용
# 신규 생성 전용 단계(C1,C2,C5 등)는 creation_steps에서 정의합니다.
# (아직 없다면 생성해 주세요: item_creator/creation_steps.py)
try:
    from item_creator import creation_steps
except Exception:
    creation_steps = None  # 초기 개발 단계에서 모듈 미존재 허용


class ShopeeCreator:
    """
    신규 생성(Create) 모드 전용 컨트롤러.

    - 입력: '상품등록' 개인 시트 (MARGIN / Collection 탭)
    - 출력: TEM_OUTPUT 작성 및 카테고리별 분할 파일 생성
    - 이미지 규칙:
        * I열(Image per Variation)  = Option Base URL + SKU
        * O열(Cover)                = Cover Base URL + (VariationIntegrationNo or SKU) + '_C_{shop_code}.jpg'  ← 신규 규칙
        * P~W(Item Image 1~8)       = Details Base URL + (VariationIntegrationNo or SKU) + _D{n}
    """

    def __init__(
        self,
        creation_spreadsheet_id: Optional[str] = None,
        cover_base_url: str = "",
        details_base_url: str = "",
        option_base_url: str = "",
        ref_spreadsheet_id: Optional[str] = None,
    ):
        """
        Args:
            creation_spreadsheet_id: '상품등록' 시트 ID 또는 전체 URL
            cover_base_url:     Cover 이미지 베이스 URL
            details_base_url:   상세 이미지(1~8) 베이스 URL
            option_base_url:    옵션 이미지 베이스 URL
            ref_spreadsheet_id: 레퍼런스 시트 ID (없으면 env/secrets 기반 open_ref_by_env)
        """
        try:
            load_env()

            # 시트 오픈: ID가 들어오면 해당 키로, 없으면 env/secrets의 CREATION_SPREADSHEET_ID 사용
            if creation_spreadsheet_id:
                sid = extract_sheet_id(creation_spreadsheet_id) or creation_spreadsheet_id
                self.sh = _authorize_and_open_by_key(sid)
            else:
                # .env / secrets 에 저장된 CREATION_SPREADSHEET_ID 사용
                self.sh = open_creation_by_env()

            # 레퍼런스 시트(선택)
            if ref_spreadsheet_id:
                rid = extract_sheet_id(ref_spreadsheet_id) or ref_spreadsheet_id
                self.ref = _authorize_and_open_by_key(rid)
            else:
                self.ref = open_ref_by_env()

        except Exception as e:
            st.error(f"Google Sheets 연결에 실패했습니다: {e}")
            st.stop()

        # Base URLs (필수 3종)
        self.cover_base_url = (cover_base_url or "").strip()
        self.details_base_url = (details_base_url or "").strip()
        self.option_base_url = (option_base_url or "").strip()

        # shop_code는 기존 복제 모드처럼 suffix에 쓰이지만, 신규 모드 UI에선 입력을 받지 않습니다.
        # 필요 시 .env 또는 secrets에서 불러와 사용(없으면 공란 → suffix 생략 처리)
        self.shop_code = get_env("SHOP_CODE", "").strip()

    # ---------------------------------------------------------------------
    # 내부 유틸
    # ---------------------------------------------------------------------
    def _initialize_failures_sheet(self):
        """Failures 탭 초기화(없으면 생성). 헤더: PID, Category, Name, Reason, Detail"""
        try:
            failures_ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: failures_ws.clear())
        except WorksheetNotFound:
            failures_ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=16))

        header = [["PID", "Category", "Name", "Reason", "Detail"]]
        with_retry(lambda: failures_ws.update(values=header, range_name="A1:E1"))

    def _cb(self, progress_callback: Optional[Callable[[int, str], Any]], pct: int, msg: str):
        if progress_callback:
            try:
                progress_callback(pct, msg)
            except Exception:
                pass  # 콜백 오류는 무시

    # ---------------------------------------------------------------------
    # 실행 진입점
    # ---------------------------------------------------------------------
    def run(self, progress_callback: Optional[Callable[[int, str], Any]] = None) -> Dict[str, Any]:
        """
        전체 파이프라인 실행.
        Returns:
            dict: {
              "download_path": str | None,
              "download_name": str | None,
              "logs": List[str]
            }
        """
        logs: List[str] = []
        download_path: Optional[str] = None
        download_name: Optional[str] = None

        try:
            # 0) Failures 초기화
            self._cb(progress_callback, 5, "Failures 시트 초기화...")
            self._initialize_failures_sheet()
            logs.append("✅ Failures 초기화 완료")

            # 1) C1: TEM_OUTPUT 시트(헤더/템플릿) 준비
            self._cb(progress_callback, 15, "Step C1: TEM_OUTPUT 템플릿 생성...")
            if creation_steps is None:
                raise RuntimeError("creation_steps 모듈이 없습니다. item_creator/creation_steps.py 를 생성하세요.")
            creation_steps.run_step_C1(self.sh, self.ref)  # A열 유지/헤더 구성 포함
            logs.append("✅ C1 완료")

            # 2) C2: Collection → TEM_OUTPUT 매핑 생성 (forward-fill + 필터 A=True)
            self._cb(progress_callback, 35, "Step C2: Collection → TEM_OUTPUT 매핑...")
            creation_steps.run_step_C2(self.sh, self.ref)
            logs.append("✅ C2 완료")

            # 3) C3: Mandatory/카테고리 기본값 채우기 (기존 Step2 재사용)
            self._cb(progress_callback, 50, "Step C3: Mandatory 기본값 채우기...")
            automation_steps.run_step_2(self.sh, self.ref)
            logs.append("✅ C3(=Step2) 완료")

            # 4) C4: FDA/재고/브랜드/무게/가격/설명 등 보강 (기존 Step3/4/5 재사용)
            self._cb(progress_callback, 65, "Step C4: 규제/기본속성/설명·가격 채우기...")
            # FDA 코드(덮어쓰기 True)
            automation_steps.run_step_3(self.sh, self.ref, overwrite=True)
            # 재고/무게/브랜드 등 (MARGIN/Brand 레퍼런스 기반)
            automation_steps.run_step_4(self.sh, self.ref)
            # 설명/가격/Variation 관련(필요 부분만 사용)
            automation_steps.run_step_5(self.sh)
            logs.append("✅ C4(=Step3/4/5) 완료")

            # 5) C5: 이미지 URL 생성(커버/상세/옵션) - 신규 규칙
            self._cb(progress_callback, 80, "Step C5: 이미지 URL 생성(커버/상세/옵션)...")
            creation_steps.run_step_C5_images(
                sh=self.sh,
                shop_code=self.shop_code,  # 없으면 내부에서 suffix 생략하도록 작성
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )
            logs.append("✅ C5 완료")

            # 6) 최종 산출물 생성(카테고리별 분할 저장) - 기존 Step7 재사용
            self._cb(progress_callback, 92, "Step 7: 최종 결과 파일 생성...")
            # run_step_7은 내부에서 파일을 만들고 경로/이름을 반환하도록 해 주세요.
            # 기존 코드와의 호환을 위해 다양한 반환형을 허용합니다.
            result7 = automation_steps.run_step_7(self.sh)

            # 반환 처리(여러 형태 허용)
            if isinstance(result7, dict):
                download_path = result7.get("download_path")
                download_name = result7.get("download_name")
            elif isinstance(result7, (list, tuple)) and len(result7) >= 1:
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
