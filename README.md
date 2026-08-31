# WeChat Motion Photo Forge

将任意封面图片和短视频封装为 OPPO / OnePlus / realme 手机可在微信朋友圈发布的实况照片。

项目不猜测厂商私有格式，而是读取一张目标手机原生相机拍摄的实况 JPG 作为模板，复用该机型的 OPLUS XMP 结构、EXIF 相机字段和厂商尾块，再替换封面与视频。因此同一套代码可适配不同 OPLUS 机型及固件。

## 为什么需要原生模板

系统相册能播放标准 Motion Photo，不代表微信会显示“实况”选项。实测 realme GT Neo5 240W 的微信朋友圈还依赖：

- `GCamera:MotionPhoto=1` 与 OPLUS O-Live Photo v2 XMP；
- 精确的 `VideoLength` 与 Container `Item:Length`；
- `oplus_8388640` EXIF 标记；
- JPEG MPF APP2 段；
- MP4 后的 435 字节 realme/OnePlus 厂商尾块；
- 与原生相机接近的编码、画幅、帧率和时长；
- 正确的数字 EXIF Orientation 值。字符串方式写入 Orientation 可能意外变成 180°。

工具从模板自动读取这些参数，不在代码中固定某个机型。

## 使用条件

- Python 3.10+
- PySide6（安装本项目时自动安装）
- `ffmpeg` 与 `ffprobe`
- `exiftool`
- 一张目标手机原生相机拍摄、已确认可发微信朋友圈的实况 JPG

macOS：

```bash
brew install ffmpeg exiftool
```

Windows 可分别从 [FFmpeg](https://ffmpeg.org/download.html) 和 [ExifTool](https://exiftool.org/) 下载，并加入 `PATH`。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
```

## 图形界面

```bash
wechat-live-gui
```

依次选择：

1. 目标手机原生实况 JPG；
2. 封面图片；
3. 实况视频；
4. 输出 JPG。

默认会跟随模板的时长、封面时间、照片尺寸、视频编码和画幅。封面或视频方向异常时，可独立选择旋转 90°、180° 或 270°。

## 命令行

检查模板：

```bash
wechat-live inspect IMG20260831123303.jpg
```

生成：

```bash
wechat-live build \
  --template IMG20260831123303.jpg \
  --cover cover.jpg \
  --video motion.mov \
  --output IMG20260831124503.jpg
```

指定剪辑与画面：

```bash
wechat-live build \
  --template native.jpg \
  --cover cover.png \
  --video motion.mp4 \
  --start 1.2 \
  --duration 2.1 \
  --key-time 0.8 \
  --mode crop \
  --cover-rotate 0 \
  --video-rotate 0 \
  --output result.jpg
```

`crop` 会铺满原生画幅并裁切边缘；`fit` 会保留完整画面并添加黑边。

## 传入手机

将生成的 JPG **原样**复制到：

```text
内部存储/DCIM/Camera/
```

建议使用 USB、局域网文件传输或手机厂商互传。不要先作为普通微信图片或 QQ 图片发送，否则平台可能重压缩并剥离实况数据。复制后等待系统相册完成媒体扫描，再进入微信朋友圈选择。

## 隐私与安全

- 全程在本机运行，不上传素材。
- 生成文件不会复制模板的 GPS。
- 会复制模板的机型与部分相机 EXIF，以符合目标手机的媒体格式。
- 不修改输入文件。
- 不要将含个人内容的原生模板提交到公开 Git 仓库。

## 已验证

- realme GT Neo5 240W：realme 系统相册识别，微信朋友圈出现“实况”选项。
- 横向封面 Orientation 已归一为 `1`，避免 180° 翻转。

其他机型应使用各自原生模板测试。固件或微信版本更新后，厂商判定条件可能变化。

## 测试

```bash
python -m unittest discover -s tests -v
```

含私有样本的端到端验证不会进入仓库；CI 只运行不含用户媒体的单元测试。

## 同类项目

调研记录见 [docs/research.md](docs/research.md)。本项目只解决“目标手机模板驱动、微信朋友圈严格识别”的窄场景；通用转换、批量管理或安卓端查看可优先考虑现有成熟工具。

## 许可

MIT。FFmpeg、ExifTool 及调研参考项目保留各自许可，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
