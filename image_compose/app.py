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
    # (중요) set_page_config는 래퍼(pages/1_Cover Image.py)에서만 호출
    st.title("Cover Image")

    # ---- 세션 상태 초기화 ----
    def init_state():
        defaults = {
            "anchor": "center",
            "resize_ratio": 1.0,
            "shadow_preset": "off",
            "item_uploader_key": 0,
            "template_uploader_key": 0,
            "preview_img": None,     # bytes
            "download_info": None,   # {"buffer": BytesIO, "count": int}
        }
        for k, v in defaults.items():
            st.session_state.setdefault(k, v)

    init_state()
    ss = st.session_state

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

        if st.button("다운로드", type="primary", use_container_width=True):
            with st.spinner("이미지를 생성 중입니다..."):
                zip_buf, count = run_batch_composition(
                    item_files, template_files, fmt, quality, shop_variable
                )
            if count > 0:
                ss.download_info = {"buffer": zip_buf, "count": count}
                st.rerun()
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
            st.rerun()

        template_files = st.file_uploader(
            "2. Template 이미지 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key=f"tpl_{ss.template_uploader_key}",
        )
        if st.button("템플릿 삭제"):
            ss.template_uploader_key += 1
            st.rerun()

    with right:
        st.subheader("이미지 설정")
        c1, c2, c3 = st.columns(3)
        c1.selectbox(
            "배치 위치",
            ["center", "top", "bottom", "left", "right",
             "top-left", "top-right", "bottom-left", "bottom-right"],
            key="anchor",
        )
        c2.selectbox(
            "리사이즈",
            [1.0, 0.9, 0.8, 0.7, 0.6],
            format_func=lambda x: f"{int(x*100)}%" if x < 1.0 else "없음",
            key="resize_ratio",
        )
        c3.selectbox("그림자 프리셋", list(SHADOW_PRESETS.keys()), key="shadow_preset")

        # 설정 변경 시 미리보기 업데이트
        update_preview(item_files, template_files)

        st.subheader("미리보기")
        img_in = _to_streamlit_image_input(ss.preview_img)
        if img_in is not None:
            st.image(img_in, caption="미리보기 (첫번째 조합)", use_container_width=True)
        else:
            st.caption("파일을 업로드하면 미리보기가 표시됩니다.")

        st.button(
            "생성하기",
            type="primary",
            use_container_width=True,
            disabled=(not item_files or not template_files),
            on_click=lambda: show_save_dialog(item_files, template_files),
        )

    # ---- 다운로드 버튼 ----
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
