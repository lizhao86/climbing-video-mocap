# 在 Mac 上用 FreeMoCap GUI 跑攀岩视频

目标：在你自己的 Mac 上装好 FreeMoCap，导入已经转好的攀岩视频（`FreeMoCap_import/IMG_6424.mp4`），单机位跑出骨骼数据 + Blender 场景。

> 先说一句实话：单机位下 FreeMoCap 的底层 2D 引擎就是 MediaPipe，姿态精度跟我们之前那套基本一样；它多出来的价值是 **GUI 操作** 和 **一键 Blender/FBX 导出**。真要更准的 3D 得多机位（2–3 台手机同拍）。这份指南只覆盖你要的"单机位 GUI 玩法"。

---

## 0. 前置：确认 Mac 环境

- 系统：Intel 或 Apple Silicon 都支持。
- 磁盘：首次运行要联网下模型，留 **3GB+** 空间。
- 我已经帮你把视频转成 FreeMoCap 能直接吃的格式：**竖屏 1080×1920 的 mp4**，路径在
  `climbing-video-动捕/FreeMoCap_import/IMG_6424.mp4`。
  FreeMoCap 导入的是"装着 mp4 的文件夹"，所以**直接选 `FreeMoCap_import` 这个文件夹**即可，别动里面的文件名。

---

## 1. 装一个独立 Python 环境（强烈建议用 conda）

FreeMoCap 要求 Python **3.10–3.12**（推荐 3.12），必须装在独立环境里，别污染系统 Python。

如果你**没装过 conda**，先装 Miniconda（终端里跑）：

```bash
# Apple Silicon (M 系列)
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh

# Intel Mac 则用：
# curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
# bash Miniconda3-latest-MacOSX-x86_64.sh
```

装完**关掉终端重开**，然后建环境：

```bash
conda create -n freemocap-env python=3.12 -y
conda activate freemocap-env
```

> 看到命令行前面出现 `(freemocap-env)` 就说明环境激活成功了。之后每次用 FreeMoCap 都要先 `conda activate freemocap-env`。

---

## 2. 安装 FreeMoCap

环境激活状态下：

```bash
pip install freemocap
```

装完后启动 GUI：

```bash
freemocap
```

如果 `freemocap` 这条不认，用这条：

```bash
python -m freemocap
```

> 首次启动会联网下载依赖和模型，慢一点正常，耐心等窗口弹出。
> 若用的是官网下载的"独立安装包"而非 pip：首次打开 Mac 会拦"未识别开发者"，**右键 App → 打开 → 确认**一次即可，以后正常双击。pip 这条路一般没这个拦截。

---

## 3. 导入并处理你的攀岩视频（单机位）

1. GUI 打开后，找 **"Import Videos"**（导入视频）按钮。
2. 选文件夹：定位到 `climbing-video-动捕/FreeMoCap_import`（里面就一个 `IMG_6424.mp4`）。
3. 单机位**不需要相机标定**（calibration 这一步可跳过/自动略过）——这是单摄像头的设定。
4. 点 **Process / 处理**，让它跑完整管线：
   - 2D 关键点追踪（MediaPipe）
   - 3D 重建（单机位下是近似）
   - 生成输出文件（CSV 等）
   - 生成 Blender 场景
5. 跑完后，如果检测到你电脑上装了 Blender，会自动弹出一个带骨架动画的 Blender 场景。

> 4K 原片在 Mac 上会很慢，所以我给你的是 1080p 版本，处理快很多，姿态质量基本无损。

---

## 4. 输出在哪 / 能拿到什么

FreeMoCap 默认把结果存在用户目录下的 **`FreeMoCap_Data/`** 文件夹里，按 session 分子文件夹。里面包括：

- **CSV**：3D/2D 关键点坐标，可拿去做分析（跟我们之前那套数据同类）。
- **`.blend` / FBX**：可直接进 Blender，或重定向（retarget）到你自己的 3D 角色。
- SynchedVideos 等中间产物。

> 想把动作灌到 3D 小人身上：在 Blender 里用 FreeMoCap 的配套插件做 retarget。注意先把目标角色摆成 **T-pose** 作为静止姿态，否则骨骼朝向会错。

---

## 5. 常见坑

- **启动报错 / 装不上**：先确认 `python --version` 在 3.10–3.12 之间，且在 `freemocap-env` 里。版本不对就重建环境。
- **窗口不弹**：用 `python -m freemocap` 再试；首次启动等久一点。
- **处理巨慢**：用我转好的 1080p 版本，别直接喂 4K 原片。
- **导入找不到视频**：确认选的是**文件夹**（`FreeMoCap_import`），不是单个文件；视频必须是 **.mp4**。
- **方向歪了**：我转出来的 mp4 已经是正的竖屏，不会再躺。

---

## 一句话总结

`conda create -n freemocap-env python=3.12 -y` → `conda activate freemocap-env` → `pip install freemocap` → `freemocap` → Import Videos 选 `FreeMoCap_import` 文件夹 → Process。

跑出来的 CSV 如果你想做攀岩姿态分析（重心/贴墙/crux/流畅度），把它丢回来我接着处理。
