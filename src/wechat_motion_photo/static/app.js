const form = document.querySelector("#convert-form");
const templateChoice = document.querySelector("#template-choice");
const status = document.querySelector("#status");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const submitButton = document.querySelector("#submit-button");
const templateInfo = document.querySelector("#template-info");
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
    if (!response.ok) throw new Error(serverError(payload, "模板无法识别"));
    renderTemplate(payload);
    setStatus("ready", "模板有效", "拖入封面与实况视频，然后生成。");
  } catch (error) {
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
    const zipRequested = zipOutput.checked;
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
    link.download = zipRequested
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
      zipRequested ? "ZIP 已开始下载，传输到新设备后再解压即可。" : "JPG 已开始下载。",
    );
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
