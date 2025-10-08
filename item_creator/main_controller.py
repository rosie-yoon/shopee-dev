# -*- coding: utf-8 -*-
"""
main_controller.py (A안 v2: 배포 환경에서 utils_common 확실히 찾도록 보강)

- 페이지(pages/3_Create Items.py)와 인터페이스 100% 호환:
  class ShopeeCreator(...); run()->bool; get_tem_values_csv()->Optional[bytes]
- utils_common 임포트 안정화:
  1) repo root를 sys.path에 선주입
  2) 실패 시, 파일 경로에서 직접 모듈 로드
  3) item_creator / item_uploader 경로 폴백
- creation_steps의 레거시 import를 shim으로 흡수
"""

from __future__ import annotations
from typing import Optional
import sys, types, io, csv
from pathlib import Path
import importlib, importlib.util

# -----------------------------------------------------------------------------
# 0) repo root를 sys.path에 선주입 (배포 환경 보호)
# -----------------------------------------------------------------------------
_THIS = Path(__file__).resolve()                          # .../item_creator/main_controller.py
_ROOT = _THIS.parents[1]                                  # repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# item_creator 폴더도 보수적으로 추가
_ITEM_CREATOR_DIR = _THIS.parent
if str(_ITEM_CREATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_ITEM_CREATOR_DIR))

# -----------------------------------------------------------------------------
# 1) utils_common 안전 임포트 (로컬 > 직접 로드 > item_creator > item_uploader)
# -----------------------------------------------------------------------------
_last_import_error = None

authorize_gspread = None
extract_sheet_id = None
get_tem_sheet_name = None

def _load_utils_direct() -> object:
    """루트의 utils_common.py를 경로로 직접 로드."""
    uc_path = _ROOT / "utils_common.py"
    if not uc_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("utils_common", uc_path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["utils_common"] = mod
    spec.loader.exec_module(mod)
    return mod

# (a) 로컬 이름 임포트 시도
utils_mod = None
try:
    utils_mod = importlib.import_module("utils_common")
except Exception as e:
    _last_import_error = e

# (b) 직접 로드(파일 경로) 폴백
if utils_mod is None:
    try:
        utils_mod = _load_utils_direct()
    except Exception as e:
        _last_import_error = e

# (c) item_creator.utils_common 폴백
if utils_mod is None:
    try:
        utils_mod = importlib.import_module("item_creator.utils_common")  # type: ignore
    except Exception as e:
        _last_import_error = e

# (d) item_uploader.utils_common 폴백
if utils_mod is None:
    try:
        utils_mod = importlib.import_module("item_uploader.utils_common")  # type: ignore
    except Exception as e:
        _last_import_error = e

if utils_mod is None:
    raise ImportError("No module named 'utils_common' (repo root에 utils_common.py가 있는지 확인)") from _last_import_error

# 심볼 바인딩
authorize_gspread = getattr(utils_mod, "authorize_gspread", None)
extract_sheet_id   = getattr(utils_mod, "extract_sheet_id", None)
get_tem_sheet_name = getattr(utils_mod, "get_tem_sheet_name", None)

if authorize_gspread is None or extract_sheet_id is None:
    raise ImportError("utils_common에서 authorize_gspread / extract_sheet_id를 찾을 수 없습니다.")

if get_tem_sheet_name is None:
    def get_tem_sheet_name() -> str:
        return "TEM_OUTPUT"

# -----------------------------------------------------------------------------
# 2) shim 주입: creation_steps의 레거시 경로(item_uploader.*)를 로컬 utils로 매핑
# -----------------------------------------------------------------------------
uploader_pkg = types.ModuleType("item_uploader")
uploader_utils = types.ModuleType("item_uploader.utils_common")
for _name in (
    "authorize_gspread", "extract_sheet_id", "get_tem_sheet_name",
    "open_creation_by_env", "ensure_worksheet", "join_url",
    "choose_cover_key", "forward_fill_by_group", "safe_worksheet", "with_retry"
):
    if hasattr(utils_mod, _name):
        setattr(uploader_utils, _name, getattr(utils_mod, _name))
uploader_auto = types.ModuleType("item_uploader.automation_steps")
setattr(uploader_auto, "get_tem_sheet_name", get_tem_sheet_name)

sys.modules.setdefault("item_uploader", uploader_pkg)
sys.modules["item_uploader.utils_common"] = uploader_utils
sys.modules["item_uploader.automation_steps"] = uploader_auto
# item_creator 경로도 동일하게 보정(로컬 utils 재사용)
sys.modules.setdefault("item_creator", types.ModuleType("item_creator"))
sys.modules["item_creator.utils_common"] = utils_mod  # 로컬 utils 재사용

# -----------------------------------------------------------------------------
# 3) creation_steps 임포트 (여기서 레거시 import를 shim이 흡수)
# -----------------------------------------------------------------------------
_ImplCreator = None
try:
    import creation_steps as _steps_mod
    _ImplCreator = getattr(_steps_mod, "ShopeeCreator", None)
except Exception as e:
    _last_import_error = e

# -----------------------------------------------------------------------------
# 4) 페이지 호환 컨트롤러 (래퍼)
# -----------------------------------------------------------------------------
class ShopeeCreator:
    """
    - __init__(sheet_url, ref_url=None, cover_base_url=None, details_base_url=None,
               option_base_url=None, shop_code=None, **kwargs)
    - run() -> bool
    - get_tem_values_csv() -> Optional[bytes]
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
        self.details_base_url = details_base_url
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
                self._impl = None

    def run(self) -> bool:
        if self._impl is None:
            raise ImportError(
                "creation_steps 모듈 로드 실패. utils_common 경로/파일 존재 및 본 컨트롤러(v2) 적용을 확인하세요."
            ) from _last_import_error
        return bool(self._impl.run())

    def get_tem_values_csv(self) -> Optional[bytes]:
        # impl이 제공하면 그대로 사용
        if self._impl and hasattr(self._impl, "get_tem_values_csv"):
            try:
                return self._impl.get_tem_values_csv()
            except Exception:
                pass
        # 폴백: 직접 시트에서 읽어 CSV 생성
        try:
            import gspread
            gc = authorize_gspread()
            sh = gc.open_by_key(extract_sheet_id(self.sheet_url))
            ws = sh.worksheet(get_tem_sheet_name())
            values = ws.get_all_values() or []
            if not values:
                return None
            buf = io.StringIO()
            csv.writer(buf).writerows(values)
            return buf.getvalue().encode("utf-8-sig")
        except Exception:
            return None
