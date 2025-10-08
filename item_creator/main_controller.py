# -*- coding: utf-8 -*-
"""
main_controller.py  (A안: 페이지와 100% 호환 + 의존 경로 완화 + 무수정 동작)

목표
- Streamlit 페이지(pages/3_Create Items.py)가 기대하는 인터페이스와 정확히 일치
  - 클래스명: ShopeeCreator
  - __init__(sheet_url, ref_url=None, cover_base_url=None, details_base_url=None,
             option_base_url=None, shop_code=None, **kwargs)
  - run() -> bool
  - get_tem_values_csv() -> Optional[bytes]
- 외부 패키지 경로(item_uploader.*, item_creator.*)에 묶이지 않도록 안전한 임포트/폴백
  - 로컬 utils_common.py를 우선 사용
  - creation_steps.py가 과거 경로를 임포트하더라도, 런타임 shim으로 해결

동작 개요
- (1) utils_common 임포트: 로컬 > item_creator.utils_common > item_uploader.utils_common
- (2) shim 등록: creation_steps가 과거 경로를 임포트해도 통과되도록
- (3) creation_steps 모듈 임포트 후, 내부 ShopeeCreator를 위임 객체(impl)로 사용
- (4) 페이지가 넘겨준 base URL / shop_code는 impl에 동일 이름 속성으로 주입(존재 유무 무관)

※ 다른 파일은 수정하지 않아도 됩니다.
"""

from __future__ import annotations

from typing import Optional, Tuple
import sys
import types
import io
import csv

# ---------------------------------------------------------------------
# 1) 안전한 utils 임포트 (로컬 우선)
# ---------------------------------------------------------------------
_last_import_error = None

authorize_gspread = None
extract_sheet_id = None
get_tem_sheet_name = None

# 로컬 utils_common.py 우선
try:
    from utils_common import authorize_gspread as _auth_local
    from utils_common import extract_sheet_id as _extract_local
    # get_tem_sheet_name 이 없을 수도 있어 폴백 처리
    try:
        from utils_common import get_tem_sheet_name as _tem_name_local  # type: ignore
    except Exception:
        _tem_name_local = None
    authorize_gspread = _auth_local
    extract_sheet_id = _extract_local
    get_tem_sheet_name = _tem_name_local
except Exception as e:
    _last_import_error = e

# item_creator.utils_common 폴백
if authorize_gspread is None or extract_sheet_id is None:
    try:
        from item_creator.utils_common import authorize_gspread as _auth_ic  # type: ignore
        from item_creator.utils_common import extract_sheet_id as _extract_ic  # type: ignore
        try:
            from item_creator.utils_common import get_tem_sheet_name as _tem_name_ic  # type: ignore
        except Exception:
            _tem_name_ic = None
        authorize_gspread = authorize_gspread or _auth_ic
        extract_sheet_id = extract_sheet_id or _extract_ic
        get_tem_sheet_name = get_tem_sheet_name or _tem_name_ic
    except Exception as e:
        _last_import_error = e

# item_uploader.utils_common 최후 폴백
if authorize_gspread is None or extract_sheet_id is None:
    try:
        from item_uploader.utils_common import authorize_gspread as _auth_iu  # type: ignore
        from item_uploader.utils_common import extract_sheet_id as _extract_iu  # type: ignore
        try:
            from item_uploader.utils_common import get_tem_sheet_name as _tem_name_iu  # type: ignore
        except Exception:
            _tem_name_iu = None
        authorize_gspread = authorize_gspread or _auth_iu
        extract_sheet_id = extract_sheet_id or _extract_iu
        get_tem_sheet_name = get_tem_sheet_name or _tem_name_iu
    except Exception as e:
        _last_import_error = e

if authorize_gspread is None or extract_sheet_id is None:
    raise ImportError(
        "authorize_gspread / extract_sheet_id 가져오기 실패. "
        "프로젝트 루트 utils_common.py가 존재하는지 확인하세요."
    ) from _last_import_error

# TEM 시트명 유틸이 없으면 기본값 제공
if get_tem_sheet_name is None:
    def get_tem_sheet_name() -> str:  # type: ignore
        return "TEM_OUTPUT"

# ---------------------------------------------------------------------
# 2) 임포트 shim: creation_steps.py가 과거 경로를 임포트해도 통과
# ---------------------------------------------------------------------
# - creation_steps.py 최상단에서 'from item_uploader.utils_common import ...' 등을 수행하는
#   레거시 코드를 고려해, 해당 경로를 로컬 utils_common에 매핑한다.
uploader_pkg = types.ModuleType("item_uploader")
utils_mod = sys.modules.get("utils_common")
if utils_mod is None:
    # 방어: 혹시 위에서 로컬 임포트가 안 됐다면 실제 주입된 모듈을 찾아 등록
    import importlib
    utils_mod = importlib.import_module("utils_common")

