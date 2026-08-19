# 场景电影感视频配置说明

## 目录

1. 素材结构
2. 配置格式
3. 动效选择
4. 媒体预设
5. 合成与验收

## 素材结构

准备以下文件，所有 PNG 使用相同尺寸与 sRGB：

- `mother.png`：最终静态母卡，作为静止帧复原基准。
- `clean-plate.png`：移除宠物与所有会移动环境元素后的干净场景；人物可以保留在底板中并完全锁定。
- `frame-ui.png`：全画布透明 PNG，只保留连续闭合的顶部主题牌、左右轨、四角、底栏、标题、ONLINE、LOOK、年份、音乐和条码；其余透明，作为倒数第二层合成。
- `frame-fx-mask.png`：可选的全画布灰度安全遮罩，只允许边框宝石、灯珠、徽章和图标所在区域为白；用于限制最后一层 `FRAME_FX`，禁止光效进入人物、场景和文字。
- `character-locked.png`：仅在人物不在底板时使用；默认不设置运动。
- 宠物分层：默认准备锁定 `pet-dog-body.png` 与后层 `pet-dog-tail.png`，身体与四脚落地不动，尾根由身体前层覆盖。兔耳仅在母版生成阶段同步获得原生独立透明层时使用；禁止从扁平兔子裁耳，无法可靠分层就自动换成小白狗。只有已有高质量逐格素材时才使用 5–9 格 `pet-strip.png`，至少 3 个不同轮廓且 24 fps 下 `frame_hold<=3`。
- 户外长发：准备独立 `hair-tips.png`，只含脸部安全区以外的外层下半段发梢；底板移除该发梢，使用 `tip_sway` 让根部固定、位移向末端递增 3–7 px。禁止把整束发丝作为刚体旋转。
- 环境素材：DAY/GREEN 户外默认使用少量独立光点、萤火或自然光斑；动态落叶默认关闭。只有用户明确要求时才设置 `scene_environment.allow_falling_leaves=true` 并启用独立 `falling_leaves`。只有 `scene_environment.has_water_or_reflection=true` 时才使用 `water_ripples`。禁止树丛、草地、墙面或人物上方背景矩形扭曲。
- 透明 sprite sheet 的格子必须等宽等高，动作前后回到第 0 格。

中性状态下，将 PET 与可选锁定人物层合成到 `clean-plate.png`，再覆盖 `frame-ui.png`，结果必须复原 `mother.png`。底板中不得残留宠物或其他会移动对象；锁定人物可以保留。`frame-ui.png` 必须先通过四边、四角与分段覆盖检查，再允许进入视频合成。PET 素材必须以目标尺寸生成：犬猫兔熊的可见高度默认达到画布 10%–16%，鸟/小精灵达到 7%–11%；深色宠物需带轮廓光或与背景错开。

## 配置格式

配置文件为 JSON，路径相对于配置文件所在目录解析。

