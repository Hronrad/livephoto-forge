from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .core import (
    BuildOptions,
    ForgeError,
    build_motion_photo,
    check_dependencies,
    inspect_template,
)


class BuildWorker(QObject):
    log = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__()
        self.values = values

    @staticmethod
    def _optional_float(value: str) -> float | None:
        return float(value) if value.strip() else None

    @Slot()
    def run(self) -> None:
        try:
            options = BuildOptions(
                start=float(self.values["start"]),
                duration=self._optional_float(self.values["duration"]),
                key_time=self._optional_float(self.values["key_time"]),
                crop_mode=self.values["mode"],
                cover_rotation=int(self.values["cover_rotation"]),
                video_rotation=int(self.values["video_rotation"]),
            )
            result = build_motion_photo(
                template=self.values["template"],
                cover=self.values["cover"],
                video=self.values["video"],
                output=self.values["output"],
                options=options,
                log=self.log.emit,
            )
            self.finished.emit(str(result.output.resolve()))
        except (ForgeError, ValueError) as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("微信实况照片封装器")
        self.resize(780, 590)
        self.inputs: dict[str, QLineEdit | QComboBox] = {}
        self.thread: QThread | None = None
        self.worker: BuildWorker | None = None
        self._build_ui()
        QTimer.singleShot(100, self._check_dependencies)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("目标手机模板驱动的微信朋友圈实况照片")
        title.setStyleSheet("font-size: 20px; font-weight: 600; margin-bottom: 10px;")
        layout.addWidget(title)

        form = QFormLayout()
        self._file_row(form, "原生模板 JPG", "template", "JPEG (*.jpg *.jpeg)")
        self._file_row(
            form, "封面图片", "cover", "图片 (*.jpg *.jpeg *.png *.heic *.heif)"
        )
        self._file_row(form, "实况视频", "video", "视频 (*.mp4 *.mov *.m4v)")
        default_output = str(
            Path.cwd() / f"IMG{datetime.now().astimezone():%Y%m%d%H%M%S}.jpg"
        )
        self._file_row(
            form,
            "输出文件",
            "output",
            "JPEG (*.jpg)",
            save=True,
            default=default_output,
        )
        layout.addLayout(form)

        options = QGroupBox("剪辑与方向")
        grid = QGridLayout(options)
        for column, (label, key, default) in enumerate(
            (
                ("开始秒", "start", "0"),
                ("时长（空=模板）", "duration", ""),
                ("封面时间（空=模板）", "key_time", ""),
            )
        ):
            grid.addWidget(QLabel(label), 0, column)
            edit = QLineEdit(default)
            self.inputs[key] = edit
            grid.addWidget(edit, 1, column)
        for column, (label, key, values) in enumerate(
            (
                ("画面适配", "mode", ("crop", "fit")),
                ("封面旋转", "cover_rotation", ("0", "90", "180", "270")),
                ("视频旋转", "video_rotation", ("0", "90", "180", "270")),
            )
        ):
            grid.addWidget(QLabel(label), 2, column)
            combo = QComboBox()
            combo.addItems(values)
            self.inputs[key] = combo
            grid.addWidget(combo, 3, column)
        layout.addWidget(options)

        actions = QHBoxLayout()
        inspect_button = QPushButton("检查模板")
        inspect_button.clicked.connect(self._inspect)
        actions.addWidget(inspect_button)
        actions.addStretch()
        self.build_button = QPushButton("生成实况照片")
        self.build_button.clicked.connect(self._start_build)
        actions.addWidget(self.build_button)
        layout.addLayout(actions)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, 1)
        self.setCentralWidget(root)

    def _file_row(
        self,
        form: QFormLayout,
        label: str,
        key: str,
        file_filter: str,
        *,
        save: bool = False,
        default: str = "",
    ) -> None:
        row = QHBoxLayout()
        edit = QLineEdit(default)
        self.inputs[key] = edit
        button = QPushButton("选择…")
        button.clicked.connect(lambda: self._choose_file(key, file_filter, save))
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)

    def _choose_file(self, key: str, file_filter: str, save: bool) -> None:
        if save:
            path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", "", file_filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if path:
            widget = self.inputs[key]
            assert isinstance(widget, QLineEdit)
            widget.setText(path)

    def _values(self) -> dict[str, str]:
        return {
            key: widget.currentText()
            if isinstance(widget, QComboBox)
            else widget.text()
            for key, widget in self.inputs.items()
        }

    def _append(self, message: str) -> None:
        self.log_box.appendPlainText(message)

    def _check_dependencies(self) -> None:
        missing = check_dependencies()
        if missing:
            QMessageBox.critical(self, "缺少依赖", "请安装：" + ", ".join(missing))

    def _inspect(self) -> None:
        try:
            profile = inspect_template(self._values()["template"])
            self._append(
                f"模板：{profile.make} {profile.model}；{profile.video_codec}；"
                f"{profile.video_duration:.3f}s；尾块 {profile.trailer_length} B"
            )
        except ForgeError as exc:
            QMessageBox.critical(self, "模板无效", str(exc))

    def _start_build(self) -> None:
        self.build_button.setEnabled(False)
        self.thread = QThread(self)
        self.worker = BuildWorker(self._values())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append)
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot(str)
    def _done(self, output: str) -> None:
        self.build_button.setEnabled(True)
        self._append("完成：" + output)
        QMessageBox.information(
            self, "生成成功", output + "\n\n请原样复制到手机 DCIM/Camera。"
        )

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.build_button.setEnabled(True)
        QMessageBox.critical(self, "生成失败", message)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
