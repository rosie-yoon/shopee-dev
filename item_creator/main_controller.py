# -*- coding: utf-8 -*-
"""
main_controller.py (A안 v3: creation_steps/ utils_common 로딩을 근본적으로 안정화)

- 페이지(3_Create Items.py)와 인터페이스 100% 호환:
  class ShopeeCreator(...); run()->bool; get_tem_values_csv()->Optional[bytes]
- utils_common / creation_steps 로딩 전략 (배포/로컬 모두 견고):
  1) repo root, item_creator 디렉터리를 sys.path에 선주입
  2) utils_common: 로컬 import → 파일 직접 로드 → item_creator → item_uploader
  3) creation_steps: item_creator.creation_steps → creation_steps → 파일 직접 로드
  4) 레거시 임포트(item_uploader.*)는 shim으로 흡수
"""

from __future__ import annotations
from typing import Optional
import sys, types, io, csv
from pathlib import Path
import importlib, importlib.util

# -----------------------------------------------------------------------------
# 0) 경로 선정렬: repo root / item_creator 를 sys.path 선주입
# -----------------------------------------------------------------------------
_THIS = Path(__file__).resolve()                           # .../item_creator/main_controller.py
_ROOT = _THIS.parents[1]                                   # repo root
_ITEM_CREATOR_DIR = _THIS.parent                           # .../item_creator

for _p in (str(_ROOT), str(_ITEM_CREATOR_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# -----------------------------------------------------------------------------
# 1) utils_common 안전 임포트 (로컬 > 파일 직접 로드 > item_creator > item_uploader)
# -----------------------------------------------------------------------------
_last_import_error = None
authorize_gspread = None
extract_sheet_id = None
get_tem_sheet_name = None

def _load_module_from_path(modname: str, path: Path):
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(modname, path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod

utils_mod = None

# (a) 로컬 이름 임포트 시도
try:
    utils_mod = importlib.import_module("utils_common")
except Exception as e:
    _last_import_error = e

# (b) 파일 직접 로드 (repo root/utils_common.py)
if utils_mod is None:
    try:
        utils_mod = _load_module_from_path("utils_common", _ROOT / "utils_common.py")
    except Exception as e:
        _last_import_error = e

# (c) item_creator.utils_common
if utils_mod is None:
    try:
        utils_mod = importlib.import_module("item_creator.utils_common")  # type: ignore
    except Exception as e:
        _last_import_error = e

# (d) item_uploader.utils_common
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
# 2) shim: 레거시 경로(item_uploader.*)를 로컬 utils로 매핑
# -----------------------------------------------------------------------------
# - creation_steps 내부가 과거 경로를 import해도 통과되도록 보정
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
sys.modules["item_creator.utils_common"] = utils_mod

# -----------------------------------------------------------------------------
# 3) creation_steps 안전 임포트
#    - 1순위: item_creator.creation_steps
#    - 2순위: creation_steps (repo root)
#    - 3순위: 파일 직접 로드 (root/item_creator 하위)
# -----------------------------------------------------------------------------
_ImplCreator = None
_import_err = None

def _try_import_creation_steps():
    # 1) 패키지 경로 우선
    try:
        return importlib.import_module("item_creator.creation_steps")
    except Exception as e:
        nonlocal _import_err
        _import_err = e
    # 2) 루트 모듈
    try:
        return importlib.import_module("creation_steps")
    except Exception as e:
        _import_err = e
    # 3) 파일 직접 로드 (item_creator/creation_steps.py → root/creation_steps.py 순)
    for path in (_ITEM_CREATOR_DIR / "creation_steps.py", _ROOT / "creation_steps.py"):
        try:
            mod = _load_module_from_path("creation_steps", path)
            if mod:
                return mod
        except Exception as e:
            _import_err = e
    return None

_steps_mod = _try_import_creation_steps()
if _steps_mod is not None:
    _ImplCreator = getattr(_steps_mod, "ShopeeCreator", None)

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
                "creation_steps 모듈 로드 실패. "
                "다음을 확인하세요: (1) item_creator/creation_steps.py 존재 여부 "
                "(2) utils_common 경로/파일 존재 (3) 본 컨트롤러(v3)로 교체 완료"
            ) from _import_err or _last_import_error
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