```json
{
  "base": "clean-plate.png",
  "reference": "mother.png",
  "locked_overlay": "frame-ui.png",
  "duration": 3.0,
  "fps": 24,
  "gif_fps": 12,
  "motion_profile": "cinematic_scene",
  "scene_environment": {"has_water_or_reflection": false, "allow_falling_leaves": false},
  "scene_wind": {"enabled": true, "direction": "down_right"},
  "frame_integrity": {
    "edge_band_px": 82,
    "fx_side_band_px": 128,
    "fx_top_bottom_band_px": 220,
    "min_edge_coverage": 0.10,
    "min_corner_coverage": 0.12,
    "min_segment_coverage": 0.02
  },
  "character_motion": {
    "enabled": true,
    "allow_face_blink": false,
    "allow_pet_blink": false,
    "max_translation_px": 7,
    "max_sway_degrees": 3
  },
  "pet_validation": {
    "min_height_ratio": 0.10,
    "max_height_ratio": 0.22,
    "min_width_ratio": 0.07,
    "min_opaque_area_ratio": 0.004,
    "max_overlay_overlap_ratio": 0.10,
    "min_translation_px": 10,
    "max_root_translation_px": 6,
    "max_root_sway_degrees": 2.5,
    "min_distinct_silhouettes": 3,
    "min_sprite_silhouette_changed_ratio": 0.015,
    "max_adjacent_sprite_changed_ratio": 0.35,
    "max_fragment_ratio": 0.03,
    "min_peak_local_mae": 2.5,
    "min_peak_local_changed_ratio": 0.04
  },
  "continuity": {
    "rest_max_mae": 1.0,
    "rest_max_changed_ratio": 0.02,
    "clean_plate_min_mae": 3.0
  },
  "visibility": {
    "preview_size": [512, 768],
    "min_peak_mae": 0.18,
    "min_changed_ratio": 0.0015
  },
  "output_mp4": "card-loop.mp4",
  "groups": [
    {
      "name": "hair_wind",
      "pivot": [520, 720],
      "motion": {"cycles": 1}
    },
    {
      "name": "pet_root",
      "pivot": [820, 1240],
      "motion": {"bob_y": 3, "sway_degrees": 1.5, "cycles": 1, "lag": 0.10}
    },
    {
      "name": "pet_tail",
      "pivot": [820, 1240],
      "motion": {"sway_degrees": 9, "cycles": 2, "lag": 0.05}
    }
  ],
  "layers": [
    {
      "name": "hair_tips",
      "image": "hair-tips.png",
      "group": "hair_wind",
      "z": 58,
      "x": 0,
      "y": 0,
      "deform": {"type": "tip_sway", "anchor": "top", "amplitude_x": 5, "secondary_amplitude": 1, "power": 1.7, "cycles": 1}
    },
    {
      "name": "pet_white_dog_tail_articulated",
      "image": "pet-dog-tail.png",
      "group": "pet_tail",
      "z": 69,
      "x": 760,
      "y": 1120,
      "deform": {"type": "tip_sway", "anchor": "bottom", "amplitude_x": 3.5, "secondary_amplitude": 0.8, "power": 1.7, "cycles": 2}
    },
    {
      "name": "pet_white_dog_body_locked",
      "image": "pet-dog-body.png",
      "group": "pet_root",
      "z": 70,
      "x": 760,
      "y": 1120,
      "scale": 1.0,
      "scale_anchor": "bottom_center"
    }
  ],
  "glints": [
    {"x": 820, "y": 410, "radius": 7, "pulse_radius": 8, "color": "#fff2b2", "cycles": 2, "phase": 0.2}
  ],
  "lights": [
    {"x": 895, "y": 96, "radius": 5, "color": "#76ff9b", "cycles": 3, "phase": 0.0}
  ],
  "particles": [
    {
      "seed": 68,
      "count": 14,
      "region": [80, 120, 1000, 1220],
      "color": "#fff5d6",
      "radius": [2, 4],
      "drift_x": 18,
      "drift_y": 12,
      "cycles": 1,
      "opacity": 120
    }
  ],
  "frame_fx_mask": "frame-fx-mask.png",
  "frame_fx": [
    {
      "type": "gem_glint",
      "x": 82,
      "y": 88,
      "radius": 5,
      "pulse_radius": 5,
      "color": "#fff4c9",
      "cycles": 1,
      "phase": 0.04
    },
    {
      "type": "rail_light",
      "points": [[958, 390], [958, 480], [958, 570]],
      "radius": 4,
      "color": "#ff8fb9",
      "cycles": 1,
      "phase": 0.22
    },
    {
      "type": "icon_pulse",
      "x": 512,
      "y": 1460,
      "radius": 22,
      "pulse_radius": 6,
      "width": 3,
      "color": "#ffd2df",
      "cycles": 1,
      "phase": 0.48
    }
  ]
}
```

每个 `layer` 使用 `image` 或 `sheet`，不能同时使用。`motion` 支持 `bob_x`、`bob_y`、`sway_degrees`、整数 `cycles`、`lag`、`pivot_x`、`pivot_y`。`deform.type=tip_sway` 支持 `anchor`、`waveform`、`amplitude_x`、`secondary_amplitude`、`amplitude_y`、`power` 和整数 `cycles`；发梢用 `anchor=top`，狗尾用 `anchor=bottom`。普通宠物根节点仅作 0–6 px 辅助位移，默认由锁定身体 + 连续尾巴后层提供主动作；sprite 仅作备选，`sequence` 首尾必须同格且 `frame_hold<=3`。动态落叶不是默认通道；只有用户明确要求并设置 `allow_falling_leaves=true` 时才允许使用，且必须为独立层、不移动背景。`water_ripples` 仅限经语义声明的真实水面/镜面反射。

`pet_validation` 独立渲染 72 帧 PET_ONLY 画面，并检查尺寸、遮挡、手机端差分、锁定身体、连续关节层、轮廓碎片率、sprite 节奏、相邻格突变与根节点幅度。狗没有独立尾巴层、任一帧碎片率超过 3%、使用 `frame_hold>3`、相同贴纸整块跳动或相邻帧轮廓突变都会失败。

`frame_fx` 支持三种类型：`gem_glint` 为局部十字/菱形星芒，`rail_light` 沿给定边轨节点追光，`icon_pulse` 为徽章或音乐图标外圈脉冲。所有坐标都必须落在 `frame_integrity` 定义的外框安全带内；有 `frame-fx-mask.png` 时还会二次裁切。FRAME_FX 始终在静态 `frame-ui.png` 之后合成，因此只能画附加光，不得替代任何框体结构。

## 电影感动效选择

