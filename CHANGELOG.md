# Changelog

## V68 author & non-commercial notice

- Added creator attribution: **侬若水 / 抖音：侬若水**.
- Added a custom non-commercial license for free personal use while requiring authorization for resale, paid packaging, paid generation services, commercial integration, advertising, brand/e-commerce use, and paid client delivery.
- Added a required text-only post-generation attribution notice; it is never embedded into images or videos.

# CHANGELOG


## v68 - author / usage notice

### Added
- GitHub README 增加作者信息：**侬若水**，抖音号：**侬若水**。
- 增加非商业使用提示；商业使用需先取得作者授权。
- 生成完成后在聊天文本中显示作者与非商用提示。
- 明确禁止把作者提示烧录进图片或视频，画面保持无水印。

## v68 - cinematic-scene video update

### Improved
- 默认从生成阶段准备动画母版、干净底板、锁定人物/UI、宠物层与环境遮罩，不再依赖扁平 JPG 后拆层。
- 默认锁定人物和卡框，以水面、星芒、粒子、宠物动作与 ONLINE 状态灯完成电影感循环。
- 新增手机尺寸动作可见度、静止帧复原、相邻重复帧与 MP4 媒体参数校验。
- PNG 序列编码改为更稳的 BMP 序列，降低解码、缺帧与损坏风险。

### Video Contract
- 3.0 秒、24 fps、72 帧、H.264、yuv420p、无声、无缝循环。
- 宠物主动作至少 1 个，环境动作至少 2 类，UI 动作至少 1 个；人物允许完全静止。
- 禁止用人物整体漂移、旋转或缩放补足动作数量。

## v68 - pet-pose-build

### Added
- PET_LAYER 宠物层
- PET_BANK：白狗、黑猫、白兔、小鸟、小精灵、小熊
- POSE_BANK：8 个轻姿态模板
- 宠物静态行为与后续 3 秒动效映射
- 主题与宠物/姿态联动规则

### Improved
- 减少人物正面站桩感
- 增加底部前景生命感
- 增加画面可动点
- 保留 HEAD_SHELL_LOCK / FACE_PANEL_LOCK / BODY_RATIO_LOCK / TYPOGRAPHY_LOCK / CARD_FRAME_LOCK

### Test Focus
- 宠物尺寸与位置
- 姿态变化幅度
- 男生比例稳定性
- 3 秒实况的循环潜力
