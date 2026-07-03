#!/usr/bin/env python
"""
generate_cards.py — 使用 Pillow 生成全套 52 张扑克牌 PNG + 牌背

设计风格：现代简约，象牙白底，清晰角标，几何人头牌，规则花纹牌背。
输出目录：static/img/cards/
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ======================== 配置 ========================
CARD_W, CARD_H = 250, 350  # 像素
OUT_DIR = Path("static/img/cards")

# 颜色
BG_CREAM = (247, 246, 241)  # 象牙白 #F7F6F1
RED = (211, 47, 47)  # #D32F2F
BLACK = (33, 33, 33)  # #212121
GOLD = (212, 168, 67)  # 金色装饰
BLUE_DARK = (30, 60, 100)
WHITE = (255, 255, 255)
CARD_BACK_COLOR = (26, 25, 25)  # #1A1919

# 花色
SUITS = {
    "S": {"symbol": "♠", "color": BLACK, "name": "spades"},
    "H": {"symbol": "♥", "color": RED, "name": "hearts"},
    "D": {"symbol": "♦", "color": RED, "name": "diamonds"},
    "C": {"symbol": "♣", "color": BLACK, "name": "clubs"},
}

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# ======================== 字体 ========================
def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """查找可用字体，优先使用 Georgia / Times New Roman。"""
    candidates = []
    if bold:
        candidates = ["georgiab.ttf", "timesbd.ttf", "arialbd.ttf", "seguisb.ttf"]
    else:
        candidates = ["georgia.ttf", "times.ttf", "arial.ttf", "segoeui.ttf"]

    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    # 回退到默认字体
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


# 预加载常用字号
FONT_RANK_CORNER = _find_font(28, bold=True)
FONT_SUIT_CORNER = _find_font(18)
FONT_PIP = _find_font(36)  # 点数图案
FONT_PIP_SM = _find_font(24)  # 小号点数图案
FONT_FACE_LABEL = _find_font(60, bold=True)


# ======================== 工具函数 ========================

def rounded_rect_mask(w: int, h: int, r: int) -> Image.Image:
    """生成圆角矩形 mask（用于裁剪卡片外形）。"""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    return mask


def apply_rounded_corners(im: Image.Image, r: int = 14) -> Image.Image:
    """给图片应用圆角裁剪。"""
    mask = rounded_rect_mask(im.width, im.height, r)
    im.putalpha(mask)
    return im


def draw_corner(draw: ImageDraw.ImageDraw, x: int, y: int, rank: str, suit: str, color: tuple):
    """绘制角标：点数 + 花色（小号）。"""
    # 点数
    draw.text((x, y), rank, fill=color, font=FONT_RANK_CORNER)
    # 花色（紧挨点数下方）
    bbox = draw.textbbox((x, y), rank, font=FONT_RANK_CORNER)
    rank_h = bbox[3] - bbox[1]
    draw.text((x + 2, y + rank_h - 6), SUITS[suit]["symbol"], fill=color, font=FONT_SUIT_CORNER)


# ======================== 点数图案布局 ========================

# 每种 rank 的点数布局：(x, y, scale) 归一化坐标 (0~1)，scale 为字号缩放
# 点数图案从 2 到 10，A 和 人头牌单独处理

def _p(nx: float, ny: float, scale: float = 1.0) -> tuple[float, float, float]:
    """将归一化坐标转为 tool 数据格式。"""
    return (nx, ny, scale)


PIP_LAYOUTS: dict[str, list[tuple[float, float, float]]] = {
    "2": [
        (0.5, 0.78, 1.0),
        (0.5, 0.22, 1.0),
    ],
    "3": [
        (0.5, 0.82, 1.0),
        (0.5, 0.50, 1.0),
        (0.5, 0.18, 1.0),
    ],
    "4": [
        (0.30, 0.78, 1.0), (0.70, 0.78, 1.0),
        (0.30, 0.22, 1.0), (0.70, 0.22, 1.0),
    ],
    "5": [
        (0.30, 0.78, 1.0), (0.70, 0.78, 1.0),
        (0.50, 0.50, 1.0),
        (0.30, 0.22, 1.0), (0.70, 0.22, 1.0),
    ],
    "6": [
        (0.30, 0.78, 1.0), (0.70, 0.78, 1.0),
        (0.30, 0.50, 1.0), (0.70, 0.50, 1.0),
        (0.30, 0.22, 1.0), (0.70, 0.22, 1.0),
    ],
    "7": [
        (0.30, 0.82, 0.85), (0.70, 0.82, 0.85),
        (0.50, 0.58, 0.85),
        (0.30, 0.50, 0.85), (0.70, 0.50, 0.85),
        (0.30, 0.22, 0.85), (0.70, 0.22, 0.85),
    ],
    "8": [
        (0.30, 0.82, 0.80), (0.50, 0.82, 0.80), (0.70, 0.82, 0.80),
        (0.30, 0.50, 0.80), (0.70, 0.50, 0.80),
        (0.30, 0.18, 0.80), (0.50, 0.18, 0.80), (0.70, 0.18, 0.80),
    ],
    "9": [
        (0.26, 0.82, 0.72), (0.50, 0.82, 0.72), (0.74, 0.82, 0.72),
        (0.26, 0.62, 0.72), (0.50, 0.62, 0.72), (0.74, 0.62, 0.72),
        (0.26, 0.42, 0.72), (0.50, 0.42, 0.72), (0.74, 0.42, 0.72),
    ],
    "10": [
        (0.26, 0.83, 0.64), (0.50, 0.83, 0.64), (0.74, 0.83, 0.64),
        (0.26, 0.63, 0.64), (0.50, 0.63, 0.64), (0.74, 0.63, 0.64),
        (0.26, 0.43, 0.64), (0.50, 0.43, 0.64), (0.74, 0.43, 0.64),
    ],
}


def draw_pip_center(draw: ImageDraw.ImageDraw, rank: str, suit: str, color: tuple):
    """绘制中央点数图案布局。"""
    layout = PIP_LAYOUTS.get(rank)
    if not layout:
        return

    margin_x, margin_y = 30, 55
    area_w = CARD_W - 2 * margin_x
    area_h = CARD_H - 2 * margin_y

    suit_char = SUITS[suit]["symbol"]

    for nx, ny, scale in layout:
        cx = margin_x + nx * area_w
        cy = margin_y + ny * area_h
        font_size = int(36 * scale)
        font = _find_font(font_size)
        bbox = draw.textbbox((0, 0), suit_char, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy - th / 2), suit_char, fill=color, font=font)


def draw_ace_center(draw: ImageDraw.ImageDraw, suit: str, color: tuple):
    """Ace：超大中央花色符号。"""
    suit_char = SUITS[suit]["symbol"]
    font = _find_font(140)
    bbox = draw.textbbox((0, 0), suit_char, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((CARD_W / 2 - tw / 2, CARD_H / 2 - th / 2 - 5),
              suit_char, fill=color, font=font)


# ======================== 人头牌插图 ========================

def draw_face_card(draw: ImageDraw.ImageDraw, rank: str, suit: str, color: tuple):
    """绘制人头牌几何肖像（K / Q / J）。"""
    cx, cy = CARD_W / 2, CARD_H / 2

    if rank == "K":
        _draw_king(draw, cx, cy, color)
    elif rank == "Q":
        _draw_queen(draw, cx, cy, color)
    elif rank == "J":
        _draw_jack(draw, cx, cy, color)


def _draw_king(draw, cx, cy, color):
    """K：王冠 + 双剑交叉 + 对称袍子。"""
    # 王冠底座
    crown_y = cy - 70
    # 底座横条
    draw.rounded_rectangle((cx - 40, crown_y + 25, cx + 40, crown_y + 34),
                           radius=4, fill=GOLD, outline=color, width=2)
    # 五个尖顶
    for i, tx in enumerate([-35, -18, 0, 18, 35]):
        peak_h = 22 if i == 2 else 16  # 中间最高
        pts = [(cx + tx - 8, crown_y + 25), (cx + tx, crown_y + 25 - peak_h),
               (cx + tx + 8, crown_y + 25)]
        draw.polygon(pts, fill=GOLD, outline=color, width=2)
    # 尖顶小球
    for i, tx in enumerate([-35, -18, 0, 18, 35]):
        peak_h = 22 if i == 2 else 16
        draw.ellipse((cx + tx - 4, crown_y + 25 - peak_h - 4,
                      cx + tx + 4, crown_y + 25 - peak_h + 4), fill=GOLD, outline=color, width=1)

    # 头部
    draw.ellipse((cx - 22, cy - 25, cx + 22, cy + 15), fill=BG_CREAM, outline=color, width=2)
    # 眼睛
    draw.ellipse((cx - 12, cy - 15, cx - 4, cy - 7), fill=color)
    draw.ellipse((cx + 4, cy - 15, cx + 12, cy - 7), fill=color)
    # 胡须
    draw.arc((cx - 20, cy - 5, cx + 20, cy + 22), start=200, end=340, fill=color, width=2)
    # 口
    draw.line((cx - 6, cy + 5, cx + 6, cy + 5), fill=color, width=1)

    # 身体袍子 — 对称梯形
    robe_pts = [
        (cx - 38, cy + 20), (cx + 38, cy + 20),
        (cx + 50, cy + 95), (cx - 50, cy + 95),
    ]
    draw.polygon(robe_pts, fill=color, outline=color, width=2)

    # 袍子内部白色三角
    inner_pts = [
        (cx - 16, cy + 28), (cx + 16, cy + 28),
        (cx + 32, cy + 90), (cx - 32, cy + 90),
    ]
    draw.polygon(inner_pts, fill=BG_CREAM, outline=color, width=1)

    # 衣领金色 V 形
    collar_pts = [(cx - 16, cy + 24), (cx, cy + 48), (cx + 16, cy + 24)]
    draw.polygon(collar_pts, fill=GOLD, outline=color, width=1)

    # 中央 K 字母
    font = _find_font(28, bold=True)
    draw.text((cx - 12, cy + 35), "K", fill=color, font=font)


def _draw_queen(draw, cx, cy, color):
    """Q：后冠 + 长发 + 对称袍子。"""
    crown_y = cy - 72

    # 后冠弧
    draw.arc((cx - 42, crown_y - 5, cx + 42, crown_y + 28),
             start=180, end=360, fill=GOLD, width=3)
    # 五个尖顶
    for i, tx in enumerate([-32, -16, 0, 16, 32]):
        peak_h = 20 if i == 2 else 14
        pts = [(cx + tx - 7, crown_y + 14), (cx + tx, crown_y + 14 - peak_h),
               (cx + tx + 7, crown_y + 14)]
        draw.polygon(pts, fill=GOLD, outline=color, width=2)
    for i, tx in enumerate([-32, -16, 0, 16, 32]):
        peak_h = 20 if i == 2 else 14
        draw.ellipse((cx + tx - 3, crown_y + 14 - peak_h - 3,
                      cx + tx + 3, crown_y + 14 - peak_h + 3), fill=GOLD, outline=color, width=1)

    # 头部
    draw.ellipse((cx - 20, cy - 22, cx + 20, cy + 15), fill=BG_CREAM, outline=color, width=2)

    # 头发 — 两侧垂下的弧线
    draw.arc((cx - 26, cy - 10, cx - 2, cy + 40), start=120, end=260, fill=color, width=3)
    draw.arc((cx + 2, cy - 10, cx + 26, cy + 40), start=280, end=420, fill=color, width=3)
    # 顶部头发
    draw.arc((cx - 22, cy - 28, cx + 22, cy + 0), start=180, end=360, fill=color, width=3)

    # 眼睛
    draw.ellipse((cx - 11, cy - 12, cx - 3, cy - 5), fill=color)
    draw.ellipse((cx + 3, cy - 12, cx + 11, cy - 5), fill=color)

    # 身体袍子
    robe_pts = [
        (cx - 40, cy + 22), (cx + 40, cy + 22),
        (cx + 55, cy + 95), (cx - 55, cy + 95),
    ]
    draw.polygon(robe_pts, fill=color, outline=color, width=2)
    inner_pts = [
        (cx - 18, cy + 30), (cx + 18, cy + 30),
        (cx + 36, cy + 90), (cx - 36, cy + 90),
    ]
    draw.polygon(inner_pts, fill=BG_CREAM, outline=color, width=1)

    # 项链
    draw.arc((cx - 14, cy + 14, cx + 14, cy + 36), start=220, end=320, fill=GOLD, width=2)
    draw.ellipse((cx - 5, cy + 28, cx + 5, cy + 38), fill=GOLD, outline=color, width=1)

    # 中央 Q 字母
    font = _find_font(28, bold=True)
    draw.text((cx - 12, cy + 40), "Q", fill=color, font=font)


def _draw_jack(draw, cx, cy, color):
    """J：贝雷帽 + 衣领 + 对称服装。"""
    # 贝雷帽
    draw.ellipse((cx - 28, cy - 55, cx + 28, cy - 32), fill=color)
    # 帽顶小圆
    draw.ellipse((cx - 4, cy - 60, cx + 4, cy - 52), fill=color)
    # 帽檐
    draw.arc((cx - 30, cy - 38, cx + 30, cy - 24), start=180, end=360, fill=color, width=3)

    # 头部
    draw.ellipse((cx - 18, cy - 32, cx + 18, cy + 2), fill=BG_CREAM, outline=color, width=2)
    # 眼睛
    draw.ellipse((cx - 10, cy - 22, cx - 2, cy - 15), fill=color)
    draw.ellipse((cx + 2, cy - 22, cx + 10, cy - 15), fill=color)

    # 衣领 V 形
    collar = [(cx - 16, cy + 2), (cx, cy + 24), (cx + 16, cy + 2)]
    draw.polygon(collar, fill=BG_CREAM, outline=color, width=2)
    # 领口装饰
    draw.line((cx - 10, cy + 6, cx, cy + 20), fill=GOLD, width=2)
    draw.line((cx + 10, cy + 6, cx, cy + 20), fill=GOLD, width=2)

    # 身体服装
    body_pts = [
        (cx - 36, cy + 6), (cx + 36, cy + 6),
        (cx + 50, cy + 95), (cx - 50, cy + 95),
    ]
    draw.polygon(body_pts, fill=color, outline=color, width=2)
    inner_pts = [
        (cx - 14, cy + 28), (cx + 14, cy + 28),
        (cx + 30, cy + 90), (cx - 30, cy + 90),
    ]
    draw.polygon(inner_pts, fill=BG_CREAM, outline=color, width=1)

    # 纽扣
    for btn_y in [cy + 44, cy + 58, cy + 72]:
        draw.ellipse((cx - 3, btn_y, cx + 3, btn_y + 6), fill=GOLD, outline=color, width=1)

    # 中央 J 字母
    font = _find_font(28, bold=True)
    draw.text((cx - 9, cy + 30), "J", fill=color, font=font)


# ======================== 牌背 ========================

def generate_card_back() -> Image.Image:
    """生成规则几何花纹牌背。"""
    im = Image.new("RGBA", (CARD_W, CARD_H), BG_CREAM)
    draw = ImageDraw.Draw(im)

    # 底色
    draw.rounded_rectangle((1, 1, CARD_W - 2, CARD_H - 2),
                           radius=14, fill=CARD_BACK_COLOR)

    # 内框
    margin = 12
    draw.rounded_rectangle(
        (margin, margin, CARD_W - margin, CARD_H - margin),
        radius=10, fill=None, outline=WHITE + (60,), width=1
    )

    # 菱形网格花纹
    cell_w, cell_h = 32, 38
    cols = (CARD_W - 2 * margin) // cell_w
    rows = (CARD_H - 2 * margin) // cell_h
    offset_x = (CARD_W - cols * cell_w) / 2
    offset_y = (CARD_H - rows * cell_h) / 2

    for r in range(rows):
        for c in range(cols):
            cx_d = offset_x + (c + 0.5) * cell_w
            cy_d = offset_y + (r + 0.5) * cell_h
            rw, rh = cell_w * 0.32, cell_h * 0.32
            diamond = [
                (cx_d, cy_d - rh),
                (cx_d + rw, cy_d),
                (cx_d, cy_d + rh),
                (cx_d - rw, cy_d),
            ]
            draw.polygon(diamond, fill=WHITE + (40,))

    # 中心椭圆装饰
    center_oval_margin = 50
    draw.ellipse(
        (center_oval_margin, center_oval_margin,
         CARD_W - center_oval_margin, CARD_H - center_oval_margin),
        fill=None, outline=WHITE + (60,), width=2
    )
    draw.ellipse(
        (center_oval_margin + 18, center_oval_margin + 18,
         CARD_W - center_oval_margin - 18, CARD_H - center_oval_margin - 18),
        fill=None, outline=WHITE + (40,), width=1
    )

    # 中心文字
    font = _find_font(16)
    draw.text((CARD_W / 2 - 22, CARD_H / 2 - 10), "♠♥♦♣", fill=WHITE + (50,), font=font)

    return apply_rounded_corners(im)


# ======================== 主生成逻辑 ========================

def generate_card(rank: str, suit: str) -> Image.Image:
    """生成单张牌面。"""
    color = SUITS[suit]["color"]
    suit_char = SUITS[suit]["symbol"]

    # 创建底板
    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # 白色圆角底
    draw.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1),
                           radius=14, fill=BG_CREAM)

    # 内框细线
    border_margin = 7
    draw.rounded_rectangle(
        (border_margin, border_margin,
         CARD_W - border_margin, CARD_H - border_margin),
        radius=10, fill=None, outline=color, width=1
    )

    # 左上角标
    draw_corner(draw, 14, 12, rank, suit, color)

    # 右下角标（旋转 180° — 通过改变绘制位置模拟）
    rank_bbox = draw.textbbox((0, 0), rank, font=FONT_RANK_CORNER)
    suit_bbox = draw.textbbox((0, 0), suit_char, font=FONT_SUIT_CORNER)
    rw = rank_bbox[2] - rank_bbox[0]
    rh = rank_bbox[3] - rank_bbox[1]
    sw = suit_bbox[2] - suit_bbox[0]
    sh = suit_bbox[3] - suit_bbox[1]

    draw.text((CARD_W - 14 - rw, CARD_H - 22 - rh - sh + 6), rank,
              fill=color, font=FONT_RANK_CORNER)
    draw.text((CARD_W - 14 - sw - 2, CARD_H - 22 - sh), suit_char,
              fill=color, font=FONT_SUIT_CORNER)

    # 中央内容
    if rank == "A":
        draw_ace_center(draw, suit, color)
    elif rank in ("J", "Q", "K"):
        draw_face_card(draw, rank, suit, color)
    else:
        draw_pip_center(draw, rank, suit, color)

    return apply_rounded_corners(im)


def main():
    """生成全部 52 张牌 + 牌背。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating playing cards...")

    # 牌背
    back = generate_card_back()
    back_path = OUT_DIR / "back.png"
    back.save(back_path)
    print(f"  ✓ {back_path}")

    # 52 张牌面
    for suit_key, suit_info in SUITS.items():
        for rank in RANKS:
            card = generate_card(rank, suit_key)
            filename = f"{rank}_{suit_key}.png"
            card.save(OUT_DIR / filename)
            print(f"  ✓ {filename}")

    # 也可生成一张 "??" 未知牌（与牌背区分，浅灰色）
    unknown = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    udraw = ImageDraw.Draw(unknown)
    udraw.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1),
                            radius=14, fill=(80, 80, 80))
    udraw.rounded_rectangle((7, 7, CARD_W - 8, CARD_H - 8),
                            radius=10, fill=None, outline=(130, 130, 130), width=2)
    font_q = _find_font(48, bold=True)
    bbox = udraw.textbbox((0, 0), "?", font=font_q)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    udraw.text((CARD_W / 2 - tw / 2, CARD_H / 2 - th / 2), "?", fill=(160, 160, 160), font=font_q)
    unknown = apply_rounded_corners(unknown)
    unknown_path = OUT_DIR / "unknown.png"
    unknown.save(unknown_path)
    print(f"  ✓ unknown.png")

    print(f"\nDone! {len(RANKS) * len(SUITS)} cards + back + unknown → {OUT_DIR}")


if __name__ == "__main__":
    main()
