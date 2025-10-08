# pages/2_Copy Template.py
from __future__ import annotations
from pathlib import Path
import sys
import importlib
import importlib.util
import types
import traceback
import streamlit as st

st.set_page_config(page_title="Copy Template", layout="wide")

# 프로젝트 루트(= pages 상위) 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ------------------------------------------------------------
# 1) utils_common 로드 (패키지/루트 어디에 있든 쓰기 위함)
# ------------------------------------------------------------
def _load_utils_common():
    try:
        from item_uploader import utils_common as uc  # 패키지 구조
        return uc
    except Exception:
        return importlib.import_module("utils_common")  # 납작(flat) 구조

uc = _load_utils_common()
extract_sheet_id = getattr(uc, "extract_sheet_id")
sheet_link       = getattr(uc, "sheet_link")
get_env          = getattr(uc, "get_env")
save_env_value   = getattr(uc, "save_env_value")
load_env         = getattr(uc, "load_env")

# ------------------------------------------------------------
# 2) app.run() 확보: 정식 임포트 → 실패 시 shim 패키지로 로드
# ------------------------------------------------------------
def _load_item_uploader_app_run():
    # (A) 정상 패키지 구조일 때
    try:
        from item_uploader.app import run as _run  # type: ignore
        return _run
    except Exception:
        pass

    # (B) 납작(flat) 구조 대응: shim 패키지 생성 후 각 모듈을 item_uploader.* 로 로드
    candidate_files = {
        "utils_common": ROOT / "utils_common.py",
        "upload_apply": ROOT / "upload_apply.py",
        "main_controller": ROOT / "main_controller.py",
        "automation_steps": ROOT / "automation_steps.py",
    }
    app_path_pkg  = ROOT / "item_uploader" / "app.py"
    app_path_flat = ROOT / "app.py"
    app_path = app_path_pkg if app_path_pkg.exists() else app_path_flat
    if not app_path.exists():
        raise FileNotFoundError(f"app.py를 찾지 못했습니다: {app_path_pkg} 또는 {app_path_flat}")

    if "item_uploader" not in sys.modules:
        pkg = types.ModuleType("item_uploader")
        pkg.__path__ = [str(ROOT)]
        sys.modules["item_uploader"] = pkg

    for mod_name, path in candidate_files.items():
        if path.exists():
            full_name = f"item_uploader.{mod_name}"
            if full_name in sys.modules:
                continue
            spec = importlib.util.spec_from_file_location(full_name, str(path))
            mod = importlib.util.module_from_spec(spec)  # type: ignore
            sys.modules[full_name] = mod
            assert spec and spec.loader
            spec.loader.exec_module(mod)  # type: ignore

    full_name = "item_uploader.app"
    spec = importlib.util.spec_from_file_location(full_name, str(app_path))
    app_mod = importlib.util.module_from_spec(spec)  # type: ignore
    app_mod.__package__ = "item_uploader"
    sys.modules[full_name] = app_mod
    assert spec and spec.loader
    spec.loader.exec_module(app_mod)  # type: ignore

    run_fn = getattr(app_mod, "run", None)
    if not callable(run_fn):
        raise AttributeError("item_uploader.app.run 함수를 찾지 못했습니다.")
    return run_fn

# ------------------------------------------------------------
# 3) 사이드바: 필수 환경 설정
#    - 운영 시트 URL (사용자 입력 → .env 저장)
#    - Reference 시트: **secrets에서만 읽기(표시만)**, 사용자 입력/저장 없음
#    - 이미지 호스팅 URL (사용자 입력 → .env 저장)
# ------------------------------------------------------------
with st.sidebar:
    st.subheader("⚙️ 초기 설정")

    # 운영/이미지 값은 기존 로직대로 .env 저장 대상
    cur_sid  = get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
    cur_host = get_env("IMAGE_HOSTING_URL")

    # Reference는 secrets에서만 읽음 (둘 중 하나 키가 있을 수 있음)
    ref_id = get_env("REFERENCE_SPREADSHEET_ID") or get_env("REFERENCE_SHEET_KEY")
    ref_url_display = sheet_link(ref_id) if ref_id else ""

    with st.form("settings_form_copy_template"):
        sheet_url = st.text_input(
            "Google Sheets URL (운영 시트)",
            value=(sheet_link(cur_sid) if cur_sid else ""),
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        # ✅ Reference는 사용자 입력 ❌, secrets에서 읽은 값을 **읽기 전용**으로만 표시
        st.text_input(
            "Reference Sheets (secrets에서 로드됨)",
            value=(ref_url_display or "🔒 secrets에 설정 필요: REFERENCE_SPREADSHEET_ID 또는 REFERENCE_SHEET_KEY"),
            disabled=True,
        )
        image_host = st.text_input(
            "Image Hosting URL",
            value=cur_host or "",
            placeholder="예: https://example.com/COVER/"
        )

        submitted = st.form_submit_button("저장")
        if submitted:
            sid = extract_sheet_id(sheet_url)
            if not sid:
                st.error("운영 시트 URL을 올바르게 입력해주세요.")
            elif not image_host or not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요.")
            else:
                # .env 업데이트 (app.run은 실행 시 load_env()로 읽음)
                save_env_value("GOOGLE_SHEETS_SPREADSHEET_ID", sid)
                save_env_value("IMAGE_HOSTING_URL", image_host)
                st.success("설정 저장 완료 (.env 업데이트).")

    if not ref_id:
        st.warning("Reference Sheets ID가 secrets에 없습니다. 배포 환경의 Streamlit secrets에 "
                   "`REFERENCE_SPREADSHEET_ID` 또는 `REFERENCE_SHEET_KEY`를 설정해주세요.")

# ------------------------------------------------------------
# 4) 본문: 실행 버튼 → item_uploader.app.run()
# ------------------------------------------------------------
st.title("Copy Template")
st.caption("BASIC / MEDIA / SALES 업로드 → 템플릿 생성 자동화")

if st.button("🚀 템플릿 복사 실행", type="primary", use_container_width=True):
    try:
        # 실행 시점에 환경 로드 (secrets/.env)
        load_env()
        run = _load_item_uploader_app_run()
        run()  # Streamlit UI (업로드/자동화/다운로드) 실행
    except Exception as e:
        st.error("실행 중 오류가 발생했습니다. 아래 상세를 확인하세요.")
        st.exception(e)
        st.code(traceback.format_exc())
