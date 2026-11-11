"""Verify the exact installed DejaVu faces needed by POD test rendering."""
from pathlib import Path

FACES = {
    'DejaVu Sans': ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'DejaVuSans-Oblique.ttf', 'DejaVuSans-BoldOblique.ttf'),
    'DejaVu Sans Mono': ('DejaVuSansMono.ttf', 'DejaVuSansMono-Bold.ttf', 'DejaVuSansMono-Oblique.ttf', 'DejaVuSansMono-BoldOblique.ttf'),
    'DejaVu Serif': ('DejaVuSerif.ttf', 'DejaVuSerif-Bold.ttf', 'DejaVuSerif-Italic.ttf', 'DejaVuSerif-BoldItalic.ttf'),
}
ROOT = Path('/usr/share/fonts/truetype/dejavu')


def fonts_ready(loader=None):
    try:
        if loader is None:
            from PIL import ImageFont
            loader = ImageFont.truetype
        for family, names in FACES.items():
            for name in names:
                font = loader(str(ROOT / name), 16)
                if font.getname()[0] != family:
                    return False
                box = font.getmask('POD 0123').getbbox()
                if box is None or box[2] <= box[0] or box[3] <= box[1]:
                    return False
        return True
    except Exception:
        return False


if __name__ == '__main__':
    raise SystemExit(0 if fonts_ready() else 1)
