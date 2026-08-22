#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 proxy-switch 图标：圆角矩形蓝色底 + 白色电源符号（纯标准库手写 PNG）"""
import struct
import zlib
import math
import os


def build_png(size, path):
    bg = (30, 100, 220)      # 蓝色
    fg = (255, 255, 255)     # 白色电源符号
    radius = int(size * 0.22)
    c = size / 2
    r = size * 0.28
    t = max(1.5, size * 0.05)

    def in_power(x, y):
        # 竖线：从圆环顶部缺口向上延伸
        if abs(x - c) <= t and (c - r - size * 0.18) <= y <= (c - r + t):
            return True
        # 圆环：顶部留约 24 度缺口
        d = math.hypot(x - c, y - c)
        if abs(d - r) <= t:
            angle = abs(math.degrees(math.atan2(y - c, x - c)))
            if abs(angle - 90) > 12:
                return True
        return False

    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            alpha = 255
            cx, cy = min(x, size - 1 - x), min(y, size - 1 - y)
            if cx < radius and cy < radius:
                dx, dy = radius - cx, radius - cy
                if dx * dx + dy * dy > radius * radius:
                    alpha = 0
            r_, g_, b_ = bg
            if alpha and in_power(x, y):
                r_, g_, b_ = fg
            row += bytes((r_, g_, b_, alpha))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        c += struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)
        return c

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    print(f"generated {path} ({size}x{size})")


base = "/vol1/1000/OpenClaw项目/proxy-switch"
build_png(64, f"{base}/ICON.PNG")
build_png(256, f"{base}/ICON_256.PNG")
build_png(64, f"{base}/app/ui/images/icon_64.png")
build_png(256, f"{base}/app/ui/images/icon_256.png")
