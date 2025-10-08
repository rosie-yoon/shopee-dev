# image_compose/app.py
from __future__ import annotations
from pathlib import Path
import io
import zipfile

import streamlit as st
from PIL import Image as PILImage  # (중요) 전부 이 별칭으로 통일

# 상대 임포트: image_compose/composer_utils.py 가 같은 폴더에 있어야 합니다.
# 패키지 인식을 위해 image_compose/__init__.py 도 반드시 존재해야 합니다.
from .composer_utils import compose_one_bytes, SHADOW_PRESETS, has_useful_alpha, ensure_rgba

BASE_DIR = Path(__file__).resolve().parent


# ---------- Streamlit 호환 이미지 렌더 ----------
def _st_image(img, **kwargs):
    """Streamlit 버전별 image 인자 호환: use_container_width(신) ↔ use_column_width(구) ↔ 키워드 없이."""
    try:
        return st.image(img, use_container_width=True, **kwargs)
    except TypeError:
        kwargs.pop("use_container_width", None)
        try:
            return st.image(img, use_column_width=True, **kwargs)
        except TypeError:
            kwargs.pop("use_column_width", None)
            return st.image(img, **kwargs)


# ---------- Streamlit이 받을 수 있는 이미지 타입으로 정규화 ----------
def _to_streamlit_image_input(x):
    """Streamlit이 받는 타입으로 정규화: PIL.Image | bytes | bytearray | BytesIO | 파일경로"""
    if x is None:
        return None
    if isinstance(x, (bytes, bytearray)):
        return x
    if isinstance(x, PILImage.Image):
        return x
    if hasattr(x, "getvalue"):  # BytesIO 등
        try:
            return x.getvalue()
        except Exception:
            pass
    if hasattr(x, "read"):      # 파일 객체
        try:
            return x.read()
        except Exception:
            pass
    if isinstance(x, (str, Path)) and Path(x).exists():
        return str(x)
    return None


