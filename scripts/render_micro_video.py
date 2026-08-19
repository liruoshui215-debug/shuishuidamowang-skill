#!/usr/bin/env python3
"""Compose a loop-safe micro-animation from a fixed card and RGBA overlays."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat


TAU = math.tau


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def rgba_color(value: str, alpha: int) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def motion_wave(motion: dict, progress: float) -> float:
    """Loop-safe wave that always returns to the exact rest pose at t=0/1."""
    cycles = float(motion.get("cycles", 1.0))
    lag = float(motion.get("lag", 0.0))
    angle = TAU * cycles * progress
    wave = math.sin(angle) - lag * (1 - math.cos(angle))
    return wave / max(1.0, math.sqrt(1 + lag * lag))


def effect_envelope(config: dict, progress: float) -> float:
    """Fade cinematic effects to a neutral frame at the loop boundary."""
    if config.get("motion_profile") == "cinematic_scene":
        return math.sin(math.pi * progress) ** 2
    return 1.0


def apply_layer_mask(image: Image.Image, layer: dict, root: Path) -> Image.Image:
    if not layer.get("mask"):
        return image
    mask = Image.open(resolve_path(root, layer["mask"])).convert("L")
    if mask.size != image.size:
        raise ValueError(f"Mask size mismatch for layer {layer.get('name', '<unnamed>')}")
    result = image.copy()
    result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
    return result


def sprite_frame(layer: dict, root: Path, frame_index: int, fps: int) -> Image.Image:
    if "image" in layer and "sheet" in layer:
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} has both image and sheet")
    if "image" in layer:
        return Image.open(resolve_path(root, layer["image"])).convert("RGBA")
    if "sheet" not in layer:
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} needs image or sheet")

    sheet = Image.open(resolve_path(root, layer["sheet"])).convert("RGBA")
    columns = int(layer.get("columns", 1))
    rows = int(layer.get("rows", 1))
    if columns < 1 or rows < 1 or sheet.width % columns or sheet.height % rows:
        raise ValueError(f"Invalid sheet grid for layer {layer.get('name', '<unnamed>')}")
    cell_w, cell_h = sheet.width // columns, sheet.height // rows
    sequence = layer.get("sequence", list(range(columns * rows)))
    if not sequence:
        raise ValueError("Sprite sequence cannot be empty")
    start_frame = round(float(layer.get("start", 0.0)) * fps)
    hold = max(1, int(layer.get("frame_hold", 1)))
    step = (frame_index - start_frame) // hold
    if step < 0:
        sprite_index = int(sequence[0])
    elif layer.get("loop_sprite", False):
        sprite_index = int(sequence[step % len(sequence)])
    else:
        sprite_index = int(sequence[min(step, len(sequence) - 1)])
    if not 0 <= sprite_index < columns * rows:
        raise ValueError(f"Sprite index {sprite_index} is outside the sheet")
    left = (sprite_index % columns) * cell_w
    top = (sprite_index // columns) * cell_h
    return sheet.crop((left, top, left + cell_w, top + cell_h))


def transformed_layer(image: Image.Image, layer: dict, progress: float) -> tuple[Image.Image, int, int]:
    motion = layer.get("motion", {})
    wave = motion_wave(motion, progress)
    x = round(float(layer.get("x", 0)) + float(motion.get("bob_x", 0)) * wave)
    y = round(float(layer.get("y", 0)) + float(motion.get("bob_y", 0)) * wave)
    angle = float(motion.get("sway_degrees", 0)) * wave

    scale = float(layer.get("scale", 1.0))
    if not 0.25 <= scale <= 4.0:
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} scale must be between 0.25 and 4.0")
    if abs(scale - 1.0) > 1e-9:
        old_w, old_h = image.size
        new_w, new_h = max(1, round(old_w * scale)), max(1, round(old_h * scale))
        resampling = Image.Resampling.NEAREST if layer.get("pixel_art", True) else Image.Resampling.BICUBIC
        image = image.resize((new_w, new_h), resampling)
        anchor = str(layer.get("scale_anchor", "bottom_center"))
        if anchor == "bottom_center":
            x += round((old_w - new_w) / 2)
            y += old_h - new_h
        elif anchor != "top_left":
            raise ValueError(f"Layer {layer.get('name', '<unnamed>')} has unsupported scale_anchor {anchor!r}")

    if abs(angle) < 1e-9:
        return image, x, y

    w, h = image.size
    padding = math.ceil(math.hypot(w, h)) + 4
    padded = Image.new("RGBA", (w + 2 * padding, h + 2 * padding))
    padded.alpha_composite(image, (padding, padding))
    pivot_x = padding + float(motion.get("pivot_x", w / 2))
    pivot_y = padding + float(motion.get("pivot_y", h / 2))
    resampling = Image.Resampling.NEAREST if layer.get("pixel_art", True) else Image.Resampling.BICUBIC
    rotated = padded.rotate(angle, resample=resampling, center=(pivot_x, pivot_y))
    bbox = rotated.getbbox()
    if bbox is None:
        return image, x, y
    return rotated.crop(bbox), x - padding + bbox[0], y - padding + bbox[1]


def deform_layer(image: Image.Image, layer: dict, progress: float) -> tuple[Image.Image, int, int]:
    """Bend a tip layer continuously while keeping its root pixels anchored."""
    deform = layer.get("deform")
    if not deform:
        return image, 0, 0
    kind = str(deform.get("type", "tip_sway"))
    if kind != "tip_sway":
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} has unsupported deform type {kind!r}")
    cycles = float(deform.get("cycles", 1))
    angle = TAU * cycles * progress
    amplitude_x = float(deform.get("amplitude_x", 0))
    secondary = float(deform.get("secondary_amplitude", 0))
    amplitude_y = float(deform.get("amplitude_y", 0))
    power = max(1.0, float(deform.get("power", 1.7)))
    anchor = str(deform.get("anchor", "top"))
    if anchor not in {"top", "bottom"}:
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} deform anchor must be top or bottom")
    waveform = str(deform.get("waveform", "sine"))
    if waveform == "sine":
        primary_wave = math.sin(angle)
    elif waveform == "pulse":
        primary_wave = math.sin(math.pi * cycles * progress) ** 2
    else:
        raise ValueError(f"Layer {layer.get('name', '<unnamed>')} has unsupported deform waveform {waveform!r}")
    horizontal = amplitude_x * primary_wave + secondary * math.sin(2 * angle)
    vertical = amplitude_y * (1 - math.cos(angle)) / 2
    padding_x = math.ceil(abs(amplitude_x) + abs(secondary)) + 2
    padding_y = math.ceil(abs(amplitude_y)) + 2
    output = Image.new("RGBA", (image.width + 2 * padding_x, image.height + 2 * padding_y))
    alpha_bbox = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
    content_top, content_bottom = alpha_bbox[1], alpha_bbox[3] - 1
    denominator = max(1, content_bottom - content_top)
    for row in range(image.height):
        if anchor == "top":
            normalized = (row - content_top) / denominator
        else:
            normalized = (content_bottom - row) / denominator
        normalized = max(0.0, min(1.0, normalized))
        influence = normalized**power
        dx = round(horizontal * influence)
        dy = round(vertical * influence)
        strip = image.crop((0, row, image.width, row + 1))
        output.alpha_composite(strip, (padding_x + dx, padding_y + row + dy))
    return output, -padding_x, -padding_y


def group_map(config: dict) -> dict[str, dict]:
    groups = config.get("groups", [])
    if isinstance(groups, dict):
        return groups
    return {str(group["name"]): group for group in groups}


def grouped_canvas(
    image: Image.Image,
    x: int,
    y: int,
    group: dict,
    progress: float,
    canvas_size: tuple[int, int],
    pixel_art: bool,
) -> Image.Image:
    canvas = Image.new("RGBA", canvas_size)
    canvas.alpha_composite(image, (x, y))
    motion = group.get("motion", {})
    wave = motion_wave(motion, progress)
    dx = round(float(motion.get("bob_x", 0)) * wave)
    dy = round(float(motion.get("bob_y", 0)) * wave)
    angle = float(motion.get("sway_degrees", 0)) * wave
    pivot = group.get("pivot", [canvas_size[0] / 2, canvas_size[1] / 2])
    resampling = Image.Resampling.NEAREST if pixel_art else Image.Resampling.BICUBIC
    if dx or dy or abs(angle) > 1e-9:
        canvas = canvas.rotate(
            angle,
            resample=resampling,
            center=(float(pivot[0]), float(pivot[1])),
            translate=(dx, dy),
            expand=False,
        )
    return canvas


def draw_glints(draw: ImageDraw.ImageDraw, config: dict, progress: float) -> None:
    envelope = effect_envelope(config, progress)
    for item in config.get("glints", []):
        wave = (1 + math.sin(TAU * (float(item.get("cycles", 2)) * progress + float(item.get("phase", 0))))) / 2
        alpha = round(255 * wave**2 * envelope)
        radius = int(item.get("radius", 6)) + round(float(item.get("pulse_radius", 0)) * wave * envelope)
        x, y = int(item["x"]), int(item["y"])
        color = rgba_color(item.get("color", "#ffffff"), alpha)
        width = max(1, int(item.get("width", 2 if config.get("motion_profile") == "cinematic_scene" else 1)))
        draw.line((x - radius, y, x + radius, y), fill=color, width=width)
        draw.line((x, y - radius, x, y + radius), fill=color, width=width)
        draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=color)


def draw_lights(draw: ImageDraw.ImageDraw, config: dict, progress: float) -> None:
    envelope = effect_envelope(config, progress)
    for item in config.get("lights", []):
        wave = (1 + math.sin(TAU * (float(item.get("cycles", 3)) * progress + float(item.get("phase", 0))))) / 2
        alpha = round((50 + 205 * wave) * envelope)
        radius = int(item.get("radius", 4)) + round(float(item.get("pulse_radius", 0)) * wave * envelope)
        x, y = int(item["x"]), int(item["y"])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rgba_color(item.get("color", "#76ff9b"), alpha))


def draw_frame_fx(config: dict, progress: float, size: tuple[int, int], root: Path) -> Image.Image:
    """Render additive effects only for the locked outer frame."""
    effects = Image.new("RGBA", size)
    draw = ImageDraw.Draw(effects, "RGBA")
    envelope = effect_envelope(config, progress)
    for item in config.get("frame_fx", []):
        kind = str(item.get("type", "gem_glint"))
        cycles = float(item.get("cycles", 1))
        phase = float(item.get("phase", 0))
        wave = (1 + math.sin(TAU * (cycles * progress + phase))) / 2
        alpha = round(float(item.get("opacity", 220)) * wave**2 * envelope)
        color = rgba_color(item.get("color", "#ffffff"), alpha)

        if kind == "gem_glint":
            x, y = int(item["x"]), int(item["y"])
            radius = int(item.get("radius", 5)) + round(float(item.get("pulse_radius", 5)) * wave * envelope)
            width = max(1, int(item.get("width", 2)))
            draw.line((x - radius, y, x + radius, y), fill=color, width=width)
            draw.line((x, y - radius, x, y + radius), fill=color, width=width)
            diagonal = max(2, round(radius * 0.45))
            draw.polygon(((x, y - diagonal), (x + diagonal, y), (x, y + diagonal), (x - diagonal, y)), fill=color)
        elif kind == "icon_pulse":
            x, y = int(item["x"]), int(item["y"])
            radius = int(item.get("radius", 18)) + round(float(item.get("pulse_radius", 6)) * wave * envelope)
            width = max(1, int(item.get("width", 3)))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=width)
        elif kind == "rail_light":
            points = [tuple(map(int, point)) for point in item.get("points", [])]
            if not points:
                continue
            cursor = ((cycles * progress + phase) % 1.0) * len(points)
            radius = max(1, int(item.get("radius", 4)))
            for index, (x, y) in enumerate(points):
                distance = abs(index - cursor)
                distance = min(distance, len(points) - distance)
                strength = max(0.0, 1.0 - distance / 1.5)
                point_alpha = round(float(item.get("opacity", 230)) * strength**2 * envelope)
                if point_alpha:
                    point_color = rgba_color(item.get("color", "#ffffff"), point_alpha)
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=point_color)
        else:
            raise ValueError(f"Unknown frame_fx type: {kind}")

    if config.get("frame_fx_mask"):
        mask = Image.open(resolve_path(root, config["frame_fx_mask"])).convert("L")
        if mask.size != size:
            raise ValueError("frame_fx_mask must match the base dimensions")
        effects.putalpha(ImageChops.multiply(effects.getchannel("A"), mask))
    return effects


def particle_specs(config: dict) -> list[tuple[dict, list[tuple[float, float, float, int]]]]:
    groups = []
    for group in config.get("particles", []):
        rng = random.Random(int(group.get("seed", 68)))
        x1, y1, x2, y2 = map(float, group["region"])
        radius_range = group.get("radius", [1, 3])
        particles = []
        for _ in range(int(group.get("count", 12))):
            particles.append((rng.uniform(x1, x2), rng.uniform(y1, y2), rng.random(), rng.randint(int(radius_range[0]), int(radius_range[1]))))
        groups.append((group, particles))
    return groups


def draw_particles(draw: ImageDraw.ImageDraw, config: dict, groups, progress: float) -> None:
    envelope = effect_envelope(config, progress)
    for group, particles in groups:
        cycles = float(group.get("cycles", 1))
        drift_x = float(group.get("drift_x", 6))
        drift_y = float(group.get("drift_y", 10))
        base_alpha = int(group.get("opacity", 120))
        for x0, y0, phase, radius in particles:
            angle = TAU * (cycles * progress + phase)
            x = x0 + drift_x * math.sin(angle)
            y = y0 + drift_y * math.cos(angle)
            alpha = round(base_alpha * (0.35 + 0.65 * ((1 + math.sin(angle * 2)) / 2)) * envelope)
            color = rgba_color(group.get("color", "#ffffff"), alpha)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def draw_falling_leaves(draw: ImageDraw.ImageDraw, config: dict, progress: float) -> None:
    """Draw deterministic, dimensional wind-borne leaves without moving scenery."""
    envelope = effect_envelope(config, progress)
    for group in config.get("falling_leaves", []):
        rng = random.Random(int(group.get("seed", 6805)))
        x1, y1, x2, y2 = map(float, group["region"])
        count = int(group.get("count", 6))
        fall_x = float(group.get("fall_x", 28))
        fall_y = float(group.get("fall_y", 90))
        base_alpha = int(group.get("opacity", 190))
        visibility_gamma = max(0.4, min(2.0, float(group.get("visibility_gamma", 1.0))))
        colors = group.get("colors", ["#d9c35a", "#98b64a", "#f0d97a"])
        outline_color = str(group.get("outline_color", "#53632c"))
        vein_color = str(group.get("vein_color", "#fff0a0"))
        leaf_style = str(group.get("leaf_style", "autumn"))
        flip_min = max(0.25, min(1.0, float(group.get("flip_min", 0.55))))
        for _ in range(count):
            x0, y0, phase = rng.uniform(x1, x2), rng.uniform(y1, y2), rng.random()
            size = rng.randint(int(group.get("size_min", 4)), int(group.get("size_max", 7)))
            depth = rng.uniform(0.72, 1.25)
            aspect = rng.uniform(0.48, 0.78)
            path_phase = rng.random()
            spin_direction = -1 if rng.random() < 0.5 else 1
            fill_hex = str(colors[rng.randrange(len(colors))])
            local = (progress + phase) % 1.0
            flutter = math.sin(TAU * (local * 2 + path_phase))
            curl = math.sin(TAU * (local + path_phase))
            x = x0 + fall_x * local + size * depth * (1.8 * flutter + 0.7 * curl)
            y = y0 + fall_y * local + size * 0.45 * math.sin(TAU * (local * 2 + phase))
            alpha = round(base_alpha * (math.sin(math.pi * local) ** visibility_gamma) * envelope)
            if alpha <= 0:
                continue
            long_radius = max(3, round(size * depth))
            short_radius = max(2, round(long_radius * aspect * max(flip_min, abs(math.cos(TAU * (local * 1.5 + path_phase))))))
            rotation = TAU * (spin_direction * local * 1.25 + path_phase)
            axis = (math.cos(rotation), math.sin(rotation))
            normal = (-axis[1], axis[0])
            tip_a = (x + axis[0] * long_radius, y + axis[1] * long_radius)
            tip_b = (x - axis[0] * long_radius, y - axis[1] * long_radius)
            side_a = (x + normal[0] * short_radius, y + normal[1] * short_radius)
            side_b = (x - normal[0] * short_radius, y - normal[1] * short_radius)
            outline = rgba_color(outline_color, min(255, round(alpha * 0.9)))
            fill = rgba_color(fill_hex, alpha)
            highlight = rgba_color(vein_color, min(255, round(alpha * 0.72)))
            if leaf_style == "autumn":
                def point(axis_amount: float, normal_amount: float) -> tuple[float, float]:
                    return (
                        x + axis[0] * long_radius * axis_amount + normal[0] * short_radius * normal_amount,
                        y + axis[1] * long_radius * axis_amount + normal[1] * short_radius * normal_amount,
                    )

                polygon = [
                    point(1.00, 0.00), point(0.58, 0.34), point(0.18, 0.66),
                    point(-0.28, 0.46), point(-0.74, 0.00), point(-0.28, -0.46),
                    point(0.18, -0.66), point(0.58, -0.34),
                ]
                draw.polygon(polygon, fill=fill)
                draw.line(polygon + [polygon[0]], fill=outline, width=max(1, round(depth)))
            elif leaf_style == "broadleaf":
                polygon = (tip_a, side_a, tip_b, side_b)
                draw.polygon(polygon, fill=fill, outline=outline)
            else:
                raise ValueError(f"Unsupported falling leaf style: {leaf_style}")
            draw.line((tip_b[0], tip_b[1], tip_a[0], tip_a[1]), fill=highlight, width=max(1, round(depth)))
            stem_end = (tip_b[0] - axis[0] * max(2, long_radius // 2), tip_b[1] - axis[1] * max(2, long_radius // 2))
            draw.line((tip_b[0], tip_b[1], stem_end[0], stem_end[1]), fill=outline, width=1)


def apply_water_ripples(frame: Image.Image, config: dict, progress: float) -> Image.Image:
    """Shift only declared open-water rectangles; never move the full card."""
    for item in config.get("water_ripples", []):
        x1, y1, x2, y2 = map(int, item["region"])
        if not (0 <= x1 < x2 <= frame.width and 0 <= y1 < y2 <= frame.height):
            raise ValueError(f"Invalid water_ripples region: {item['region']}")
        crop = frame.crop((x1, y1, x2, y2))
        wave = motion_wave(item, progress) * effect_envelope(config, progress)
        dx = float(item.get("amplitude_x", 0)) * wave
        dy = float(item.get("amplitude_y", 0)) * wave
        resampling = Image.Resampling.NEAREST if item.get("pixel_art", False) else Image.Resampling.BICUBIC
        shifted = crop.transform(
            crop.size,
            Image.Transform.AFFINE,
            (1, 0, -dx, 0, 1, -dy),
            resample=resampling,
        )
        blend = max(0.0, min(1.0, float(item.get("blend", 0.6))))
        edge = max(0, int(item.get("edge_fade", 16)))
        mask = Image.new("L", crop.size)
        inset_x = min(edge, max(0, crop.width // 3))
        inset_y = min(edge, max(0, crop.height // 3))
        ImageDraw.Draw(mask).rectangle(
            (inset_x, inset_y, crop.width - inset_x - 1, crop.height - inset_y - 1),
            fill=round(255 * blend),
        )
        if edge:
            mask = mask.filter(ImageFilter.GaussianBlur(max(1, edge / 2)))
        frame.paste(Image.composite(shifted, crop, mask), (x1, y1))
    return frame


def has_transform(motion: dict) -> bool:
    return any(abs(float(motion.get(key, 0))) > 0 for key in ("bob_x", "bob_y", "sway_degrees"))


def layer_is_animated(layer: dict, groups: dict[str, dict]) -> bool:
    return (
        "sheet" in layer
        or bool(layer.get("deform"))
        or has_transform(layer.get("motion", {}))
        or has_transform(groups.get(str(layer.get("group", "")), {}).get("motion", {}))
    )


def alpha_fragment_report(image: Image.Image, threshold: int = 17) -> tuple[float, int]:
    """Return the visible alpha outside the largest 8-connected component."""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return 1.0, 0
    crop = alpha.crop(bbox)
    width, height = crop.size
    pixels = bytes(1 if value > threshold else 0 for value in crop.get_flattened_data())
    seen = bytearray(width * height)
    sizes = []
    for start, occupied in enumerate(pixels):
        if not occupied or seen[start]:
            continue
        queue = deque([start])
        seen[start] = 1
        size = 0
        while queue:
            index = queue.popleft()
            size += 1
            x, y = index % width, index // width
            for ny in range(max(0, y - 1), min(height, y + 2)):
                row = ny * width
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = row + nx
                    if pixels[neighbor] and not seen[neighbor]:
                        seen[neighbor] = 1
                        queue.append(neighbor)
        sizes.append(size)
    meaningful = [size for size in sizes if size >= 4]
    total = sum(meaningful)
    if not total:
        return 1.0, 0
    return 1 - max(meaningful) / total, len(meaningful)


def compose_frame(
    config: dict,
    root: Path,
    frame_index: int,
    total: int,
    base: Image.Image,
    locked_overlay: Image.Image | None,
    particles,
    include_effects: bool,
) -> Image.Image:
    fps = int(config.get("fps", 24))
    progress = frame_index / total
    groups = group_map(config)
    frame = apply_water_ripples(base.copy(), config, progress) if include_effects else base.copy()
    for layer in sorted(config.get("layers", []), key=lambda item: float(item.get("z", 0))):
        source = apply_layer_mask(sprite_frame(layer, root, frame_index, fps), layer, root)
        source, x, y = transformed_layer(source, layer, progress)
        source, deform_x, deform_y = deform_layer(source, layer, progress)
        x += deform_x
        y += deform_y
        group = groups.get(str(layer.get("group", "")))
        if group:
            layer_canvas = grouped_canvas(
                source,
                x,
                y,
                group,
                progress,
                base.size,
                bool(layer.get("pixel_art", True)),
            )
            frame.alpha_composite(layer_canvas)
        else:
            frame.alpha_composite(source, (x, y))
    if include_effects:
        effects = Image.new("RGBA", base.size)
        draw = ImageDraw.Draw(effects, "RGBA")
        draw_particles(draw, config, particles, progress)
        draw_falling_leaves(draw, config, progress)
        draw_glints(draw, config, progress)
        draw_lights(draw, config, progress)
        frame.alpha_composite(effects)
    if locked_overlay is not None:
        frame.alpha_composite(locked_overlay)
    if include_effects and config.get("frame_fx"):
        frame.alpha_composite(draw_frame_fx(config, progress, base.size, root))
    return frame


def render_frames(config: dict, root: Path) -> tuple[list[Image.Image], int, float]:
    base = Image.open(resolve_path(root, config["base"])).convert("RGBA")
    locked_overlay = None
    if config.get("locked_overlay"):
        locked_overlay = Image.open(resolve_path(root, config["locked_overlay"])).convert("RGBA")
        if locked_overlay.size != base.size:
            raise ValueError("locked_overlay must match the base dimensions")
    duration = float(config.get("duration", 3.0))
    fps = int(config.get("fps", 24))
    if duration <= 0 or fps <= 0:
        raise ValueError("duration and fps must be positive")
    total = round(duration * fps)
    if total < 2:
        raise ValueError("Animation needs at least two frames")
    particles = particle_specs(config)
    frames = [
        compose_frame(config, root, index, total, base, locked_overlay, particles, True).convert("RGB")
        for index in range(total)
    ]
    return frames, fps, duration


def is_pet_layer(layer: dict) -> bool:
    owner = f"{layer.get('name', '')} {layer.get('group', '')}".lower()
    return "pet" in owner


def render_pet_canvas(
    config: dict,
    root: Path,
    frame_index: int,
    total: int,
    canvas_size: tuple[int, int],
) -> Image.Image:
    fps = int(config.get("fps", 24))
    progress = frame_index / total
    groups = group_map(config)
    canvas = Image.new("RGBA", canvas_size)
    for layer in sorted((item for item in config.get("layers", []) if is_pet_layer(item)), key=lambda item: float(item.get("z", 0))):
        source = apply_layer_mask(sprite_frame(layer, root, frame_index, fps), layer, root)
        source, x, y = transformed_layer(source, layer, progress)
        source, deform_x, deform_y = deform_layer(source, layer, progress)
        x += deform_x
        y += deform_y
        group = groups.get(str(layer.get("group", "")))
        if group:
            layer_canvas = grouped_canvas(source, x, y, group, progress, canvas_size, bool(layer.get("pixel_art", True)))
            canvas.alpha_composite(layer_canvas)
        else:
            canvas.alpha_composite(source, (x, y))
    return canvas


def validate_pet_visibility(config: dict, root: Path) -> dict:
    """Require a readable, unobscured pet whose own motion is visible on mobile."""
    if config.get("motion_profile") != "cinematic_scene":
        return {}
    base = Image.open(resolve_path(root, config["base"])).convert("RGBA")
    overlay = Image.open(resolve_path(root, config["locked_overlay"])).convert("RGBA")
    width, height = base.size
    fps = int(config.get("fps", 24))
    total = round(float(config.get("duration", 3.0)) * fps)
    settings = config.get("pet_validation", {})
    names = " ".join(str(layer.get("name", "")).lower() for layer in config.get("layers", []) if is_pet_layer(layer))
    compact_pet = any(token in names for token in ("bird", "spirit", "fairy"))
    min_height_ratio = float(settings.get("min_height_ratio", 0.07 if compact_pet else 0.10))
    max_height_ratio = float(settings.get("max_height_ratio", 0.14 if compact_pet else 0.22))
    min_width_ratio = float(settings.get("min_width_ratio", 0.05 if compact_pet else 0.07))
    min_opaque_area_ratio = float(settings.get("min_opaque_area_ratio", 0.0025 if compact_pet else 0.004))
    max_overlay_overlap_ratio = float(settings.get("max_overlay_overlap_ratio", 0.10))
    min_distinct_silhouettes = int(settings.get("min_distinct_silhouettes", 3))
    min_sprite_silhouette_changed_ratio = float(settings.get("min_sprite_silhouette_changed_ratio", 0.015))
    max_adjacent_sprite_changed_ratio = float(settings.get("max_adjacent_sprite_changed_ratio", 0.35))
    max_fragment_ratio = float(settings.get("max_fragment_ratio", 0.03))

    pet_frames = [render_pet_canvas(config, root, index, total, base.size) for index in range(total)]
    overlay_alpha = overlay.getchannel("A")
    visible_frames = []
    for frame in pet_frames:
        visible = frame.copy()
        visible.putalpha(ImageChops.multiply(frame.getchannel("A"), ImageChops.invert(overlay_alpha)))
        visible_frames.append(visible)

    neutral_alpha = pet_frames[0].getchannel("A")
    visible_neutral_alpha = visible_frames[0].getchannel("A")
    bbox = visible_neutral_alpha.getbbox()
    if bbox is None:
        raise ValueError("pet is fully missing or hidden behind the locked frame/UI")
    bbox_width, bbox_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    height_ratio = bbox_height / height
    width_ratio = bbox_width / width
    opaque_pixels = sum(visible_neutral_alpha.histogram()[17:])
    opaque_area_ratio = opaque_pixels / (width * height)
    original_pixels = max(1, sum(neutral_alpha.histogram()[17:]))
    overlap_ratio = 1 - opaque_pixels / original_pixels

    errors = []
    silhouette_changed_ratio = 0.0
    adjacent_sprite_changed_ratio = 0.0
    distinct_silhouettes = 0
    pet_layers = [layer for layer in config.get("layers", []) if is_pet_layer(layer)]
    groups = group_map(config)
    sprite_layers = [layer for layer in pet_layers if layer.get("sheet")]
    part_tokens = ("ear", "tail", "head", "paw", "leg", "chest", "wing")
    articulated_layers = [
        layer for layer in pet_layers
        if any(token in str(layer.get("name", "")).lower() for token in part_tokens)
        and layer_is_animated(layer, groups)
    ]
    locked_body_layers = [
        layer for layer in pet_layers
        if any(token in str(layer.get("name", "")).lower() for token in ("body", "core"))
        and not layer_is_animated(layer, groups)
    ]
    fragment_reports = [alpha_fragment_report(frame) for frame in visible_frames]
    peak_fragment_ratio = max((report[0] for report in fragment_reports), default=1.0)
    peak_component_count = max((report[1] for report in fragment_reports), default=0)
    if sprite_layers:
        silhouette_hashes = set()
        for layer in sprite_layers:
            sheet = Image.open(resolve_path(root, layer["sheet"])).convert("RGBA")
            columns, rows = int(layer.get("columns", 1)), int(layer.get("rows", 1))
            cell_w, cell_h = sheet.width // columns, sheet.height // rows
            sequence = [int(index) for index in layer.get("sequence", list(range(columns * rows)))]
            cells = []
            for index in sequence:
                left = (index % columns) * cell_w
                top = (index // columns) * cell_h
                alpha = sheet.crop((left, top, left + cell_w, top + cell_h)).getchannel("A")
                cells.append(alpha)
                silhouette_hashes.add(alpha.tobytes())
            neutral = cells[0]
            for alpha in cells[1:]:
                diff = ImageChops.difference(neutral, alpha)
                union = ImageChops.lighter(neutral, alpha)
                union_pixels = max(1, sum(union.histogram()[18:]))
                changed_pixels = sum(diff.histogram()[18:])
                silhouette_changed_ratio = max(silhouette_changed_ratio, changed_pixels / union_pixels)
            for first_alpha, second_alpha in zip(cells, cells[1:]):
                diff = ImageChops.difference(first_alpha, second_alpha)
                union = ImageChops.lighter(first_alpha, second_alpha)
                union_pixels = max(1, sum(union.histogram()[18:]))
                changed_pixels = sum(diff.histogram()[18:])
                adjacent_sprite_changed_ratio = max(adjacent_sprite_changed_ratio, changed_pixels / union_pixels)
        distinct_silhouettes = len(silhouette_hashes)
    if not compact_pet:
        if not sprite_layers and not articulated_layers:
            errors.append("ordinary pets require continuous articulated ears/head/tail/limbs or a smooth sprite; rigid root-only motion is not allowed")
        if articulated_layers and not locked_body_layers:
            errors.append("continuous pet articulation requires a locked pet body/core layer so the feet stay grounded")
        if "dog" in names and not any("tail" in str(layer.get("name", "")).lower() for layer in articulated_layers):
            errors.append("dog animation requires an independently animated tail layer; do not move the whole dog")
        if peak_fragment_ratio > max_fragment_ratio:
            errors.append(
                "pet articulation contains detached or broken silhouette fragments: "
                f"fragment_ratio={peak_fragment_ratio:.4f}, maximum={max_fragment_ratio:.4f}"
            )
        if sprite_layers and distinct_silhouettes < min_distinct_silhouettes:
            errors.append(f"pet action is too rigid: distinct silhouettes={distinct_silhouettes}, minimum={min_distinct_silhouettes}")
        if sprite_layers and silhouette_changed_ratio < min_sprite_silhouette_changed_ratio:
            errors.append(
                "pet action is too rigid: articulated silhouette change "
                f"ratio={silhouette_changed_ratio:.4f}, minimum={min_sprite_silhouette_changed_ratio:.4f}"
            )
        if adjacent_sprite_changed_ratio > max_adjacent_sprite_changed_ratio:
            errors.append(
                "pet sprite steps are too abrupt: adjacent silhouette change "
                f"ratio={adjacent_sprite_changed_ratio:.4f}, maximum={max_adjacent_sprite_changed_ratio:.4f}"
            )
        max_frame_hold = int(settings.get("max_sprite_frame_hold", 3))
        for layer in sprite_layers:
            if int(layer.get("frame_hold", 1)) > max_frame_hold:
                errors.append(
                    f"pet sprite cadence is too stepped: frame_hold={int(layer.get('frame_hold', 1))}, "
                    f"maximum={max_frame_hold}; use continuous articulated parts when possible"
                )
    if height_ratio < min_height_ratio:
        errors.append(f"pet is too small: visible height ratio={height_ratio:.4f}, minimum={min_height_ratio:.4f}")
    if height_ratio > max_height_ratio:
        errors.append(f"pet is too large: visible height ratio={height_ratio:.4f}, maximum={max_height_ratio:.4f}")
    if width_ratio < min_width_ratio:
        errors.append(f"pet is too narrow or unreadable: visible width ratio={width_ratio:.4f}, minimum={min_width_ratio:.4f}")
    if opaque_area_ratio < min_opaque_area_ratio:
        errors.append(f"pet silhouette is too sparse: opaque area ratio={opaque_area_ratio:.5f}")
    if overlap_ratio > max_overlay_overlap_ratio:
        errors.append(f"pet is obscured by frame/UI: overlap ratio={overlap_ratio:.4f}")
    if bbox[0] <= 0 or bbox[1] <= 0 or bbox[2] >= width or bbox[3] >= height:
        errors.append("pet touches the canvas edge and appears cropped")

    preview_size = tuple(map(int, config.get("visibility", {}).get("preview_size", [512, 768])))
    reduced = [frame.resize(preview_size, Image.Resampling.NEAREST) for frame in visible_frames]
    union_alpha = Image.new("L", preview_size)
    for frame in reduced:
        union_alpha = ImageChops.lighter(union_alpha, frame.getchannel("A"))
    union_bbox = union_alpha.getbbox()
    if union_bbox is None:
        errors.append("pet has no visible pixels in the mobile preview")
        union_bbox = (0, 0, preview_size[0], preview_size[1])

    def flatten(frame: Image.Image) -> Image.Image:
        background = Image.new("RGBA", preview_size, (127, 127, 127, 255))
        background.alpha_composite(frame)
        return background.convert("RGB")

    flattened = [flatten(frame).crop(union_bbox) for frame in reduced]
    first = flattened[0]
    peak_mae = 0.0
    peak_changed = 0.0
    for frame in flattened[1:]:
        diff = ImageChops.difference(first, frame)
        peak_mae = max(peak_mae, sum(ImageStat.Stat(diff).mean) / 3)
        peak_changed = max(peak_changed, changed_ratio(diff, threshold=4))
    min_peak_mae = float(settings.get("min_peak_local_mae", 2.5))
    min_peak_changed = float(settings.get("min_peak_local_changed_ratio", 0.04))
    if peak_mae < min_peak_mae or peak_changed < min_peak_changed:
        errors.append(
            "pet motion is not independently visible on mobile: "
            f"local_mae={peak_mae:.4f}, changed_ratio={peak_changed:.4f}"
        )
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "visible_bbox": list(bbox),
        "height_ratio": round(height_ratio, 6),
        "width_ratio": round(width_ratio, 6),
        "opaque_area_ratio": round(opaque_area_ratio, 6),
        "frame_overlap_ratio": round(overlap_ratio, 6),
        "mobile_peak_local_mae": round(peak_mae, 6),
        "mobile_peak_local_changed_ratio": round(peak_changed, 6),
        "distinct_silhouettes": distinct_silhouettes,
        "sprite_silhouette_changed_ratio": round(silhouette_changed_ratio, 6),
        "adjacent_sprite_changed_ratio": round(adjacent_sprite_changed_ratio, 6),
        "continuous_articulated_parts": len(articulated_layers),
        "locked_body_layers": len(locked_body_layers),
        "peak_fragment_ratio": round(peak_fragment_ratio, 6),
        "peak_component_count": peak_component_count,
    }


def validate_coherent_high(config: dict) -> None:
    profile = config.get("motion_profile")
    if profile == "high":
        raise ValueError("legacy motion_profile=high is discontinuity-prone; use coherent_high")
    if profile != "coherent_high":
        return
    duration = float(config.get("duration", 3.0))
    fps = int(config.get("fps", 24))
    layers = config.get("layers", [])
    groups = group_map(config)
    names = " ".join(str(layer.get("name", "")).lower() for layer in layers)
    character_groups = [name for name in groups if "character" in name.lower()]
    pet_groups = [name for name in groups if "pet" in name.lower()]
    pet_root_groups = [name for name in pet_groups if name.lower() == "pet_root" or name.lower().endswith("_pet_root")]
    moving_groups = sum(has_transform(group.get("motion", {})) for group in groups.values())
    local_channels = sum("sheet" in layer or has_transform(layer.get("motion", {})) for layer in layers)
    effect_channels = bool(config.get("glints")) + bool(config.get("lights")) + bool(config.get("particles"))
    errors = []
    if abs(duration - 3.0) > 1e-6:
        errors.append("coherent high motion requires duration=3.0")
    if fps < 24:
        errors.append("coherent high motion requires fps>=24")
    if not config.get("reference") or not config.get("locked_overlay"):
        errors.append("coherent high motion requires reference and locked_overlay")
    if not character_groups or not pet_groups:
        errors.append("coherent high motion requires character_root and pet_root groups")
    if not any(token in names for token in ("body", "character_core")):
        errors.append("coherent high motion requires a separated body/character_core layer")
    if not any(token in names for token in ("face", "blink", "eye")):
        errors.append("coherent high motion requires a face/blink/eye layer")
    if not any(token in names for token in ("hair", "cloth", "skirt", "dress", "scarf", "coat")):
        errors.append("coherent high motion requires a hair or clothing layer")
    if "pet" not in names:
        errors.append("coherent high motion requires a pet layer")
    if moving_groups + local_channels + effect_channels < 6:
        errors.append("coherent high motion requires at least six visible submotions")
    if any("z" not in layer for layer in layers):
        errors.append("every coherent layer requires an explicit z value")
    for owner, motion in [
        *((f"group {name}", group.get("motion", {})) for name, group in groups.items()),
        *((f"layer {layer.get('name', '<unnamed>')}", layer.get("motion", {})) for layer in layers),
    ]:
        cycles = float(motion.get("cycles", 1))
        if abs(cycles - round(cycles)) > 1e-6:
            errors.append(f"{owner} cycles must be an integer for a seamless rest pose")
        if abs(float(motion.get("phase", 0))) > 1e-9:
            errors.append(f"{owner} must use lag instead of phase")
    for layer in layers:
        if "sheet" in layer:
            sequence = layer.get("sequence", [])
            if not sequence or sequence[0] != sequence[-1]:
                errors.append(f"sprite layer {layer.get('name', '<unnamed>')} must start and end on the same rest cell")
    if errors:
        raise ValueError("; ".join(errors))


def alpha_coverage(alpha: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = alpha.crop(box)
    return ImageStat.Stat(crop).mean[0] / 255 if crop.width and crop.height else 0.0


def validate_frame_integrity(config: dict, root: Path) -> dict:
    """Reject incomplete frame overlays and FRAME_FX that leak into the scene."""
    if config.get("motion_profile") != "cinematic_scene":
        return {}
    overlay = Image.open(resolve_path(root, config["locked_overlay"])).convert("RGBA")
    width, height = overlay.size
    alpha = overlay.getchannel("A")
    settings = config.get("frame_integrity", {})
    edge_band = max(8, min(int(settings.get("edge_band_px", round(width * 0.08))), width // 3, height // 3))
    min_edge = float(settings.get("min_edge_coverage", 0.10))
    min_corner = float(settings.get("min_corner_coverage", 0.12))
    min_segment = float(settings.get("min_segment_coverage", 0.02))

    edge_boxes = {
        "top": (0, 0, width, edge_band),
        "bottom": (0, height - edge_band, width, height),
        "left": (0, 0, edge_band, height),
        "right": (width - edge_band, 0, width, height),
    }
    corner_boxes = {
        "top_left": (0, 0, edge_band, edge_band),
        "top_right": (width - edge_band, 0, width, edge_band),
        "bottom_left": (0, height - edge_band, edge_band, height),
        "bottom_right": (width - edge_band, height - edge_band, width, height),
    }
    edge_report = {name: alpha_coverage(alpha, box) for name, box in edge_boxes.items()}
    corner_report = {name: alpha_coverage(alpha, box) for name, box in corner_boxes.items()}
    errors = [f"frame {name} edge coverage is incomplete ({ratio:.4f})" for name, ratio in edge_report.items() if ratio < min_edge]
    errors.extend(f"frame {name} corner coverage is incomplete ({ratio:.4f})" for name, ratio in corner_report.items() if ratio < min_corner)

    segment_count = max(4, int(settings.get("segments_per_edge", 8)))
    missing_segments = []
    for index in range(segment_count):
        x1, x2 = round(width * index / segment_count), round(width * (index + 1) / segment_count)
        y1, y2 = round(height * index / segment_count), round(height * (index + 1) / segment_count)
        for name, box in (
            (f"top[{index}]", (x1, 0, x2, edge_band)),
            (f"bottom[{index}]", (x1, height - edge_band, x2, height)),
            (f"left[{index}]", (0, y1, edge_band, y2)),
            (f"right[{index}]", (width - edge_band, y1, width, y2)),
        ):
            if alpha_coverage(alpha, box) < min_segment:
                missing_segments.append(name)
    if missing_segments:
        errors.append("frame has missing edge segments: " + ", ".join(missing_segments))

    side_band = max(edge_band, int(settings.get("fx_side_band_px", round(width * 0.125))))
    top_bottom_band = max(edge_band, int(settings.get("fx_top_bottom_band_px", round(height * 0.14))))

    def in_frame_safe_area(x: int, y: int) -> bool:
        return x <= side_band or x >= width - side_band or y <= top_bottom_band or y >= height - top_bottom_band

    allowed_types = {"gem_glint", "rail_light", "icon_pulse"}
    for index, item in enumerate(config.get("frame_fx", [])):
        kind = str(item.get("type", "gem_glint"))
        if kind not in allowed_types:
            errors.append(f"frame_fx[{index}] has unsupported type {kind!r}")
            continue
        points = item.get("points") if kind == "rail_light" else [[item.get("x"), item.get("y")]]
        if kind == "rail_light" and (not isinstance(points, list) or len(points) < 2):
            errors.append(f"frame_fx[{index}] rail_light requires at least two points")
            continue
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2 or None in point:
                errors.append(f"frame_fx[{index}] has an invalid point")
                continue
            x, y = map(int, point)
            if not (0 <= x < width and 0 <= y < height):
                errors.append(f"frame_fx[{index}] point {(x, y)} is outside the canvas")
            elif not in_frame_safe_area(x, y):
                errors.append(f"frame_fx[{index}] point {(x, y)} leaks outside the frame safe area")
        cycles = float(item.get("cycles", 1))
        if abs(cycles - round(cycles)) > 1e-6:
            errors.append(f"frame_fx[{index}] cycles must be an integer for a seamless loop")

    if config.get("frame_fx_mask"):
        mask = Image.open(resolve_path(root, config["frame_fx_mask"])).convert("L")
        if mask.size != overlay.size:
            errors.append("frame_fx_mask must match the frame-ui dimensions")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "edge_band_px": edge_band,
        "edge_coverage": {key: round(value, 6) for key, value in edge_report.items()},
        "corner_coverage": {key: round(value, 6) for key, value in corner_report.items()},
        "frame_fx_count": len(config.get("frame_fx", [])),
    }


def validate_cinematic_scene(config: dict) -> None:
    if config.get("motion_profile") != "cinematic_scene":
        return
    duration = float(config.get("duration", 3.0))
    fps = int(config.get("fps", 24))
    layers = config.get("layers", [])
    groups = group_map(config)
    pet_groups = [name for name in groups if "pet" in name.lower()]
    pet_root_groups = [name for name in pet_groups if name.lower() == "pet_root" or name.lower().endswith("_pet_root")]
    pet_layers = [layer for layer in layers if is_pet_layer(layer)]
    character_motion = config.get("character_motion", {})
    allow_secondary_motion = bool(character_motion.get("enabled", config.get("allow_character_motion", False)))
    allow_face_blink = bool(character_motion.get("allow_face_blink", False))
    allow_pet_blink = bool(character_motion.get("allow_pet_blink", False))
    safe_secondary_tokens = ("hair_tip", "hair_end", "dress_hem", "skirt_hem", "cloth_hem", "scarf_tail")
    errors = []
    if abs(duration - 3.0) > 1e-6:
        errors.append("cinematic_scene requires duration=3.0")
    if fps < 24:
        errors.append("cinematic_scene requires fps>=24")
    if not config.get("reference") or not config.get("locked_overlay"):
        errors.append("cinematic_scene requires reference and locked_overlay")
    if not pet_root_groups or not pet_layers:
        errors.append("cinematic_scene requires a pet_root group and a pet layer")
    if any("z" not in layer for layer in layers):
        errors.append("every cinematic layer requires an explicit z value")

    pet_action = any(layer_is_animated(layer, groups) for layer in pet_layers)
    if not pet_action:
        errors.append("cinematic_scene requires one visible pet action")
    pet_amplitudes = []
    for name in pet_groups:
        motion = groups[name].get("motion", {})
        pet_amplitudes.extend(abs(float(motion.get(key, 0))) for key in ("bob_x", "bob_y"))
        pet_amplitudes.append(abs(float(motion.get("sway_degrees", 0))) * 1.5)
    for layer in pet_layers:
        motion = layer.get("motion", {})
        pet_amplitudes.extend(abs(float(motion.get(key, 0))) for key in ("bob_x", "bob_y"))
        pet_amplitudes.append(abs(float(motion.get("sway_degrees", 0))) * 1.5)
        deform = layer.get("deform", {})
        pet_amplitudes.extend(abs(float(deform.get(key, 0))) for key in ("amplitude_x", "amplitude_y"))
    pet_has_sprite = any("sheet" in layer for layer in pet_layers)
    min_pet_motion = float(config.get("pet_validation", {}).get("min_translation_px", 10))
    pet_names = " ".join(str(layer.get("name", "")).lower() for layer in pet_layers)
    compact_pet = any(token in pet_names for token in ("bird", "spirit", "fairy"))
    max_root_translation = max(
        [
            abs(float(groups[name].get("motion", {}).get(key, 0)))
            for name in pet_root_groups
            for key in ("bob_x", "bob_y")
        ]
        or [0]
    )
    max_root_sway = max(
        [abs(float(groups[name].get("motion", {}).get("sway_degrees", 0))) for name in pet_root_groups] or [0]
    )
    if not compact_pet:
        allowed_translation = float(config.get("pet_validation", {}).get("max_root_translation_px", 6))
        allowed_sway = float(config.get("pet_validation", {}).get("max_root_sway_degrees", 2.5))
        if max_root_translation > allowed_translation or max_root_sway > allowed_sway:
            errors.append(
                "ordinary pet root motion is too rigid; keep the body anchored and animate ears/head/tail/limbs "
                f"(translation={max_root_translation:g}px, sway={max_root_sway:g}deg)"
            )
    if not pet_has_sprite and max(pet_amplitudes or [0]) < min_pet_motion:
        errors.append(f"transform-only pet motion must reach {min_pet_motion:g}px-equivalent so it remains visible on mobile")

    for layer in layers:
        name = str(layer.get("name", "")).lower()
        group_name = str(layer.get("group", "")).lower()
        owner = f"{name} {group_name}"
        animated = layer_is_animated(layer, groups)
        layer_is_pet = "pet" in owner
        if not animated:
            continue
        if layer_is_pet and any(token in owner for token in ("blink", "eye")) and not allow_pet_blink:
            errors.append(f"pet blink layer {layer.get('name', '<unnamed>')} is disabled by default")
            continue
        if layer_is_pet:
            continue
        if any(token in owner for token in ("body", "character_core", "head_root")):
            errors.append(f"locked body layer {layer.get('name', '<unnamed>')} must not animate")
            continue
        if any(token in owner for token in ("face", "blink", "eye", "bang", "earring")) and not allow_face_blink:
            errors.append(f"face-adjacent layer {layer.get('name', '<unnamed>')} must remain locked")
            continue
        if any(token in owner for token in ("hair", "cloth", "skirt", "dress", "scarf")):
            if not allow_secondary_motion:
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} is not enabled")
                continue
            if not any(token in owner for token in safe_secondary_tokens):
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} is not a safe tip/hem layer")
                continue
            motions = [layer.get("motion", {}), groups.get(str(layer.get("group", "")), {}).get("motion", {})]
            max_translation = max(abs(float(motion.get(key, 0))) for motion in motions for key in ("bob_x", "bob_y"))
            max_sway = max(abs(float(motion.get("sway_degrees", 0))) for motion in motions)
            deform = layer.get("deform", {})
            if deform and str(deform.get("type", "tip_sway")) != "tip_sway":
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} uses an unsupported deformation")
            if abs(float(deform.get("amplitude_x", 0))) > float(character_motion.get("max_translation_px", 9)):
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} exceeds safe tip deformation")
            if max_translation > float(character_motion.get("max_translation_px", 9)):
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} exceeds safe translation")
            if max_sway > float(character_motion.get("max_sway_degrees", 4)):
                errors.append(f"secondary character layer {layer.get('name', '<unnamed>')} exceeds safe sway")
        elif any(token in owner for token in ("character", "person", "arm", "hand", "leg", "torso")):
            errors.append(f"locked character layer {layer.get('name', '<unnamed>')} must not animate")

    environmental_channels = sum(bool(config.get(key)) for key in ("water_ripples", "falling_leaves", "glints", "particles"))
    if environmental_channels < 1:
        errors.append("cinematic_scene requires at least one semantic environmental motion channel")
    if not config.get("lights"):
        errors.append("cinematic_scene requires a UI/status light action")
    frame_fx = config.get("frame_fx", [])
    if len(frame_fx) < 2:
        errors.append("cinematic_scene requires at least two staggered local frame_fx actions")
    elif not any(str(item.get("type", "gem_glint")) == "gem_glint" for item in frame_fx):
        errors.append("cinematic_scene requires at least one frame gem_glint sparkle")
    if config.get("water_ripples") and not bool(config.get("scene_environment", {}).get("has_water_or_reflection", False)):
        errors.append("water_ripples may only be used when scene_environment.has_water_or_reflection=true; never warp bushes or generic scenery")
    if config.get("water_ripples") and max(
        max(abs(float(item.get("amplitude_x", 0))), abs(float(item.get("amplitude_y", 0))))
        for item in config["water_ripples"]
    ) < 6:
        errors.append("water ripple displacement must reach at least 6px")
    if config.get("falling_leaves") and not bool(config.get("scene_environment", {}).get("allow_falling_leaves", False)):
        errors.append("falling_leaves are disabled by default; enable them only for an explicit user request")
    if bool(config.get("scene_wind", {}).get("enabled", False)):
        hair_tip_layers = [
            layer for layer in layers
            if "hair_tip" in str(layer.get("name", "")).lower() or "hair_end" in str(layer.get("name", "")).lower()
        ]
        if not hair_tip_layers:
            errors.append("wind-enabled long-hair scenes require a safe hair_tip/hair_end layer")
        elif not any(str(layer.get("deform", {}).get("type", "")) == "tip_sway" for layer in hair_tip_layers):
            errors.append("wind-enabled hair tips require continuous tip_sway deformation; rigid whole-layer rotation is not allowed")
    for index, group in enumerate(config.get("falling_leaves", [])):
        if "seed" not in group:
            errors.append(f"falling_leaves[{index}] requires a fixed seed for repeatable output")
        if int(group.get("count", 0)) < 5:
            errors.append(f"falling_leaves[{index}] requires at least 5 leaves for staggered depth")
        if int(group.get("size_max", 0)) <= int(group.get("size_min", 0)):
            errors.append(f"falling_leaves[{index}] requires a real size range for depth variation")
        if len(group.get("colors", [])) < 2:
            errors.append(f"falling_leaves[{index}] requires at least two leaf colors")
        if str(group.get("leaf_style", "")) not in {"autumn", "broadleaf"}:
            errors.append(f"falling_leaves[{index}] requires leaf_style=autumn or broadleaf")
        if int(group.get("size_min", 0)) < 8 or int(group.get("size_max", 0)) < 12:
            errors.append(f"falling_leaves[{index}] is too small to read as a leaf on mobile")
        if abs(float(group.get("fall_y", 0))) < 240:
            errors.append(f"falling_leaves[{index}] needs at least 240px of vertical fall")
        if int(group.get("opacity", 0)) < 180:
            errors.append(f"falling_leaves[{index}] opacity is too low for mobile visibility")
    if config.get("glints") and max(float(item.get("pulse_radius", 0)) for item in config["glints"]) < 4:
        errors.append("at least one glint pulse_radius must reach 4px")

    motion_owners = [
        *((f"group {name}", group.get("motion", {})) for name, group in groups.items()),
        *((f"layer {layer.get('name', '<unnamed>')}", layer.get("motion", {})) for layer in layers),
        *((f"deform {layer.get('name', '<unnamed>')}", layer.get("deform", {})) for layer in layers if layer.get("deform")),
        *(("water_ripple", item) for item in config.get("water_ripples", [])),
    ]
    for owner, motion in motion_owners:
        cycles = float(motion.get("cycles", 1))
        if abs(cycles - round(cycles)) > 1e-6:
            errors.append(f"{owner} cycles must be an integer for a seamless rest pose")
    for layer in layers:
        if "sheet" in layer:
            sequence = layer.get("sequence", [])
            if not sequence or sequence[0] != sequence[-1]:
                errors.append(f"sprite layer {layer.get('name', '<unnamed>')} must start and end on the same rest cell")
    if errors:
        raise ValueError("; ".join(errors))


def validate_motion_profile(config: dict) -> None:
    validate_coherent_high(config)
    validate_cinematic_scene(config)


def changed_ratio(diff: Image.Image, threshold: int = 2) -> float:
    histogram = diff.convert("L").histogram()
    return sum(histogram[threshold + 1 :]) / (diff.width * diff.height)


def validate_continuity(config: dict, root: Path) -> dict:
    if config.get("motion_profile") not in {"coherent_high", "cinematic_scene"}:
        return {}
    base = Image.open(resolve_path(root, config["base"])).convert("RGBA")
    reference = Image.open(resolve_path(root, config["reference"])).convert("RGBA")
    locked_overlay = Image.open(resolve_path(root, config["locked_overlay"])).convert("RGBA")
    if base.size != reference.size or base.size != locked_overlay.size:
        raise ValueError("base, reference, and locked_overlay must have identical dimensions")
    fps = int(config.get("fps", 24))
    total = round(float(config.get("duration", 3.0)) * fps)
    groups = group_map(config)
    rest = compose_frame(config, root, 0, total, base, locked_overlay, [], False).convert("RGB")
    reference_rgb = reference.convert("RGB")
    rest_diff = ImageChops.difference(rest, reference_rgb)
    rest_mae = sum(ImageStat.Stat(rest_diff).mean) / 3
    rest_changed = changed_ratio(rest_diff)

    coverage = Image.new("L", base.size)
    for layer in sorted(config.get("layers", []), key=lambda item: float(item.get("z", 0))):
        if not layer_is_animated(layer, groups):
            continue
        source = apply_layer_mask(sprite_frame(layer, root, 0, fps), layer, root)
        source, x, y = transformed_layer(source, layer, 0.0)
        source, deform_x, deform_y = deform_layer(source, layer, 0.0)
        x += deform_x
        y += deform_y
        group = groups.get(str(layer.get("group", "")))
        if group:
            alpha = grouped_canvas(source, x, y, group, 0.0, base.size, bool(layer.get("pixel_art", True))).getchannel("A")
        else:
            alpha = Image.new("L", base.size)
            alpha.paste(source.getchannel("A"), (x, y))
        coverage = ImageChops.lighter(coverage, alpha)
    if coverage.getbbox() is None:
        raise ValueError("animated layer coverage is empty")
    base_reference_diff = ImageChops.difference(base.convert("RGB"), reference_rgb)
    clean_plate_mae = sum(ImageStat.Stat(base_reference_diff, mask=coverage).mean) / 3
    limits = config.get("continuity", {})
    if rest_mae > float(limits.get("rest_max_mae", 1.0)):
        raise ValueError(f"rest frame does not reconstruct the mother card: mae={rest_mae:.4f}")
    if rest_changed > float(limits.get("rest_max_changed_ratio", 0.02)):
        raise ValueError(f"rest frame seam area is too large: ratio={rest_changed:.6f}")
    if clean_plate_mae < float(limits.get("clean_plate_min_mae", 3.0)):
        raise ValueError(f"base still contains animated objects; clean plate mae={clean_plate_mae:.4f}")
    return {
        "rest_mae": round(rest_mae, 6),
        "rest_changed_ratio": round(rest_changed, 8),
        "clean_plate_mae": round(clean_plate_mae, 6),
    }


def validate_visibility(config: dict, frames: list[Image.Image]) -> dict:
    """Reject technically changing loops that still look static at mobile size."""
    if config.get("motion_profile") != "cinematic_scene":
        return {}
    settings = config.get("visibility", {})
    preview_size = settings.get("preview_size", [512, 768])
    if len(preview_size) != 2 or min(map(int, preview_size)) <= 0:
        raise ValueError("visibility.preview_size must be [width, height]")
    size = tuple(map(int, preview_size))
    reduced = [frame.resize(size, Image.Resampling.LANCZOS).convert("RGB") for frame in frames]
    first = reduced[0]
    peak_mae = 0.0
    peak_changed = 0.0
    zero_adjacent = 0
    previous = first
    for index, frame in enumerate(reduced):
        diff = ImageChops.difference(first, frame)
        peak_mae = max(peak_mae, sum(ImageStat.Stat(diff).mean) / 3)
        peak_changed = max(peak_changed, changed_ratio(diff, threshold=4))
        if index and ImageChops.difference(previous, frame).getbbox() is None:
            zero_adjacent += 1
        previous = frame
    min_peak_mae = float(settings.get("min_peak_mae", 0.18))
    min_changed_ratio = float(settings.get("min_changed_ratio", 0.0015))
    if peak_mae < min_peak_mae or peak_changed < min_changed_ratio:
        raise ValueError(
            "cinematic motion is not visible enough at mobile size: "
            f"peak_mae={peak_mae:.4f}, changed_ratio={peak_changed:.6f}"
        )
    if zero_adjacent:
        raise ValueError(f"animation contains {zero_adjacent} duplicate adjacent frames")
    return {
        "preview_size": list(size),
        "peak_mae": round(peak_mae, 6),
        "peak_changed_ratio": round(peak_changed, 8),
        "duplicate_adjacent_frames": zero_adjacent,
    }


def save_mp4(frames: list[Image.Image], fps: int, output: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to write MP4")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="micro-video-") as temp_dir:
        temp = Path(temp_dir)
        for index, frame in enumerate(frames):
            # BMP avoids rare PNG chunk/decode failures when ffmpeg reads long image sequences.
            frame.save(temp / f"frame_{index:04d}.bmp")
        command = [
            "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
            "-i", str(temp / "frame_%04d.bmp"), "-an", "-c:v", "libx264",
            "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart",
            str(output),
        ]
        subprocess.run(command, check=True)


def probe_mp4(output: Path, expected_frames: int, expected_fps: int, expected_size: tuple[int, int]) -> dict:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is required to validate MP4")
    command = [
        "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
        "-of", "json", str(output),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    video_streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        raise ValueError("MP4 must contain exactly one video stream and no audio stream")
    stream = video_streams[0]
    numerator, denominator = map(int, stream.get("avg_frame_rate", "0/1").split("/"))
    actual_fps = numerator / denominator if denominator else 0
    actual_frames = int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0)
    actual_size = (int(stream.get("width", 0)), int(stream.get("height", 0)))
    expected_even_size = (expected_size[0] // 2 * 2, expected_size[1] // 2 * 2)
    if stream.get("codec_name") != "h264":
        raise ValueError(f"MP4 codec must be h264, got {stream.get('codec_name')}")
    if actual_frames != expected_frames:
        raise ValueError(f"MP4 frame count mismatch: expected {expected_frames}, got {actual_frames}")
    if abs(actual_fps - expected_fps) > 1e-6:
        raise ValueError(f"MP4 fps mismatch: expected {expected_fps}, got {actual_fps}")
    if actual_size != expected_even_size:
        raise ValueError(f"MP4 dimensions mismatch: expected {expected_even_size}, got {actual_size}")
    expected_duration = expected_frames / expected_fps
    actual_duration = float(data.get("format", {}).get("duration", 0))
    if abs(actual_duration - expected_duration) > 1 / expected_fps:
        raise ValueError(f"MP4 duration mismatch: expected {expected_duration}, got {actual_duration}")
    if stream.get("pix_fmt") != "yuv420p":
        raise ValueError(f"MP4 pixel format must be yuv420p, got {stream.get('pix_fmt')}")
    return {
        "codec": "h264",
        "pixel_format": "yuv420p",
        "frames": actual_frames,
        "fps": actual_fps,
        "size": list(actual_size),
        "duration": round(actual_duration, 6),
        "audio_streams": 0,
    }


def save_gif(frames: list[Image.Image], fps: int, output: Path, preview_fps: int = 12) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    target_fps = max(1, min(fps, int(preview_fps)))
    if target_fps < 12 and fps >= 12:
        raise ValueError("GIF preview must use at least 12 fps")
    target_count = max(2, round(len(frames) * target_fps / fps))
    indices = [min(len(frames) - 1, round(index * fps / target_fps)) for index in range(target_count)]
    palette_frames = [frames[index].convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for index in indices]
    total_centiseconds = round((len(frames) / fps) * 100)
    base_centiseconds, extra_centiseconds = divmod(total_centiseconds, len(palette_frames))
    frame_centiseconds = [base_centiseconds] * len(palette_frames)
    for index in range(extra_centiseconds):
        frame_centiseconds[round(index * len(palette_frames) / extra_centiseconds) % len(palette_frames)] += 1
    durations_ms = [value * 10 for value in frame_centiseconds]
    palette_frames[0].save(
        output,
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    if len(palette_frames) < 36 and len(frames) >= 72:
        raise ValueError("3-second GIF preview must contain at least 36 frames")
    actual_duration = sum(durations_ms) / 1000
    return {"frames": len(palette_frames), "fps": round(len(palette_frames) / actual_duration, 6), "duration": round(actual_duration, 6)}


def safe_config(base: Path, output_mp4: Path, output_gif: Path | None, duration: float, fps: int) -> dict:
    with Image.open(base) as image:
        width, height = image.size
    config = {
        "base": str(base),
        "duration": duration,
        "fps": fps,
        "motion_profile": "draft",
        "output_mp4": str(output_mp4),
        "glints": [
            {"x": round(width * 0.73), "y": round(height * 0.20), "radius": max(4, round(width * 0.012)), "color": "#fff2b2", "cycles": 2, "phase": 0.0},
            {"x": round(width * 0.58), "y": round(height * 0.60), "radius": max(3, round(width * 0.009)), "color": "#ffffff", "cycles": 2, "phase": 0.45},
            {"x": round(width * 0.22), "y": round(height * 0.72), "radius": max(3, round(width * 0.008)), "color": "#ffd6ef", "cycles": 1, "phase": 0.7},
        ],
        "lights": [
            {"x": round(width * 0.93), "y": round(height * 0.04), "radius": max(3, round(width * 0.008)), "color": "#76ff9b", "cycles": 3, "phase": 0.0}
        ],
        "particles": [
            {
                "seed": 68,
                "count": 16,
                "region": [round(width * 0.08), round(height * 0.12), round(width * 0.92), round(height * 0.90)],
                "color": "#fff5d6",
                "radius": [1, max(2, round(width * 0.006))],
                "drift_x": max(4, round(width * 0.018)),
                "drift_y": max(7, round(height * 0.024)),
                "cycles": 1,
                "opacity": 150,
            }
        ],
    }
    if output_gif is not None:
        config["output_gif"] = str(output_gif)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path, help="JSON configuration file")
    parser.add_argument("--safe-base", type=Path, help="Draft-only flat card motion; not valid for final high-motion delivery")
    parser.add_argument("--output-mp4", type=Path, help="MP4 path for --safe-base")
    parser.add_argument("--output-gif", type=Path, help="Optional GIF path for --safe-base")
    parser.add_argument("--duration", type=float, default=3.0, help="Duration for --safe-base")
    parser.add_argument("--fps", type=int, default=24, help="Frame rate for --safe-base")
    args = parser.parse_args()
    if bool(args.config) == bool(args.safe_base):
        parser.error("provide either CONFIG.json or --safe-base CARD.png")
    if args.safe_base:
        base = args.safe_base.resolve()
        output_mp4 = (args.output_mp4 or base.with_name(f"{base.stem}-loop.mp4")).resolve()
        output_gif = args.output_gif.resolve() if args.output_gif else None
        config = safe_config(base, output_mp4, output_gif, args.duration, args.fps)
        root = base.parent
    else:
        config_path = args.config.resolve()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        root = config_path.parent
    validate_motion_profile(config)
    frame_integrity = validate_frame_integrity(config, root)
    pet_validation = validate_pet_visibility(config, root)
    continuity = validate_continuity(config, root)
    frames, fps, duration = render_frames(config, root)
    visibility = validate_visibility(config, frames)

    outputs = {}
    media_validation = {}
    if config.get("output_mp4"):
        mp4 = resolve_path(root, config["output_mp4"])
        save_mp4(frames, fps, mp4)
        outputs["mp4"] = str(mp4)
        media_validation["mp4"] = probe_mp4(mp4, len(frames), fps, frames[0].size)
    if config.get("output_gif"):
        gif = resolve_path(root, config["output_gif"])
        media_validation["gif"] = save_gif(frames, fps, gif, int(config.get("gif_fps", 12)))
        outputs["gif"] = str(gif)
    if not outputs:
        raise ValueError("Set output_mp4 and/or output_gif")

    print(json.dumps({"motion_profile": config.get("motion_profile", "custom"), "frame_integrity": frame_integrity, "pet_validation": pet_validation, "continuity": continuity, "visibility": visibility, "media_validation": media_validation, "frames": len(frames), "fps": fps, "duration": duration, "size": frames[0].size, "outputs": outputs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
