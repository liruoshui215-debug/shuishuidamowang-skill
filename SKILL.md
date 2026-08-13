---
name: shuishuidamowang-v53-final-locked
description: Creates a retro CRT/Windows 98 style photo animation with a polished desktop shell, click-triggered Shui Analyzer, source-locked popup images, a more pixelized identity card portrait, richer asymmetric popup composition, faster decoding rhythm, and a readable final hold state that stays open after the absurd title is revealed.
---

# shuishuidamowang v53 — Final Locked

## Version intent

V53 Final Locked is the **locked final release** built on top of V52/V53 polish.

This version does **not** replace the proven core structure. The verified mechanism stays locked:

**desktop → cursor move/click → 水的分析器触发 → burst popups → fast decode → absurd title reveal → completed final hold**

V53 only refines the visual finish and readability:
- make the desktop shell feel more like a believable Chinese Win98 environment;
- make the first burst composition less plain and more aesthetically arranged;
- keep popup positions more asymmetrical and lively instead of too fixed;
- keep the identity card portrait more obviously pixel/cartoon-like;
- preserve the under-4-second pacing and final hold readability.

## 1. Hard lock: do not change the proven core behavior

The following behaviors are now considered stable and should remain unchanged unless a future version is explicitly experimental:
- 4:3 landscape output;
- short visible cursor move followed by a clear click;
- popup burst triggered by **水的分析器** rather than random photo clicking;
- no slide-in motion;
- fast progress bar;
- 2–3 detail extractors;
- absurd identity title generation;
- final completed state remains open and does not retreat.

## 2. Duration target

### Required duration
- preferred total duration: **3.2–3.8 seconds**;
- recommended default target: **3.4–3.6 seconds**;
- 24 fps.

### Intent
The whole piece must stay short enough for social/live conversion while still making the reveal readable.

## 3. Final hold remains mandatory

### Rule
After the identity/title is revealed, the interface must remain in the **completed expanded state**.

### Required behavior
- do **not** retreat to the empty desktop;
- do **not** shut all windows;
- do **not** cut away immediately;
- the final title must stay readable.

### Required final hold duration
- preferred final hold: **0.9–1.2 seconds**;
- minimum acceptable hold: **0.7 seconds**.

### Final hold windows
The final state should keep visible, space permitting:
- main preview window;
- 人物身份卡;
- 分析进度;
- 水的分析器;
- 2–3 detail extractors;
- palette / properties / support windows.

## 4. Final hold must stay alive, not frozen dead

Allowed micro-motion during the hold:
- CRT scanline shimmer;
- subtle cursor blink / idle flicker;
- tiny status light flicker;
- progress bar resting at 100%;
- gentle monitor noise.

Avoid:
- retreat animation;
- repeated loop resets;
- large window motion;
- scanning face box animation.

## 5. Progress bar and decode rhythm

The progress bar is only a rhythm device and should complete quickly.

### Recommended milestones
- 12% 正在读取人物样本…
- 34% 正在建立像素档案…
- 58% 正在检测异常特征…
- 76% 正在匹配职业身份…
- 90% **正在破译头衔…**
- 100% **头衔破译完成**

### Rule
- progress should feel brisk, not slow or suspenseful;
- identity card reveal should happen early;
- the final hold must happen soon enough to read the title.

## 6. Identity card is a shareable comedic feature

### Required behavior
- the identity card should appear early and remain through the ending;
- it must show a **clear pixel portrait**;
- the pixel portrait should feel slightly more cartoon / low-res than a normal crop;
- name / status / absurd title must remain readable in the final hold.

### Identity portrait style rule
The portrait should follow:

**head/shoulder crop → proportional crop → low-resolution reduction → 12–18 color quantization → nearest-neighbor enlargement**

The result should look like a retro pixel avatar, not just a tiny realistic thumbnail.

## 7. Detail extractor logic

### Core separation rule
**Identity card = person**  
**detail extractors = object / texture / environment / accessory**

### Priority order
Prioritize 2–3 extractors from:
1. accessories (earrings, necklace, bracelet, bag hardware)
2. phone / phone-case / handheld object details
3. clothing texture / collar / folds / print
4. environment texture (wood grain, wall, tile, pavement)
5. light source / reflection / signage / water reflection
6. landscape detail (ridge, snow texture, backpack, path, rock surface)

### Avoid strongly
If the identity card already uses the head crop, then detail extractors should **not** use:
- full-face crops;
- scalp-only crops;
- hair-top crops;
- empty forehead fragments;
- blank dark corners;
- empty flat wall fragments unless the texture itself is clearly interesting.

## 8. Window composition should feel more designed

This is a key V53 polish point.

### Composition rule
The popup burst should feel like an intentional **clustered desktop composition**, not a rigid grid.

### Required behavior
- allow windows to appear on both left and right sides;
- keep the first major popup richer, less plain, and visually anchored;
- use asymmetrical spacing so the composition feels lively;
- keep enough negative space so the subject remains readable.

### Suggested structure
- main preview window = primary focal anchor;
- identity card = medium secondary window;
- progress/analyzer window = compact support;
- 2–3 detail extractors = small asymmetric satellites;
- palette / properties windows = visual balance helpers.

### Avoid
- all windows stacking in one identical column;
- overly fixed right-side-only layouts;
- repetitive equal spacing that feels mechanical.

## 9. Desktop shell polish remains mandatory

### Required desktop presence
- visible Win98-style desktop icons with cleaner shapes;
- classic left icon stack;
- believable taskbar, start button, and system clock;
- icon labels legible;
- no empty or rough cheap-looking desktop.

### Preferred desktop icon pool
Use 4–7 icons chosen from:
- 我的电脑
- 我的文档
- 回收站
- 图片
- 工具箱
- 画图
- Internet Explorer
- 水的分析器
- 相机导入

### Aesthetic note
Icons should feel more polished than rough placeholder blocks.

## 10. Source-lock / anti-distortion rule

All popup imagery must remain geometry-safe.

### Rule
All ordinary popup images must come from the same mother frame using:
- proportional crop;
- contain or cover-crop fit;
- no non-uniform stretching;
- no squeezed or widened faces;
- no identity redraw in ordinary popup windows.

### Identity card exception
The identity-card portrait may be pixel-stylized as described above, but it must still remain clearly the same person.

## 11. Popup motion / trigger behavior

### Rule
- short readable mouse move;
- click **水的分析器**;
- windows appear only after the click;
- windows open with snap-open state changes;
- no slide-in motion;
- no face-scan rectangle.

### Important ending rule
For default V53 social/live output, the piece must still end on the completed expanded state and **not retreat before cut**.

## 12. Visual tone

Preserve:
- CRT monitor texture;
- Chinese Win95/98-like shell;
- blue title bars and gray classic panels;
- 4:3 output;
- humorous absurd identity-card energy;
- shareable final reveal.


## 13. Final completion-text lock

When the progress reaches 100%, the lower status line must switch from an in-progress sentence to a completed sentence.

Required final footer text:
- **身份记录已归档**

Do not leave the footer as “水的分析器正在生成档案” after 100%.
