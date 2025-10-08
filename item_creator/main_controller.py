# item_creator/main_controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st
import gspread

from item_creator.utils_common import (
    get_env,
    save_env_value,
    extract_sheet_id,
    authorize_gspread,
)
from .creation_steps import (
    run_step_C1,
    run_step_C2,
    run_step_C4_prices,   # 신규: 가격 매핑
    run_step_C5_images,   # 기존: 이미지 URL/Variation 복원
)

class CreateItemsController:
    def __init__(self):
        self.gc: gspread.Client | None = None
        self.sh: gspread.Spreadsheet | None = None
        self.ref: gspread.Spreadsheet | None = None

    # 필요시 호출: 세션/입력값은 이미 별도 페이지에서 저장해 둔 상태라고 가정
    def _connect(self):
        self.gc = authorize_gspread()

        sheet_url = get_env("NEW_CREATE_SHEET_URL") or ""
        ref_url   = get_env("REFERENCE_SHEET_URL") or ""
        if not sheet_url or not ref_url:
            raise RuntimeError("필수 URL이 비어 있습니다. (상품등록 시트/레퍼런스 시트)")

        self.sh  = self.gc.open_by_key(extract_sheet_id(sheet_url))
        self.ref = self.gc.open_by_key(extract_sheet_id(ref_url))

    def run(self):
        st.subheader("실행")

        # 실행에 필요한 값 로드 (이미 ‘입력 & 저장’ 단계에서 저장했다고 가정)
        shop_code   = get_env("CREATE_SHOP_CODE") or ""
        cover_base  = get_env("CREATE_COVER_BASE_URL") or ""
        details_base= get_env("CREATE_DETAILS_BASE_URL") or ""
        option_base = get_env("CREATE_OPTION_BASE_URL") or ""

        # 기본 유효성 체크 (홈/입력 섹션에서 비활성화 이미 해두셨겠지만, 여기서도 한 번 더 방어)
        missing = []
        if not cover_base:   missing.append("Cover URL")
        if not details_base: missing.append("Details URL")
        if not option_base:  missing.append("Option URL")
        if missing:
            st.error("다음 항목이 비어 있습니다: " + ", ".join(missing))
            return

        if st.button("실행", type="primary", use_container_width=True, key="btn_create_run"):
            try:
                self._connect()

                # C1: TEM_OUTPUT 초기화
                run_step_C1(self.sh, self.ref)

                # C2: Collection → TEM_OUTPUT (A열 True / Variation 그룹 공란 자동 보정 포함)
                run_step_C2(self.sh, self.ref)

                # C4: (신규) 가격 매핑: MARGIN(A=SKU, E=소비자가) → TEM_OUTPUT('SKU Price')
                run_step_C4_prices(self.sh)

                # C5: 이미지 URL 채우기 + Variation 복원
                #     - Cover: (VIN 있으면 VIN, 아니면 SKU) + _C_{shop_code}.jpg
                #     - Option: OptionBaseURL + SKU
                #     - Details: DetailsBaseURL + (VIN or SKU) + _D1.._D{1~8}
                run_step_C5_images(
                    self.sh,
                    shop_code=shop_code,
                    cover_base_url=cover_base,
                    details_base_url=details_base,
                    option_base_url=option_base,
                )

                st.success("템플릿 생성 완료! (C1→C2→C4→C5)")

            except Exception as e:
                st.exception(e)
