#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def ease_out_back(t):
    t = clamp(t)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def find_font(size, bold=False):
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def nrect(box, w, h):
    x, y, bw, bh = box
    return [
        int(x * w), int(y * h), int((x + bw) * w), int((y + bh) * h)
    ]


def point(p, w, h):
    return int(p[0] * w), int(p[1] * h)


def ensure_even_image(img):
    w, h = img.size
    nw, nh = w - (w % 2), h - (h % 2)
    if (nw, nh) != (w, h):
        img = img.crop((0, 0, nw, nh))
    return img


def bevel_rect(d, box, fill=(192, 192, 192), light=(255, 255, 255), dark=(64, 64, 64), width=2):
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=fill)
    for i in range(max(1, width)):
        d.line((x0 + i, y0 + i, x1 - i, y0 + i), fill=light)
        d.line((x0 + i, y0 + i, x0 + i, y1 - i), fill=light)
        d.line((x0 + i, y1 - i, x1 - i, y1 - i), fill=dark)
        d.line((x1 - i, y0 + i, x1 - i, y1 - i), fill=dark)


def draw_cursor(im, x, y, scale, pressed=False):
    d = ImageDraw.Draw(im)
    s = max(11, int(25 * scale))
    yy = y + (max(1, int(2 * scale)) if pressed else 0)
    pts = [
        (x, yy),
        (x, yy + s),
        (x + int(s * 0.28), yy + int(s * 0.72)),
        (x + int(s * 0.46), yy + int(s * 1.05)),
        (x + int(s * 0.62), yy + int(s * 0.97)),
        (x + int(s * 0.45), yy + int(s * 0.65)),
        (x + int(s * 0.78), yy + int(s * 0.64)),
    ]
    d.polygon(pts, fill=(248, 248, 244), outline=(0, 0, 0))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=max(1, int(scale * 2)))