- 人物：脸、眼睛、刘海、脸旁内层头发、耳饰与躯干锁定；户外长发/有风场景必须使用根部固定、末端渐强的安全 `hair_tips`/`hair_ends` 连续形变 3–7 px，且不可覆盖脸或整束刚体旋转。
- 宠物：默认小白狗摇尾，锁定身体与落地脚，只连续转动/弯曲身体后的尾巴层；兔耳只接受原生分层素材。普通宠物根节点不超过 6 px/2.5°；sprite 仅作顺滑备选。
- 环境：户外默认使用少量独立光点、萤火或自然光斑，不生成动态落叶；只有用户明确要求才启用独立叶片。真实水面/镜面反射才允许水纹横移 6–18 px；无水场景禁止任何矩形背景区域晃动。
- 星芒：`pulse_radius` 至少 4 px，避免只提高亮度却看不出变化。
- UI：ONLINE 状态灯轻闪，避免整块标签变亮。
- 外框：至少 2 个错峰 `frame_fx`，且至少一个为 `gem_glint`；推荐顶部主宝石、角部宝石、侧轨灯珠与底部徽章依次闪亮，同一时刻 1–3 个亮点，禁止整框呼吸或变形。

同一成片保留 5–8 个可见子动作，归入 LOCKED_CHARACTER、PET_ROOT、ENVIRONMENT、LOCKED_FRAME_UI、FRAME_FX 五个系统。环境先动、宠物响应、外框局部闪点与 UI 收尾；不得用人物整体漂移补足动作数。所有动作必须在 512×768 预览中肉眼可见。

固定 z 顺序：环境后景 0–19；锁定人物 20–59；宠物尾/后层 60–69；宠物身体/前层 70–79；环境前景 80–89；`locked_overlay`/`frame-ui.png` 90–98；受安全区限制的 `FRAME_FX` 永远最后。

## 媒体预设

| 用途 | 尺寸 | 比例 |
|---|---:|---:|
| 系列母卡与默认视频 | 1024×1536 | 2:3 |
| 抖音/视频号/Reels 外层画布 | 1080×1920 | 9:16，完整嵌入 2:3 卡 |
| 其他平台外层画布 | 按平台要求 | 不裁卡框 |

MP4 使用 H.264、yuv420p、无声和 `faststart`。GIF 只作预览或兼容版本，默认 12 fps、3 秒 36 帧；禁止降到 8 fps / 24 帧。需要最高画质时始终交付 MP4。

## 合成与验收

```bash
python3 scripts/render_micro_video.py config.json
ffprobe -v error -show_entries stream=width,height,r_frame_rate -show_entries format=duration -of json card-loop.mp4
```

如果只有一张扁平母卡，可用安全微动模式排错：

```bash
python3 scripts/render_micro_video.py \
  --safe-base card.png \
  --output-mp4 card-loop.mp4 \
  --output-gif card-loop.gif
```

安全模式自动加入循环粒子、闪点和状态灯，但仅限草稿与排错，禁止作为最终交付。最终配置必须设置 `motion_profile: cinematic_scene`。

验收必须满足：

- 时长为 3.0 秒，允许一帧误差。
- 帧率为 24 fps，共 72 帧。
- 5–8 个清楚动作；PET、至少一种语义正确的环境效果、UI 与至少两个错峰 FRAME_FX 各自清楚可见；户外长发/有风场景必须有安全发梢层。
- `rest_mae` 与接缝占比通过；脚本确认 `clean_plate` 内没有残留活动宠物。
- 宠物身体共享 PET_ROOT 且保持落地；狗尾后层连续摆动，连接处由身体前层覆盖；72 帧碎片率不得超过 3%。
- 普通宠物必须有锁定身体 + 至少 1 个连续关节层，或使用至少 3 个不同轮廓且 `frame_hold<=3` 的顺滑 sprite；根节点不超过 6 px/2.5°，禁止贴纸式整块跳动。
- 无水场景不存在 `water_ripples` 或树丛/草地/墙面矩形扭曲；默认配置中不存在动态落叶。
- `pet_validation` 通过：普通宠物高度不低于画布 10%，遮挡率不高于 10%，PET_ONLY 局部差分达到阈值；其他画面动效不能代替宠物动作。
- 卡框/UI 通过 `locked_overlay` 覆盖，不被粒子或人物穿透；只有通过外框安全区与可选遮罩检查的 FRAME_FX 可以在其上方出现。
- `frame_integrity` 的顶部、底部、左右轨、四角和分段覆盖全部通过；不存在断边、缺角、被裁或中央场景越界。
- FRAME_FX 至少包含一个宝石星芒且不改变框体几何，不让标题、ONLINE、LOOK、年份或条码本体闪烁。
- 首尾衔接无跳变；固定元素逐帧一致。
- 头壳、五官、比例、文字与卡框无漂移。
- 72 帧无缺帧、意外重复帧或解码错误；动作在 512×768 预览中清楚可见。
- 动作幅度清楚但克制，宠物不抢人物脸部注意力。
- MP4 可播放；宽高为偶数；没有意外音轨。
- 若输出 GIF，至少 12 fps、36 帧，且动作节奏与 MP4 一致。