uploader_utils = types.ModuleType("item_uploader.utils_common")
# 로컬 utils에서 필요한 심볼을 그대로 export
for _name in ("authorize_gspread", "extract_sheet_id", "get_tem_sheet_name",
              "open_creation_by_env", "ensure_worksheet", "join_url",
              "choose_cover_key", "forward_fill_by_group", "safe_worksheet",
              "with_retry"):
    if hasattr(utils_mod, _name):
        setattr(uploader_utils, _name, getattr(utils_mod, _name))

# automation_steps.get_tem_sheet_name shim
uploader_auto = types.ModuleType("item_uploader.automation_steps")
setattr(uploader_auto, "get_tem_sheet_name", get_tem_sheet_name)

# sys.modules에 주입
sys.modules.setdefault("item_uploader", uploader_pkg)
sys.modules["item_uploader.utils_common"] = uploader_utils
sys.modules["item_uploader.automation_steps"] = uploader_auto

# (선택) item_creator 경로도 동일하게 보정
creator_pkg = types.ModuleType("item_creator")
sys.modules.setdefault("item_creator", creator_pkg)
sys.modules["item_creator.utils_common"] = utils_mod  # 로컬 utils 재사용

# ---------------------------------------------------------------------
# 3) creation_steps 모듈 임포트
#    - 이 모듈 안에 ShopeeCreator(impl)가 정의되어 있으며 run()->bool,
#      get_tem_values_csv()->Optional[bytes] 를 제공한다.
# ---------------------------------------------------------------------
try:
    import creation_steps as _steps_mod
    _ImplCreator = getattr(_steps_mod, "ShopeeCreator", None)
except Exception as e:
    _ImplCreator = None
    _last_import_error = e

# ---------------------------------------------------------------------
# 4) 페이지 호환 컨트롤러 (래퍼)
# ---------------------------------------------------------------------
class ShopeeCreator:
    """
    페이지(3_Create Items.py)가 직접 사용하는 컨트롤러 (호환 래퍼).

    - __init__ 인자와 run()/get_tem_values_csv() 시그니처를 페이지에 맞춤
    - 내부적으로 creation_steps.ShopeeCreator(impl) 에 위임
    - impl이 없더라도 친절한 에러를 반환 (ImportError 등)
    """

    def __init__(
        self,
        *,
        sheet_url: str,
        ref_url: Optional[str] = None,
        cover_base_url: Optional[str] = None,
        details_base_url: Optional[str] = None,
        option_base_url: Optional[str] = None,
        shop_code: Optional[str] = None,
        **_: object,
    ) -> None:
        if not sheet_url:
            raise ValueError("sheet_url is required.")

        self.sheet_url = sheet_url
        self.ref_url = ref_url
        self.cover_base_url = cover_base_url
        self.details_base_url = details_base_url or None  # 페이지에선 details_base_url 키 사용
        self.option_base_url = option_base_url
        self.shop_code = shop_code

        self._impl = None
        if _ImplCreator is not None:
            try:
                self._impl = _ImplCreator(sheet_url=sheet_url, ref_url=ref_url)
                # 페이지에서 넘긴 값 주입(impl이 사용하지 않아도 무해)
                for k in ("cover_base_url", "details_base_url", "option_base_url", "shop_code"):
                    setattr(self._impl, k, getattr(self, k))
            except Exception:
                # impl 생성 실패 시에도 런타임에서 에러를 안내하도록 유지
                self._impl = None

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        전체 파이프라인 실행. success/fail bool 반환 (페이지 호환).
        """
        if self._impl is None:
            # impl 로드 실패 원인 안내
            raise ImportError(
                "creation_steps 모듈 로드에 실패했습니다. "
                "로컬 utils_common.py가 존재하고, 본 파일의 shim 등록이 수행되는지 확인하세요."
            ) from _last_import_error
        try:
            return bool(self._impl.run())
        except Exception:
            # impl 내부 예외는 그대로 propagate 하되, 페이지에서 st.exception 으로 표시됨
            raise

    # ----------------------------------------------------------
    # TEM_OUTPUT → CSV
    # ----------------------------------------------------------
    def get_tem_values_csv(self) -> Optional[bytes]:
        """
        TEM_OUTPUT 시트를 CSV 바이트로 반환. (페이지 호환)
        """
        if self._impl and hasattr(self._impl, "get_tem_values_csv"):
            try:
                return self._impl.get_tem_values_csv()
            except Exception:
                # impl의 CSV 변환 실패 시 폴백 로직 시도
                pass

        # 폴백: 직접 시트에서 읽어 CSV 생성 (TEM 시트명 유틸 사용)
        try:
            import gspread
            gc = authorize_gspread()
            sh = gc.open_by_key(extract_sheet_id(self.sheet_url))
            ws = sh.worksheet(get_tem_sheet_name())
            values = ws.get_all_values() or []
            if not values:
                return None
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerows(values)
            return buf.getvalue().encode("utf-8-sig")
        except Exception:
            return None
