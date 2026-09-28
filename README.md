# Motion Photo Forge

将封面图片和短视频封装为手机可识别的实况照片。可直接使用[在线版本](https://motion-photo.hronrad.cn/)，也可在本机运行。

## 本机运行

先安装 FFmpeg 和 ExifTool：

- macOS：`brew install ffmpeg exiftool`
- Debian / Ubuntu：`sudo apt install ffmpeg libimage-exiftool-perl`
- Windows：安装 [FFmpeg](https://ffmpeg.org/download.html) 和 [ExifTool](https://exiftool.org/)，并加入 `PATH`

在项目目录运行 `python start.py`；也可双击对应系统的 `start.command`、`start.sh` 或 `start.bat`。

## 使用

选择机型，添加封面和短视频，点击“生成实况照片”。默认下载 ZIP；传输到手机后解压，将 JPG 原样放入 `DCIM/Camera/`。需要直接下载 JPG 时，在高级设置中关闭“输出 ZIP 压缩包”。

内置 realme、HONOR、Google Pixel、Redmi、Samsung、OPPO 和 HUAWEI 的部分机型。兼容性可能因系统和相册版本而异；未收录机型可在页面提交原生动态照片帮助适配。

## 隐私

本机服务默认只监听 `127.0.0.1`。使用在线版本时，素材会上传至本站服务器处理，转换临时文件在响应结束后删除。

## 开发

安装项目依赖后运行：`python -m unittest discover -s tests -v`。项目采用 MIT 许可证；格式资料见 [docs/research.md](docs/research.md)。
