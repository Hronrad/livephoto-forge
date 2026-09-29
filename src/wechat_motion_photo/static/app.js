const form = document.querySelector("#convert-form");
const templateChoice = document.querySelector("#template-choice");
const status = document.querySelector("#status");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const submitButton = document.querySelector("#submit-button");
const templateInfo = document.querySelector("#template-info");
const androidTransferNote = document.querySelector("#android-transfer-note");
const appleGuide = document.querySelector("#apple-guide");
const guideTitle = document.querySelector("#apple-guide-title");
const guideLead = document.querySelector("#apple-guide-lead");
const guideFoot = document.querySelector("#apple-guide-foot");
const guideKicker = document.querySelector("#apple-guide-kicker");
const guideReopen = document.querySelector("#show-apple-guide");
const coverHint = document.querySelector("#cover-hint");
const appleIosTemplateId = "apple-live-ios-direct";
const appleTemplateId = "apple-live-mac-experimental";

function appleMode() {
  if (templateChoice.value === appleIosTemplateId) return "ios";
  if (templateChoice.value === appleTemplateId) return "mac";
  return null;
}

function showAppleGuide() {
  if (appleMode()) appleGuide.hidden = false;
}

function updateTransferGuidance() {
  const mode = appleMode();
  document.body.dataset.platform = mode || "android";
  androidTransferNote.hidden = Boolean(mode);
  guideReopen.hidden = !mode;
  zipOutput.disabled = Boolean(mode);
  zipOutput.closest(".checkbox-option").hidden = Boolean(mode);
  document.querySelectorAll("[data-android-only]").forEach((control) => {
    control.hidden = Boolean(mode);
  });
  document.querySelector("#duration-input").placeholder = mode ? "默认 3 秒，最长 3 秒" : "跟随模板";
  document.querySelector("#key-time-input").placeholder = mode ? "默认首帧" : "跟随模板";
  coverHint.textContent = mode === "ios"
    ? "留空可从 HDR 视频自动生成 HDR HEIC 封面"
    : "不上传则使用视频首帧";
  if (!mode) {
    appleGuide.hidden = true;
    return;
  }
  const mac = mode === "mac";
  guideKicker.textContent = mac ? "APPLE · MAC RELAY" : "APPLE LIVE PHOTO";
  guideTitle.textContent = mac ? "通过 Mac 中转导入" : "导入到 iPhone / iPad";
  guideLead.textContent = mac
    ? "直接导入不可用时，使用 Mac「照片」完成配对。"
    : "先保留下载，再解压 ZIP，最后打开 PVT 保存到照片。";
  document.querySelector("#apple-ios-steps").hidden = mac;
  document.querySelector("#apple-mac-steps").hidden = !mac;
  guideFoot.textContent = mac
    ? "请在 Mac「照片」中同时导入两个文件；在 iPhone/iPad 中分别保存会得到两个独立项目。"
    : "HDR 视频不上传封面时，自动取首帧生成 HDR HEIC。若直接导入不成功，可选 Mac 中转备用。";
  showAppleGuide();
}
const zipOutput = document.querySelector("#zip-output");
const templateDialog = document.querySelector("#template-upload-dialog");
const templateUploadForm = document.querySelector("#template-upload-form");
const templateSubmission = document.querySelector("#template-submission");
const templateUploadStatus = document.querySelector("#template-upload-status");
const templateUploadButton = document.querySelector("#submit-template-upload");

function setStatus(state, title, message) {
  status.dataset.state = state;
  statusTitle.textContent = title;
  statusMessage.textContent = message;
}

function serverError(payload, fallback) {
  return payload?.detail || fallback;
}

function fileLabel(input) {
  const defaults = {
    cover: "选择图片",
    video: "选择视频",
  };
  const label = document.querySelector(`[data-filename="${input.id}"]`);
  label.textContent = input.files[0]?.name || defaults[input.id];
  input.closest(".file-row").dataset.ready = input.files.length ? "true" : "false";
}