def draw_click_feedback(im, x, y, scale, strength):
    """Classic-ish click tick instead of a modern circular ripple."""
    if strength <= 0:
        return
    d = ImageDraw.Draw(im)
    r = max(4, int(10 * scale * strength))
    col1, col2 = (255, 255, 255), (0, 0, 0)
    d.line((x - r, y, x - max(2, r // 3), y), fill=col1, width=1)
    d.line((x + max(2, r // 3), y, x + r, y), fill=col1, width=1)
    d.line((x, y - r, x, y - max(2, r // 3)), fill=col1, width=1)
    d.line((x, y + max(2, r // 3), x, y + r), fill=col1, width=1)
    d.point((x, y), fill=col2)


def draw_focus_feedback(im, box, scale, phase=0):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    width = max(2, int(3 * scale))
    d.rectangle(box, outline=(255, 255, 255), width=width)
    inset = max(2, int(4 * scale))
    d.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset), outline=(0, 0, 128), width=max(1, width - 1))
    # Small corner marks keep it image-editor-like.
    m = max(6, int(12 * scale))
    for cx, cy, sx, sy in [
        (x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)
    ]:
        d.line((cx, cy, cx + sx * m, cy), fill=(0, 0, 128), width=width)
        d.line((cx, cy, cx, cy + sy * m), fill=(0, 0, 128), width=width)


def draw_marquee(im, box, scale, phase=0, scan=None):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    step = max(3, int(6 * scale))
    width = max(1, int(scale))
    # marching ants
    for x in range(x0, x1, step):
        idx = ((x - x0) // step + phase) % 2
        col = (255, 255, 255) if idx == 0 else (0, 0, 0)
        d.line((x, y0, min(x + step - 1, x1), y0), fill=col, width=width)
        d.line((x, y1, min(x + step - 1, x1), y1), fill=col, width=width)
    for y in range(y0, y1, step):
        idx = ((y - y0) // step + phase) % 2
        col = (255, 255, 255) if idx == 0 else (0, 0, 0)
        d.line((x0, y, x0, min(y + step - 1, y1)), fill=col, width=width)
        d.line((x1, y, x1, min(y + step - 1, y1)), fill=col, width=width)
    if scan is not None:
        sy = int(lerp(y0 + 2, y1 - 2, clamp(scan)))
        d.line((x0 + 2, sy, x1 - 2, sy), fill=(255, 255, 255), width=max(1, int(2 * scale)))


def make_window_shell(size, title, scale, active=True):
    ww, wh = size
    win = Image.new("RGB", size, (192, 192, 192))
    d = ImageDraw.Draw(win)
    bevel_rect(d, (0, 0, ww - 1, wh - 1), width=max(1, int(2 * scale)))
    th = max(21, int(30 * scale))
    title_col = (0, 0, 128) if active else (128, 128, 128)
    d.rectangle((3, 3, ww - 4, th), fill=title_col)
    tf = find_font(max(11, int(14 * scale)), bold=True)
    d.text((8, 5), title, font=tf, fill=(255, 255, 255))
    b = max(15, int(19 * scale))
    bx = ww - 6 - b
    bevel_rect(d, (bx, 6, bx + b, 6 + b), fill=(192, 192, 192), width=1)
    d.line((bx + 4, 10, bx + b - 4, 6 + b - 4), fill=(0, 0, 0), width=1)
    d.line((bx + b - 4, 10, bx + 4, 6 + b - 4), fill=(0, 0, 0), width=1)
    return win, th


def _safe_size(out_size):
    return max(1, int(out_size[0])), max(1, int(out_size[1]))


def resize_contain(image, out_size, bg=(32, 32, 32), resample=Image.Resampling.NEAREST):
    """Aspect-ratio-preserving resize with neutral letterbox padding."""
    tw, th = _safe_size(out_size)
    if image.width < 1 or image.height < 1:
        return Image.new("RGB", (tw, th), bg)
    ratio = min(tw / image.width, th / image.height)
    nw = max(1, int(round(image.width * ratio)))
    nh = max(1, int(round(image.height * ratio)))
    resized = image.resize((nw, nh), resample)
    canvas = Image.new("RGB", (tw, th), bg)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def resize_cover_crop(image, out_size, resample=Image.Resampling.LANCZOS):
    """Aspect-ratio-preserving center crop that fills the destination without stretching."""
    tw, th = _safe_size(out_size)
    if image.width < 1 or image.height < 1:
        return Image.new("RGB", (tw, th), (0, 0, 0))
    ratio = max(tw / image.width, th / image.height)
    nw = max(1, int(round(image.width * ratio)))
    nh = max(1, int(round(image.height * ratio)))
    resized = image.resize((nw, nh), resample)
    x0 = max(0, (nw - tw) // 2)
    y0 = max(0, (nh - th) // 2)
    return resized.crop((x0, y0, x0 + tw, y0 + th))


def source_locked_crop(base, crop_box, out_size, fit="contain", bg=(24, 24, 24)):
    """Derive window imagery from the mother frame only, preserving geometry."""
    crop = base.crop(crop_box)
    if fit == "cover":
        return resize_cover_crop(crop, out_size, Image.Resampling.NEAREST)
    return resize_contain(crop, out_size, bg=bg, resample=Image.Resampling.NEAREST)


def pixel_identity_portrait(base, crop_box, out_size, pixel_size=(48, 64), colors=16):
    """Source-locked portrait stylization: crop -> low-res -> quantize -> nearest upscale."""
    crop = base.crop(crop_box)
    pw, ph = _safe_size(pixel_size)
    low = resize_cover_crop(crop, (pw, ph), Image.Resampling.LANCZOS)
    low = ImageEnhance.Contrast(low).enhance(1.14)
    # Quantization groups tones/colors without inventing new facial geometry.
    q = low.quantize(colors=max(8, min(32, int(colors))), method=Image.Quantize.MEDIANCUT).convert("RGB")
    tw, th = _safe_size(out_size)
    return q.resize((tw, th), Image.Resampling.NEAREST)


def build_crop_window(base, item, w, h, scale):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "局部放大"), scale)
    d = ImageDraw.Draw(win)
    margin = max(7, int(9 * scale))
    caption_h = max(19, int(24 * scale))
    inner = (margin, th + margin, ww - margin, wh - margin - caption_h)
    iw, ih = max(1, inner[2] - inner[0]), max(1, inner[3] - inner[1])
    crop_box = nrect(item["crop"], w, h)
    detail = source_locked_crop(base, crop_box, (iw, ih), fit=item.get("fit", "contain"))
    win.paste(detail, (inner[0], inner[1]))
    d.rectangle(inner, outline=(64, 64, 64), width=max(1, int(scale)))
    bf = find_font(max(9, int(12 * scale)), bold=False)
    d.text((margin, wh - margin - caption_h + 3), item.get("caption", "选区"), font=bf, fill=(0, 0, 0))
    return win, final, crop_box


def palette_colors(base, sample_box, count=18):
    crop = base.crop(sample_box).resize((128, 128), Image.Resampling.BILINEAR)
    q = crop.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    colors = q.getcolors(maxcolors=128 * 128) or []
    colors.sort(reverse=True)
    out = []
    for _, idx in colors[:count]:
        out.append(tuple(pal[idx * 3: idx * 3 + 3]))
    while len(out) < count:
        out.append((128, 128, 128))
    return out


def build_palette_window(base, item, w, h, scale):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "颜色表"), scale)
    d = ImageDraw.Draw(win)
    sample_box = nrect(item.get("sample", [0, 0, 1, 1]), w, h)
    cols = int(item.get("cols", 6))
    rows = int(item.get("rows", 3))
    colors = palette_colors(base, sample_box, cols * rows)
    margin = max(8, int(10 * scale))
    top = th + margin
    gap = max(2, int(3 * scale))
    sw = max(7, int((ww - 2 * margin - (cols - 1) * gap) / cols))
    sh = max(7, int((wh - top - margin - (rows - 1) * gap) / rows))
    k = 0
    for r in range(rows):
        for c in range(cols):
            x0 = margin + c * (sw + gap)
            y0 = top + r * (sh + gap)
            bevel_rect(d, (x0, y0, x0 + sw, y0 + sh), fill=colors[k], width=1)
            k += 1
    return win, final, None


def build_properties_window(base, item, w, h, scale, metadata):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "图像属性"), scale)
    d = ImageDraw.Draw(win)
    bf = find_font(max(9, int(12 * scale)), bold=False)
    y = th + max(10, int(12 * scale))
    x = max(8, int(10 * scale))
    line_h = max(16, int(20 * scale))
    for line in metadata[:7]:
        d.text((x, y), line, font=bf, fill=(0, 0, 0))
        y += line_h
        if y > wh - line_h:
            break
    return win, final, None


def build_dashboard_window(base, item, w, h, scale, metadata):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "水的分析器"), scale)
    d = ImageDraw.Draw(win)
    margin = max(7, int(9 * scale))
    bf = find_font(max(9, int(12 * scale)), bold=False)
    sf = find_font(max(8, int(11 * scale)), bold=False)
    # thumbnail
    thumb_w = max(40, int(ww * 0.26))
    thumb_h = max(36, int(wh * 0.30))
    thumb = resize_contain(base, (thumb_w, thumb_h), bg=(24, 24, 24), resample=Image.Resampling.NEAREST)
    tx, ty = margin, th + margin
    win.paste(thumb, (tx, ty))
    d.rectangle((tx, ty, tx + thumb_w, ty + thumb_h), outline=(64, 64, 64), width=max(1, int(scale)))
    # text block
    x = tx + thumb_w + margin
    y = ty
    lines = metadata[:3] if metadata else ["模式：256 色", "状态：分析中", "文件：IMAGE_01.BMP"]
    for line in lines:
        d.text((x, y), line, font=sf, fill=(0, 0, 0))
        y += max(12, int(15 * scale))
    # progress bar
    bar_x0 = margin
    bar_y0 = ty + thumb_h + max(7, int(9 * scale))
    bar_x1 = ww - margin
    bar_y1 = bar_y0 + max(10, int(12 * scale))
    bevel_rect(d, (bar_x0, bar_y0, bar_x1, bar_y1), fill=(212, 212, 212), width=1)
    fill_w = int((bar_x1 - bar_x0 - 4) * 0.68)
    d.rectangle((bar_x0 + 2, bar_y0 + 2, bar_x0 + 2 + fill_w, bar_y1 - 2), fill=(0, 0, 128))
    # small buttons
    btn_y = bar_y1 + max(7, int(8 * scale))
    labels = ["扫描", "索引", "取样"]
    btn_w = max(28, int((ww - 2 * margin - 2 * margin) / 3))
    gap = max(4, int(5 * scale))
    bx = margin
    for lab in labels:
        bevel_rect(d, (bx, btn_y, bx + btn_w, btn_y + max(15, int(18 * scale))), fill=(192, 192, 192), width=1)
        d.text((bx + 6, btn_y + 2), lab, font=sf, fill=(0, 0, 0))
        bx += btn_w + gap
    return win, final, None


def stable_image_seed(base):
    sample = base.resize((24, 24), Image.Resampling.BILINEAR).tobytes()
    return int(hashlib.sha256(sample).hexdigest()[:12], 16)


def pick_stable(values, seed, offset=0, fallback="未知"):
    if not values:
        return fallback
    return values[(seed + offset) % len(values)]


def _split_title_lines(text, max_chars=8):
    text = str(text)
    if len(text) <= max_chars:
        return [text]
    return [text[:max_chars], text[max_chars:max_chars * 2]]


def build_identity_card_window(base, item, w, h, scale, plan, t=0.0):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "人物身份卡"), scale)
    d = ImageDraw.Draw(win)
    margin = max(7, int(9 * scale))
    sf = find_font(max(8, int(11 * scale)), bold=False)
    bf = find_font(max(10, int(13 * scale)), bold=True)
    title_font = find_font(max(11, int(15 * scale)), bold=True)

    crop_box = nrect(item.get("portrait_crop", [0.40, 0.18, 0.22, 0.30]), w, h)
    portrait_w = max(54, int(ww * 0.34))
    portrait_h = max(72, int((wh - th) * 0.60))
    portrait = pixel_identity_portrait(
        base,
        crop_box,
        (portrait_w, portrait_h),
        pixel_size=tuple(item.get("portrait_pixel_size", [48, 64])),
        colors=int(item.get("portrait_colors", 16)),
    )
    px, py = margin, th + margin
    win.paste(portrait, (px, py))
    d.rectangle((px, py, px + portrait_w, py + portrait_h), outline=(64, 64, 64), width=max(1, int(scale)))

    seed = stable_image_seed(base)
    selected_title = pick_stable(plan.get("job_titles", []), seed, 0, "临时现实维护员")
    status = pick_stable(plan.get("status_pool", []), seed, 7, "可疑正常")
    note = pick_stable(plan.get("note_pool", []), seed, 13, "识别结果仅供娱乐")
    archive_id = f"SH-{seed % 10000:04d}"
    reveal_time = float(item.get("title_reveal_time", 0.0))
    title_visible = t >= reveal_time

    tx = px + portrait_w + margin
    ty = py
    d.text((tx, ty), "档案编号：", font=sf, fill=(64, 64, 64))
    ty += max(13, int(15 * scale))
    d.text((tx, ty), archive_id, font=sf, fill=(0, 0, 0))
    ty += max(20, int(22 * scale))
    d.text((tx, ty), "状态：", font=sf, fill=(64, 64, 64))
    ty += max(13, int(15 * scale))
    d.text((tx, ty), status if title_visible else "处理中", font=bf, fill=(0, 0, 0))

    # Profession is the visual punchline: strong old-Windows selection strip.
    strip_y = max(py + portrait_h + margin, th + int((wh - th) * 0.62))
    d.text((margin, strip_y), "职业身份：", font=sf, fill=(64, 64, 64))
    strip_y += max(14, int(17 * scale))
    strip_h = max(34, int(45 * scale))
    d.rectangle((margin, strip_y, ww - margin, min(wh - margin - 22, strip_y + strip_h)), fill=(0, 0, 128))
    shown = selected_title if title_visible else "正在编译离谱头衔…"
    lines = _split_title_lines(shown, max_chars=8)
    yy = strip_y + 3
    for line in lines[:2]:
        d.text((margin + 6, yy), line, font=title_font, fill=(255, 255, 255))
        yy += max(15, int(18 * scale))

    note_y = wh - max(22, int(27 * scale))
    d.text((margin, note_y), f"备注：{note if title_visible else '等待归档'}", font=sf, fill=(0, 0, 0))
    return win, final, None

def progress_state(t, item, plan):
    start = float(item.get("progress_start", item.get("appear", 0.0)))
    end = float(item.get("progress_end", start + 3.0))
    q = clamp((t - start) / max(1e-6, end - start))
    steps = plan.get("progress_steps", [[1.0, "归档完成"]])
    # Milestones are target percentages. Choose the first milestone >= current q,
    # but keep the displayed percentage continuously moving to make the bar feel alive.
    msg = steps[-1][1]
    for pct, text in steps:
        if q <= float(pct):
            msg = text
            break
    return q, msg


def build_progress_window(base, item, w, h, scale, plan, t):
    final = nrect(item["window"], w, h)
    ww, wh = final[2] - final[0], final[3] - final[1]
    win, th = make_window_shell((ww, wh), item.get("title", "分析进度"), scale)
    d = ImageDraw.Draw(win)
    margin = max(8, int(10 * scale))
    sf = find_font(max(8, int(11 * scale)), bold=False)
    bf = find_font(max(9, int(12 * scale)), bold=True)
    q, msg = progress_state(t, item, plan)

    d.text((margin, th + margin), msg, font=sf, fill=(0, 0, 0))
    pct = int(round(q * 100))
    d.text((ww - margin - max(34, int(38 * scale)), th + margin), f"{pct:3d}%", font=bf, fill=(0, 0, 0))

    bar_y0 = th + margin + max(25, int(30 * scale))
    bar_y1 = bar_y0 + max(15, int(18 * scale))
    bevel_rect(d, (margin, bar_y0, ww - margin, bar_y1), fill=(224, 224, 224), width=1)
    inner_x0, inner_x1 = margin + 3, ww - margin - 3
    fill_x = inner_x0 + int((inner_x1 - inner_x0) * q)
    if fill_x > inner_x0:
        d.rectangle((inner_x0, bar_y0 + 3, fill_x, bar_y1 - 3), fill=(0, 0, 128))

    y = bar_y1 + max(8, int(9 * scale))
    active_footer = str(plan.get("active_progress_footer", "水的分析器正在生成档案"))
    done_footer = str(item.get("final_footer_text", plan.get("final_completion_footer", "身份记录已归档")))
    footer = done_footer if q >= 0.999 else active_footer
    d.text((margin, y), footer, font=sf, fill=(64, 64, 64))
    return win, final, None

def build_analyzer_window(base, item, w, h, scale, metadata, plan=None, t=0.0):
    typ = item.get("type", "crop")
    plan = plan or {}
    if typ == "identity_card":
        return build_identity_card_window(base, item, w, h, scale, plan, t=t)
    if typ == "progress":
        return build_progress_window(base, item, w, h, scale, plan, t)
    if typ == "dashboard":
        return build_dashboard_window(base, item, w, h, scale, metadata)
    if typ == "crop":
        return build_crop_window(base, item, w, h, scale)
    if typ == "palette":
        return build_palette_window(base, item, w, h, scale)
    return build_properties_window(base, item, w, h, scale, metadata)


def paste_pop(canvas, window_img, final_box, progress, closing=False):
    if progress <= 0:
        return
    x0, y0, x1, y1 = final_box
    fw, fh = x1 - x0, y1 - y0
    if closing:
        p = 1.0 - smoothstep(progress)
    else:
        p = min(1.0, max(0.0, ease_out_back(progress)))
    # Keep a minimum size so first visible frame reads as a window, not a dot.
    scale = 0.64 + 0.36 * p
    nw, nh = max(2, int(fw * scale)), max(2, int(fh * scale))
    resized = window_img.resize((nw, nh), Image.Resampling.NEAREST)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    px, py = cx - nw // 2, cy - nh // 2
    canvas.paste(resized, (px, py))


def load_plan(path):
    plan = {
        "duration": 3.1,
        "fps": 24,
        "cursor_mode": "direct_click",
        "cursor_visible": True,
        "cursor_anchor": [0.53, 0.50],
        "click_time": 0.24,
        "focus_box": [0.18, 0.12, 0.54, 0.72],
        "metadata": ["文件：IMAGE_01.BMP", "模式：256 色", "状态：就绪"],
        "analyzers": [],
    }
    if path:
        with open(path, "r", encoding="utf-8") as f:
            plan.update(json.load(f))
    return plan


def timing_for_item(item, index, n, duration):
    appear = float(item.get("appear", 0.36 + 0.10 * index))
    pop_dur = float(item.get("pop_duration", 0.18))
    close_base = min(duration - 0.24, float(item.get("close_base", 2.46)))
    disappear = float(item.get("disappear", close_base + (n - 1 - index) * 0.08))
    close_dur = float(item.get("close_duration", 0.16))
    return appear, pop_dur, disappear, close_dur


def cursor_position(t, plan, w, h):
    mode = str(plan.get("cursor_mode", "direct_click"))
    anchor = point(plan.get("cursor_anchor", [0.53, 0.50]), w, h)
    if mode != "short_move_click":
        return anchor
    start = point(plan.get("cursor_start", [0.18, 0.90]), w, h)
    move_start = float(plan.get("move_start", 0.20))
    move_end = float(plan.get("move_end", 0.34))
    if t <= move_start:
        return start
    if t >= move_end:
        return anchor
    q = clamp((t - move_start) / max(1e-6, move_end - move_start))
    q = smoothstep(q)
    return int(lerp(start[0], anchor[0], q)), int(lerp(start[1], anchor[1], q))

def frame_at(base, t, plan, poster=False):
    im = base.copy()
    w, h = im.size
    scale = w / 1024.0
    duration = float(plan.get("duration", 6.8))
    click_time = float(plan.get("click_time", 0.16))
    cursor_mode = str(plan.get("cursor_mode", "direct_click"))
    cursor_visible = bool(plan.get("cursor_visible", True))
    cursor_anchor = point(plan.get("cursor_anchor", [0.53, 0.50]), w, h)
    trigger_box = nrect(plan.get("trigger_box", [0.045, 0.73, 0.13, 0.17]), w, h)
    focus_box = nrect(plan.get("focus_box", [0.18, 0.12, 0.54, 0.72]), w, h)
    analyzers = list(plan.get("analyzers", []))
    metadata = list(plan.get("metadata", []))

    # Build all analyzer windows deterministically from the untouched mother frame.
    built = []
    build_t = duration if poster else t
    for i, item in enumerate(analyzers):
        win, final, source = build_analyzer_window(base, item, w, h, scale, metadata, plan=plan, t=build_t)
        built.append((item, win, final, source, timing_for_item(item, i, len(analyzers), duration)))

    if poster:
        # Peak expanded state: all analyzers fully open. V48 intentionally
        # keeps the source photo clean; no face/source marquee scanning.
        for i, (item, win, final, source, timing) in enumerate(built):
            im.paste(win, (final[0], final[1]))
        return im

    # Trigger highlight during click. V48 removes the face/photo scan focus.
    if click_time - 0.02 <= t <= click_time + 0.10:
        draw_focus_feedback(im, trigger_box, scale)

    # Analyzer overlays + real-photo source selections.
    for i, (item, win, final, source, timing) in enumerate(built):
        appear, pop_dur, disappear, close_dur = timing
        visible = appear <= t < disappear
        if not visible:
            continue

        # V45 SNAP MODE: binary visibility only.
        # No position interpolation, no size interpolation, no easing.
        if appear <= t < disappear:
            im.paste(win, (final[0], final[1]))


    # Cursor logic: short readable move then click.
    cx, cy = cursor_position(t, plan, w, h)
    click_pressed = click_time <= t < click_time + 0.10
    if cursor_visible:
        draw_cursor(im, cx, cy, scale, pressed=click_pressed)

    if click_time <= t < click_time + 0.20:
        q = 1.0 - ((t - click_time) / 0.20)
        draw_click_feedback(im, cursor_anchor[0], cursor_anchor[1], scale, q)

    # Very subtle CRT breathing only; never the primary motion.
    pulse = 1.0 + 0.008 * math.sin(2 * math.pi * t / duration)
    if abs(pulse - 1.0) > 0.001:
        im = ImageEnhance.Brightness(im).enhance(pulse)
    return im


def encode_mp4(frame_dir, fps, output):
    out = str(Path(output).resolve())
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, "frame_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-level", "4.0",
        "-movflags", "+faststart",
        "-tag:v", "avc1",
        "-r", str(fps),
        out,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def main():
    ap = argparse.ArgumentParser(description="Deterministic V53 final-locked live renderer")
    ap.add_argument("--input", required=True, help="Clean static mother frame")
    ap.add_argument("--output", required=True, help="Final live MP4")
    ap.add_argument("--plan", help="Animation plan JSON")
    ap.add_argument("--poster", help="Optional expanded end-state PNG")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found; live render skipped")

    plan = load_plan(args.plan)
    fps = int(plan.get("fps", 24))
    duration = float(plan.get("duration", 6.8))
    base = ensure_even_image(Image.open(args.input).convert("RGB"))

    if args.poster:
        poster = frame_at(base, min(2.35, duration * 0.72), plan, poster=True)
        poster.save(args.poster)

    frames = max(1, round(fps * duration))
    with tempfile.TemporaryDirectory(prefix="shuishuidamowang_v49_") as td:
        for i in range(frames):
            t = i / fps
            fr = frame_at(base, t, plan, poster=False)
            fr.save(os.path.join(td, f"frame_{i:04d}.png"), compress_level=1)
        print(encode_mp4(td, fps, args.output))


if __name__ == "__main__":
    main()
