# 微信实况照片封装器

本机 WebUI：把封面图片和短视频封装为 OPPO / OnePlus / realme 手机可在微信朋友圈发布的实况照片。

## 使用

先安装两个系统工具：

- macOS：`brew install ffmpeg exiftool`
- Windows：安装 [FFmpeg](https://ffmpeg.org/download.html) 和 [ExifTool](https://exiftool.org/)，把可执行文件加入 `PATH`（ExifTool 文件名应为 `exiftool.exe`）
- Linux（Debian / Ubuntu）：`sudo apt install ffmpeg libimage-exiftool-perl`

然后在项目目录运行：

```bash
python start.py
```

首次启动会在项目内创建 `.venv` 并安装 Python 依赖，随后自动打开浏览器。以后仍运行同一条命令即可。

也可以双击：

- Windows：`start.bat`
- macOS：`start.command`
- Linux：`start.sh`

页面内依次操作：

1. 直接选择内置手机模板，或上传其他机型已确认可发朋友圈的原生实况 JPG；
2. 拖入或选择自定义封面图片；
3. 拖入或选择自定义实况视频；
4. 点击“生成实况照片”。

将下载的 JPG **原样**复制到手机的 `DCIM/Camera/`，等待相册完成媒体扫描，再进入微信朋友圈选择。不要先作为普通聊天图片中转。

## 为什么需要模板

系统相册能播放标准 Motion Photo，不代表微信会显示“实况”选项。OPLUS 设备还可能依赖 O-Live Photo v2 XMP、MPF、机型 EXIF、精确视频长度和厂商私有尾块。本项目从目标手机的原生实况照片中读取这些参数，不把某个机型写死在代码里。

内置模板：realme GT Neo5 240W。模板已替换为中性封面和静音短片，不包含用户原始画面内容。

已验证：realme GT Neo5 240W，系统相册识别且微信朋友圈出现“实况”选项；输出 Orientation 归一为数字 `1`，不会再旋转 180°。

## 命令行（可选）

```bash
wechat-live inspect native.jpg
wechat-live build --template native.jpg --cover cover.jpg --video motion.mov --output result.jpg
```

WebUI 手动启动：

```bash
wechat-live-web
wechat-live-web --no-browser --host 127.0.0.1 --port 8765
```

## 隐私

- Web 服务默认只监听 `127.0.0.1`，文件不会上传到互联网。
- 输入文件不会被修改，临时素材在响应结束后删除。
- 输出不会复制模板 GPS，但会复制模板机型与必要相机字段。
- 不要把含个人内容的手机模板提交到公开仓库。

## 开发与测试

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

转换核心位于 `src/wechat_motion_photo/core.py`，Web 服务位于 `src/wechat_motion_photo/web.py`，前端为无构建步骤的原生 HTML / CSS / JavaScript。

同类项目调研见 [docs/research.md](docs/research.md)。许可证为 MIT。
