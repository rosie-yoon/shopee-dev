# scripts/normalize_icons.py
from PIL import Image
from pathlib import Path

SRC_DIR = Path("assets/icons")
DST_DIR = SRC_DIR  # 같은 폴더에 저장
CANVAS = 144       # @3x
PADDING = 8        # 글로우 여유 (1x 4~8px 기준 -> @3x에선 8~24px)

def normalize_one(src_path: Path, out_name: str):
    img = Image.open(src_path).convert("RGBA")
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0,0,0,0))

    target = CANVAS - 2*PADDING
    ratio = min(target / img.width, target / img.height)
    new_size = (max(1, int(img.width*ratio)), max(1, int(img.height*ratio)))
    scaled = img.resize(new_size, Image.LANCZOS)

    x = (CANVAS - scaled.width) // 2
    y = (CANVAS - scaled.height) // 2
    canvas.paste(scaled, (x, y), scaled)
    out_path = DST_DIR / out_name
    canvas.save(out_path, optimize=True)
    print("saved:", out_path)

def main():
    mapping = {
        "cover.png":  "cover@3x.png",
        "copy.png":   "copy@3x.png",
        "create.png": "create@3x.png",
    }
    for k, v in mapping.items():
        src = SRC_DIR / k
        if src.exists():
            normalize_one(src, v)
        else:
            print("skip (not found):", src)

if __name__ == "__main__":
    main()
