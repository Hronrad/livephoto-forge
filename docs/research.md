# 同类项目调研

调研日期：2026-08-31。

## 结论

已有项目已经覆盖标准 Android Motion Photo、OPPO O-Live、跨品牌转换和封面编辑，但未发现同时满足以下条件的开源项目：

1. 独立选择封面图片与实况视频；
2. 从目标 realme/OPPO/OnePlus 手机的原生实况 JPG 自动提取私有模板；
3. 保留模板的真实 OPLUS XMP 布局和机型尾块；
4. 以微信朋友圈是否出现“实况”选项作为端到端验收条件；
5. 跨平台 GUI 与 CLI。

本项目因此采用模板驱动，而不是再维护一组容易随机型和固件失效的硬编码常量。

## 项目比较

### OPPO Live Photo Maker

- 地址：https://github.com/Young-Spark/oppo-live-photo-maker
- 许可：MIT
- 优点：跨平台 GUI/CLI、OPPO XMP 与 MPF、操作简单。
- 差异：公开实现从视频生成封面，并固定若干 OPLUS 字段；未克隆目标 realme 样本末尾的 OnePlus/realme 厂商块。实测结果可被系统相册识别，但微信朋友圈未必提供“实况”选项。

### Live Photo Box

- 地址：https://github.com/LengxiQwQ/live-photo-box
- 许可：GPL-3.0
- 优点：Windows 上功能全面，支持合并、拆分、修复、封面编辑和多厂商协议。
- 差异：目前以 Windows/.NET 为主；本项目不复制其 GPL 代码，只将其作为协议与产品范围的调研参考。

### MotionCraft

- 地址：https://github.com/WeiErLiTeo/MotionCraft
- 许可：Apache-2.0
- 优点：安卓端查看、转换、配对与 XMP 检查，覆盖多个品牌。
- 差异：重点是通用 Android Motion Photo 管理，不以特定 realme 原生模板和微信朋友圈判定为核心。

### MotionTrans

- 地址：https://github.com/Huakira/MotionTrans
- 许可：仓库声明未授予再分发或商用许可。
- 优点：Apple Live Photo 与 OPPO/Android Motion Photo 双向转换，保留大量元数据。
- 差异：主要面向 macOS/iOS；不能将其代码纳入 MIT 项目。

### live_motion_photos_convert

- 地址：https://github.com/AssassinJY/live_motion_photos_convert
- 许可：MIT
- 优点：Apple 与 Android 双向批量转换，已验证小米 HyperOS 和微信。
- 差异：验证重点是小米，不覆盖本次 realme 私有尾块。

### video-to-live-photo

- 地址：https://github.com/yangzhen-23/video-to-live-photo
- 许可：Apache-2.0
- 优点：Windows 图形界面、多片段、多目标平台、自选封面时间。
- 差异：标准 Android/iPhone/vivo 为主，不包含本次 realme 微信模板克隆路径。

## 本次 realme 样本得到的互操作结论

系统相册的 Motion Photo 识别条件比微信宽松。样本显示，微信可用文件与普通 Google Motion Photo 的关键差异包括：

- 原生 XMP 使用 `OpCamera` 与 `GContainer` 命名空间；
- `OpCamera:VideoLength` 仅计算 MP4，Container 长度还包括厂商尾块；
- 文件末尾有长度自描述的 435 字节 OnePlus/realme 块；
- EXIF `UserComment` 大小写和数值需要跟随模板；
- 原生 MP4 参数为目标机型偏好的 HEVC、画幅、帧率和时长；
- EXIF Orientation 必须用数值方式写入并归一为 `1`，否则 ExifTool 的字符串转换可能写成 Rotate 180。

