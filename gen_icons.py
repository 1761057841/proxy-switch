#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 proxy-switch 图标：圆角渐变蓝底 + 白色拨动开关（toggle switch）
纯标准库手写 PNG，4x 超采样抗锯齿。

主题：代理「开关」——拨钮在右 = 开启状态，直观表达应用功能。
"""
import struct
import zlib
import math
import os


def lerp(a, b, t):
    return a + (b - a) * t


def build_png(size, path):
    SS = 4  # 超采样倍数
    S = size * SS
    radius = size * 0.22 * SS  # 圆角半径

    # 渐变背景：顶部 #1a73e8（Google 蓝）→ 底部 #0d47a1（深蓝）
    top = (26, 115, 232)
    bottom = (13, 71, 161)

    # 开关参数（相对 size 归一化）
    c = S / 2
    track_w = 0.62 * S      # 轨道宽
    track_h = 0.34 * S      # 轨道高
    knob_r = 0.20 * S       # 拨钮半径
    knob_off = 0.16 * S     # 拨钮偏移（右侧=开）

    def in_rounded_rect(x, y, w, h, r):
        cx, cy = min(x, w - 1 - x), min(y, h - 1 - y)
        if cx < r and cy < r:
            dx, dy = r - cx, r - cy
            return dx * dx + dy * dy <= r * r
        return True

    def sample(x, y):
        """返回 (r,g,b,a) 0-255"""
        # 1. 圆角背景
        if not in_rounded_rect(x, y, S, S, radius):
            return (0, 0, 0, 0)
        t = y / S
        r_ = lerp(top[0], bottom[0], t)
        g_ = lerp(top[1], bottom[1], t)
        b_ = lerp(top[2], bottom[2], t)

        # 2. 轨道（圆角矩形，白色半透明）
        tw, th = track_w, track_h
        tx0, ty0 = c - tw / 2, c - th / 2
        if in_rounded_rect(x - tx0, y - ty0, tw, th, th / 2):
            # 轨道内部：稍亮
            r_, g_, b_ = r_ * 0.85 + 255 * 0.15, g_ * 0.85 + 255 * 0.15, b_ * 0.85 + 255 * 0.15

        # 3. 拨钮（白色圆，右侧=开启）
        kx = c + knob_off
        d = math.hypot(x - kx, y - c)
        if d <= knob_r:
            r_, g_, b_ = 255, 255, 255

        # 4. 拨钮内的小圆点（蓝色，表示状态）
        if d <= knob_r * 0.45:
            r_, g_, b_ = top[0], top[1], top[2]

        return (int(r_), int(g_), int(b_), 255)

    # 超采样渲染
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc_r = acc_g = acc_b = acc_a = 0
            for sy in range(SS):
                for sx in range(SS):
                    r_, g_, b_, a = sample(x * SS + sx, y * SS + sy)
                    acc_r += r_ * a
                    acc_g += g_ * a
                    acc_b += b_ * a
                    acc_a += a
            if acc_a == 0:
                row += bytes((0, 0, 0, 0))
            else:
                row += bytes((acc_r // acc_a, acc_g // acc_a, acc_b // acc_a, acc_a // (SS * SS)))
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