function renderTemplate(profile) {
  document.querySelector("#device-value").textContent = `${profile.make} ${profile.model}`;
  document.querySelector("#video-value").textContent = `${profile.video_codec.toUpperCase()} · ${profile.video_duration.toFixed(2)} 秒`;
  document.querySelector("#trailer-value").textContent = `${profile.trailer_length} B`;
  templateInfo.hidden = false;
}

async function inspectTemplate() {
  const templateId = templateChoice.value;
  templateInfo.hidden = true;
  updateTransferGuidance();
  if (templateId === appleIosTemplateId) {
    setStatus("ready", "iOS / iPadOS 直接导入", "HDR 视频留空封面即可保留首帧 HDR；右下角有完整导入步骤。");
    return;
  }
  if (templateId === appleTemplateId) {
    setStatus("ready", "Mac 中转备用", "若 iOS / iPadOS 直接导入不可用，可生成 JPG + MOV 配对文件，在 Mac「照片」中导入。");
    return;
  }
  if (!templateId) {
    setStatus("idle", "等待手机模板", "请从当前已有的模板中选择一个机型。");
    return;
  }
  setStatus("working", "正在检查模板", "读取目标手机的机型与实况格式…");
  const body = new FormData();
  body.append("template_id", templateId);
  try {
    const response = await fetch("/api/inspect", { method: "POST", body });
    const payload = await response.json();
    if (templateChoice.value !== templateId) return;
    if (!response.ok) throw new Error(serverError(payload, "模板无法识别"));
    renderTemplate(payload);
    setStatus("ready", "模板有效", "上传视频即可生成；不选封面时使用视频首帧。");
  } catch (error) {
    if (templateChoice.value !== templateId) return;
    setStatus("error", "模板检查失败", error.message);
  }
}

function acceptsFile(input, file) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (input.id === "cover") return file.type.startsWith("image/") || ["heic", "heif"].includes(extension);
  return file.type.startsWith("video/") || ["mov", "mp4", "m4v"].includes(extension);
}

form.querySelectorAll('input[type="file"]').forEach((input) => {
  input.addEventListener("change", () => {
    fileLabel(input);
  });
});

document.querySelectorAll("[data-drop-target]").forEach((row) => {
  let dragDepth = 0;
  const input = document.querySelector(`#${row.dataset.dropTarget}`);
  row.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    row.dataset.dragover = "true";
  });
  row.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  row.addEventListener("dragleave", () => {
    dragDepth -= 1;
    if (dragDepth <= 0) {
      dragDepth = 0;
      row.dataset.dragover = "false";
    }
  });
  row.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    row.dataset.dragover = "false";
    const file = event.dataTransfer.files[0];
    if (!file || !acceptsFile(input, file)) {
      setStatus("error", "文件类型不正确", `请向“${row.querySelector("strong").textContent}”区域拖入对应格式。`);
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
});

templateChoice.addEventListener("change", () => {
  inspectTemplate();
});

document.querySelector("#close-apple-guide").addEventListener("click", () => {
  appleGuide.hidden = true;
  guideReopen.focus();
});
guideReopen.addEventListener("click", showAppleGuide);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !appleGuide.hidden) appleGuide.hidden = true;
});

function closeTemplateDialog() {
  templateDialog.close();
}

document.querySelector("#open-template-upload").addEventListener("click", () => {
  templateUploadForm.reset();
  document.querySelector("[data-upload-filename]").textContent = "支持 JPG、ZIP、TAR、TGZ、BZ2、XZ";
  templateUploadStatus.textContent = "";
  templateUploadStatus.dataset.state = "idle";
  templateDialog.showModal();
});

document.querySelector("#close-template-upload").addEventListener("click", closeTemplateDialog);
document.querySelector("#cancel-template-upload").addEventListener("click", closeTemplateDialog);
templateDialog.addEventListener("click", (event) => {
  if (event.target === templateDialog) closeTemplateDialog();
});

