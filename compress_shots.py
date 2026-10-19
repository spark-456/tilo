import sys
from pathlib import Path

from PIL import Image


def optimize_directory(dir_path: str):
    p = Path(dir_path)
    if not p.exists():
        print(f"Directory {dir_path} does not exist.")
        return
    for img_path in sorted(p.glob("*.png")):
        size_bytes = img_path.stat().st_size
        print(f"{img_path.name}: {size_bytes / 1024:.1f} KB")
        if size_bytes > 290 * 1024:
            print(f"  Optimizing {img_path.name}...")
            im = Image.open(img_path)
            for colors in (256, 160, 128, 96, 64):
                quantized = im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
                quantized.save(img_path, optimize=True)
                new_size = img_path.stat().st_size
                if new_size <= 290 * 1024:
                    break
            print(f"  -> {new_size / 1024:.1f} KB")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "docs/assets/readme"
    optimize_directory(target)
