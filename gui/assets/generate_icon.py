#!/usr/bin/env python3
"""アプリアイコン(icon.ico/icon.png)とスプラッシュ画像(splash.png)を生成する。

style.qssのアクセントカラー(#2563eb系)に合わせた、角丸グラデーション背景+
チェックマークのシンプルなデザイン。素材ファイルはリポジトリにコミットする
（生成にPillowが要るため、再生成が必要な場合だけこのスクリプトを実行する）。
"""
from __future__ import annotations
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent

_BLUE_LIGHT = (59, 130, 246)   # #3b82f6
_BLUE_DARK = (29, 64, 175)     # #1d40af
_WHITE = (255, 255, 255)


def _rounded_gradient_square(size: int, radius_ratio: float = 0.22) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size))
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(_BLUE_LIGHT[0] + (_BLUE_DARK[0] - _BLUE_LIGHT[0]) * t)
        g = int(_BLUE_LIGHT[1] + (_BLUE_DARK[1] - _BLUE_LIGHT[1]) * t)
        b = int(_BLUE_LIGHT[2] + (_BLUE_DARK[2] - _BLUE_LIGHT[2]) * t)
        for x in range(size):
            grad.putpixel((x, y), (r, g, b, 255))

    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    mdraw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)

    img.paste(grad, (0, 0), mask)
    return img


def _draw_checkmark(img: Image.Image) -> None:
    size = img.width
    draw = ImageDraw.Draw(img)
    width = max(2, int(size * 0.09))
    p1 = (size * 0.27, size * 0.53)
    p2 = (size * 0.44, size * 0.70)
    p3 = (size * 0.75, size * 0.33)
    draw.line([p1, p2], fill=_WHITE, width=width, joint="curve")
    draw.line([p2, p3], fill=_WHITE, width=width, joint="curve")
    r = width / 2
    for cx, cy in (p1, p2, p3):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_WHITE)


def make_icon_image(size: int) -> Image.Image:
    img = _rounded_gradient_square(size)
    _draw_checkmark(img)
    return img


def main() -> None:
    base = make_icon_image(256)
    base.save(ASSETS_DIR / "icon.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [make_icon_image(s) for s in sizes]
    images[-1].save(
        ASSETS_DIR / "icon.ico", format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )

    # スプラッシュ用: アイコン+アプリ名の横並び画像
    splash_w, splash_h = 520, 220
    splash = Image.new("RGBA", (splash_w, splash_h), (15, 23, 42, 255))  # #0f172a
    icon_128 = make_icon_image(128)
    splash.paste(icon_128, (48, (splash_h - 128) // 2), icon_128)

    from PIL import ImageFont

    draw = ImageDraw.Draw(splash)
    text_x = 48 + 128 + 32
    try:
        font_title = ImageFont.truetype("segoeuib.ttf", 30)
        font_sub = ImageFont.truetype("segoeui.ttf", 15)
    except OSError:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    draw.text((text_x, splash_h // 2 - 34), "openapi-test-tool", font=font_title, fill=(255, 255, 255, 255))
    draw.text(
        (text_x, splash_h // 2 + 8),
        "API test generator & runner",
        font=font_sub, fill=(148, 163, 184, 255),
    )
    splash.save(ASSETS_DIR / "splash.png")

    print("wrote", ASSETS_DIR / "icon.ico")
    print("wrote", ASSETS_DIR / "icon.png")
    print("wrote", ASSETS_DIR / "splash.png")


if __name__ == "__main__":
    main()