templateSubmission.addEventListener("change", () => {
  document.querySelector("[data-upload-filename]").textContent =
    templateSubmission.files[0]?.name || "支持 JPG、ZIP、TAR、TGZ、BZ2、XZ";
});

templateUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!templateUploadForm.reportValidity()) return;
  templateUploadButton.disabled = true;
  templateUploadButton.textContent = "正在检查…";
  templateUploadStatus.dataset.state = "working";
  templateUploadStatus.textContent = "正在解压并验证动态图片…";
  try {
    const response = await fetch("/api/template-submissions", {
      method: "POST",
      body: new FormData(templateUploadForm),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(serverError(payload, "模板上传失败"));
    templateUploadStatus.dataset.state = "success";
    templateUploadStatus.textContent = `已收到 ${payload.submission.label} 的动态图片，将用于机型适配。`;
    setTimeout(closeTemplateDialog, 1200);
  } catch (error) {
    templateUploadStatus.dataset.state = "error";
    templateUploadStatus.textContent = error.message;
  } finally {
    templateUploadButton.disabled = false;
    templateUploadButton.textContent = "检查并提交";
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  if (!templateChoice.value) {
    setStatus("error", "请选择手机模板", "请从当前已有的机型模板中选择。");
    return;
  }
  submitButton.disabled = true;
  submitButton.textContent = "正在生成，请稍候…";
  setStatus("working", "正在生成实况照片", "视频转码通常需要几十秒，请保持页面打开。");
  try {
    const mode = appleMode();
    const zipRequested = Boolean(mode) || zipOutput.checked;
    const requestBody = new FormData(form);
    requestBody.set("zip_output", zipRequested ? "true" : "false");
    const response = await fetch("/api/convert", { method: "POST", body: requestBody });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(serverError(payload, "转换失败"));
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    link.href = url;
    const standardAndroid = new Set([
      "google-pixel-2",
      "redmi-k70-ultra",
      "samsung-galaxy-s7",
    ]).has(templateChoice.value);
    link.download = mode === "ios"
      ? `IMG${stamp}-ios-live.pvt.zip`
      : mode === "mac"
      ? `IMG${stamp}-apple-live.zip`
      : zipRequested
      ? `IMG${stamp}.zip`
      : standardAndroid
        ? `MVIMG${stamp}MP.jpg`
        : `IMG${stamp}.jpg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus(
      "success",
      "生成完成",
      mode === "ios"
        ? "下载已开始。在「文件」中先对 ZIP 选择“保留下载”，下载完成后长按“解压缩”，再单击 PVT 中的“保存到照片”。"
        : mode === "mac"
        ? "ZIP 已下载。请在 Mac「照片」中同时导入 JPG 与 MOV，再同步或隔空投送到 iPhone。"
        : zipRequested ? "ZIP 已开始下载，传输到新设备后再解压即可。" : "JPG 已开始下载。",
    );
    if (mode) {
      guideTitle.textContent = mode === "ios" ? "下载完成，接下来导入照片" : "下载完成，接下来在 Mac 导入";
      showAppleGuide();
    }
  } catch (error) {
    setStatus("error", "生成失败", error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "生成实况照片";
  }
});

async function initialize() {
  try {
    const [healthResponse, templatesResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/templates"),
    ]);
    const health = await healthResponse.json();
    const payload = await templatesResponse.json();
    if (!health.ok) {
      setStatus("error", "缺少系统工具", `请先安装：${health.missing.join("、")}`);
      return;
    }
    templateChoice.replaceChildren();
    payload.templates.forEach((item) => {
      templateChoice.add(new Option(item.label, item.id));
    });
    if (payload.templates.length) templateChoice.value = payload.templates[0].id;
    await inspectTemplate();
  } catch {
    setStatus("error", "服务暂时未就绪", "刷新页面后重试。");
  }
}

initialize();