def run():
    # (주의) set_page_config는 래퍼(pages/1_Cover Image.py)에서 호출
    st.title("Cover Image")
    # st.caption("build tag: cover-live-preview @ 16:xx KST")  # 필요시 버전 확인용

    # ---- 세션 상태 초기화 ----
    def init_state():
        defaults = {
            "anchor": "center",
            "resize_ratio": 1.0,       # 기본 100%
            "shadow_preset": "off",
            "item_uploader_key": 0,
            "template_uploader_key": 0,
            "preview_img": None,       # bytes (단일 미리보기)
            "preview_list": [],        # bytes 리스트 (다중 미리보기)
            "preview_idx": 0,          # 다중 미리보기 인덱스
            "preview_sig": None,       # 현재 미리보기 입력/옵션의 시그니처 (라이브 갱신용)
            "download_info": None,     # {"buffer": BytesIO, "count": int}
        }
        for k, v in defaults.items():
            st.session_state.setdefault(k, v)

    init_state()
    ss = st.session_state

    # ---------- 유틸: 파일/옵션 시그니처 ----------
    def _files_fingerprint(files):
        """UploadedFile 리스트를 간단한 해시(이름+크기)로 요약."""
        if not files:
            return []
        fps = []
        for f in files:
            try:
                name = getattr(f, "name", "noname")
                # 일부 환경에서 UploadedFile에 size 속성이 없을 수 있음 → getbuffer().nbytes로 보완
                try:
                    size = getattr(f, "size", None)
                except Exception:
                    size = None
                if size is None:
                    try:
                        size = len(f.getvalue())
                    except Exception:
                        size = 0
                fps.append((name, int(size)))
            except Exception:
                fps.append(("unknown", 0))
        return fps

    def _options_signature():
        return (ss.anchor, float(ss.resize_ratio), ss.shadow_preset)

    # ---- 합성 미리보기 (첫 1장) ----
    def update_preview(item_files, template_files):
        """업로드된 첫 번째 아이템/템플릿으로 미리보기 1장을 만들어 ss.preview_img(bytes)에 저장."""
        ss.preview_img = None
        if not item_files or not template_files:
            return

        # UploadedFile → bytes → BytesIO → PILImage (포인터 이슈 방지)
        item_bytes = item_files[0].getvalue()
        tpl_bytes  = template_files[0].getvalue()
        item_img = PILImage.open(io.BytesIO(item_bytes))
        template_img = PILImage.open(io.BytesIO(tpl_bytes))

        # 투명 배경 체크
        if not has_useful_alpha(ensure_rgba(item_img)):
            try:
                st.toast("투명 배경이 아닌 Item은 미리보기에서 제외됩니다.", icon="⚠️")
            except Exception:
                st.warning("투명 배경이 아닌 Item은 미리보기에서 제외됩니다.")
            return

        opts = {
            "anchor": ss.anchor,
            "resize_ratio": ss.resize_ratio,
            "shadow_preset": ss.shadow_preset,
            "out_format": "PNG",   # 미리보기는 PNG 고정
        }
        result = compose_one_bytes(item_img, template_img, **opts)
        if not result:
            ss.preview_img = None
            return

        # compose_one_bytes → (BytesIO, ext) 형태 가정
        data = None
        if isinstance(result, tuple) and len(result) >= 1:
            buf = result[0]
            if hasattr(buf, "getvalue"):
                data = buf.getvalue()
            elif isinstance(buf, (bytes, bytearray)):
                data = bytes(buf)
        elif isinstance(result, PILImage.Image):
            tmp = io.BytesIO()
            result.save(tmp, format="PNG")
            data = tmp.getvalue()
        elif hasattr(result, "getvalue"):
            data = result.getvalue()
        elif isinstance(result, (bytes, bytearray)):
            data = bytes(result)
        ss.preview_img = data

    # ---- 다중 미리보기 생성 (자동/실시간) ----
    def generate_preview_list(item_files, template_files, max_count: int = 12):
        """업로드된 아이템 × 템플릿 조합으로 최대 max_count장의 미리보기(bytes) 생성."""
        ss.preview_list = []
        ss.preview_idx = 0

        if not item_files or not template_files:
            return

        opts_base = {
            "anchor": ss.anchor,
            "resize_ratio": ss.resize_ratio,
            "shadow_preset": ss.shadow_preset,
            "out_format": "PNG",
        }

        out = []
        # 아이템 × 템플릿 순회 (과도한 생성 방지 위해 max_count 제한)
        for item_file in item_files:
            if len(out) >= max_count:
                break
            try:
                item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                if not has_useful_alpha(ensure_rgba(item_img)):
                    continue
            except Exception:
                continue

            for template_file in template_files:
                if len(out) >= max_count:
                    break
                try:
                    template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
                except Exception:
                    continue

                result = compose_one_bytes(item_img, template_img, **opts_base)
                if not result:
                    continue

                buf = result[0]
                data = buf.getvalue() if hasattr(buf, "getvalue") else (bytes(buf) if isinstance(buf, (bytes, bytearray)) else None)
                if data:
                    out.append(data)

        ss.preview_list = out

    # ---- 배치 합성 & Zip 생성 ----
    def run_batch_composition(item_files, template_files, fmt, quality, shop_variable):
        zip_buf = io.BytesIO()
        count = 0
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for item_file in item_files:
                # 매 루프마다 새로 열기(포인터 이슈 방지)
                item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                if not has_useful_alpha(ensure_rgba(item_img)):
                    continue

                for template_file in template_files:
                    template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
                    opts = {
                        "anchor": ss.anchor,
                        "resize_ratio": ss.resize_ratio,
                        "shadow_preset": ss.shadow_preset,
                        "out_format": fmt,     # "JPEG" 등
                        "quality": quality,    # 100 등
                    }
                    result = compose_one_bytes(item_img, template_img, **opts)
                    if result:
                        img_buf, ext = result  # img_buf: BytesIO
                        item_name = Path(item_file.name).stem
                        shop_var = shop_variable if shop_variable else Path(template_file.name).stem
                        filename = f"{item_name}_C_{shop_var}.{ext}"
                        zf.writestr(filename, img_buf.getvalue())
                        count += 1

        zip_buf.seek(0)
        return zip_buf, count

    # ---- 다운로드 다이얼로그 ----
    @st.dialog("출력 설정")
    def show_save_dialog(item_files, template_files):
        st.caption("설정 후 '다운로드'를 누르면 Zip 파일이 생성됩니다.")
        fmt = "JPEG"   # 고정
        quality = 100  # 고정
        st.caption("저장 포맷: JPG(.jpg)")

        shop_variable = st.text_input(
            "Shop 구분값 (선택)",
            key="dialog_shop_var",
            help="입력 시 'Item_C_구분값.jpg' 형식으로 저장됩니다.",
        )

        if st.button("다운로드", type="primary", use_container_width=True, key="btn_confirm_download"):

            with st.spinner("이미지를 생성 중입니다..."):
                zip_buf, count = run_batch_composition(
                    item_files, template_files, fmt, quality, shop_variable
                )
            if count > 0:
                ss.download_info = {"buffer": zip_buf, "count": count}
                st.rerun()  # 다운로드 버튼 반영 위해 1회만 재실행 (일상 상호작용의 깜빡임과 무관)
            else:
                st.warning("생성된 이미지가 없습니다. Item이 투명 배경을 가졌는지 확인해주세요.")

    # ---- UI 레이아웃 ----
    left, right = st.columns([1, 1])

    with left:
        st.subheader("이미지 업로드")
        item_files = st.file_uploader(
            "1. Item 이미지 업로드 (누끼 딴 이미지, PNG/WEBP)",
            type=["png", "webp"],
            accept_multiple_files=True,
            key=f"item_{ss.item_uploader_key}",
        )
        if st.button("아이템 리스트 삭제"):
            ss.item_uploader_key += 1
            # 버튼 자체가 rerun을 유발 → rerun 호출 불필요

        template_files = st.file_uploader(
            "2. Template 이미지 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key=f"tpl_{ss.template_uploader_key}",
        )
        if st.button("템플릿 삭제"):
            ss.template_uploader_key += 1

    with right:
        st.subheader("이미지 설정")
        c1, c2, c3 = st.columns(3)
        c1.selectbox(
            "배치 위치",
            ["center", "top", "bottom", "left", "right",
             "top-left", "top-right", "bottom-left", "bottom-right"],
            key="anchor",
        )

        # ----- 리사이즈 (확대 포함 + 100% 기본) -----
        resize_options = [1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7]
        if "resize_ratio" not in st.session_state:
            st.session_state["resize_ratio"] = 1.0
        current = st.session_state["resize_ratio"]
        idx = resize_options.index(current) if current in resize_options else resize_options.index(1.0)
        st.session_state["resize_ratio"] = c2.selectbox(
            "리사이즈",
            resize_options,
            index=idx,
            format_func=lambda x: f"{int(round(x*100))}%"
        )

        c3.selectbox("그림자 프리셋", list(SHADOW_PRESETS.keys()), key="shadow_preset")

        # ---- 프리뷰 고정 슬롯(깜빡임 최소화) ----
        preview_header = st.empty()
        preview_nav    = st.empty()
        preview_image  = st.empty()
        preview_hint   = st.empty()

        preview_header.subheader("미리보기")

        # ---- 실시간 적용: 입력/옵션 시그니처를 기준으로 자동 갱신 ----
        cur_sig = (tuple(_files_fingerprint(item_files)),
                   tuple(_files_fingerprint(template_files)),
                   _options_signature())

        if cur_sig != ss.preview_sig:
            # 단일 프리뷰 갱신
            update_preview(item_files, template_files)
            # 다중 프리뷰 갱신
            generate_preview_list(item_files, template_files)
            ss.preview_sig = cur_sig

        # ---- 미리보기 네이게이션 / 렌더 ----
        if ss.preview_list:
            n = len(ss.preview_list)
            with preview_nav.container():
                cprev, ccenter, cnext = st.columns([1, 5, 1])
                with cprev:
                    if st.button("◀", use_container_width=True, key="nav_prev"):
                        ss.preview_idx = (ss.preview_idx - 1) % n
                with ccenter:
                    st.write(f"**{ss.preview_idx + 1} / {n}**")
                with cnext:
                    if st.button("▶", use_container_width=True, key="nav_next"):
                        ss.preview_idx = (ss.preview_idx + 1) % n

            current_bytes = ss.preview_list[ss.preview_idx]
            preview_image.image(
                _to_streamlit_image_input(current_bytes),
                caption=f"미리보기 #{ss.preview_idx + 1}",
                use_column_width=True,  # 구/신버전 모두 안전
            )
            preview_hint.empty()
        else:
            # 단일(업로드 직후) 미리보기 또는 힌트
            img_in = _to_streamlit_image_input(ss.preview_img)
            if img_in is not None:
                preview_image.image(img_in, caption="미리보기 (단일)", use_column_width=True)
                preview_hint.caption("업로드/설정 변경 시 자동으로 여러 장 미리보기를 생성합니다.")
            else:
                preview_image.empty()
                preview_hint.caption("파일을 업로드하면 미리보기가 표시됩니다.")

        # ---- 실행/다운로드 (버튼 텍스트 변경) ----
        st.button(
            "다운로드",
            type="primary",
            use_container_width=True,
            key="btn_open_save_dialog",
            disabled=(not item_files or not template_files),
            on_click=lambda: show_save_dialog(item_files, template_files),
        )

    # ---- 다운로드 버튼 (다이얼로그 완료 후 노출) ----
    if ss.get("download_info"):
        info = ss.download_info
        st.success(f"총 {info['count']}개의 이미지 생성 완료!")
        st.download_button(
            "Zip 다운로드",
            info["buffer"],
            file_name="Thumb_Craft_Results.zip",
            mime="application/zip",
            use_container_width=True,
        )
        ss.download_info = None  # 초기화


if __name__ == "__main__":
    run()
