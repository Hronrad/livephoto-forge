const form = document.querySelector("#convert-form");
const templateInput = document.querySelector("#template");
const templateChoice = document.querySelector("#template-choice");
const status = document.querySelector("#status");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const submitButton = document.querySelector("#submit-button");
const templateInfo = document.querySelector("#template-info");

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
    template: "上传其他模板",
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
  document.querySelector('[data-drop-target="template"]').dataset.ready = "true";
}

async function inspectTemplate() {
  const file = templateInput.files[0];
  const templateId = templateChoice.value;
  templateInfo.hidden = true;
  if (!file && !templateId) {
    setStatus("idle", "等待自定义模板", "拖入或点击上传目标手机的原生实况 JPG。");
    return;
  }
  setStatus("working", "正在检查模板", "读取目标手机的机型与实况格式…");
  const body = new FormData();
  if (file) body.append("template", file);
  if (!file && templateId) body.append("template_id", templateId);
  try {
    const response = await fetch("/api/inspect", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(serverError(payload, "模板无法识别"));
    renderTemplate(payload);
    setStatus("ready", "模板有效", "拖入封面与实况视频，然后生成。");
  } catch (error) {
    document.querySelector('[data-drop-target="template"]').dataset.ready = "false";
    setStatus("error", "模板检查失败", error.message);
  }
}

function acceptsFile(input, file) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (input.id === "template") return file.type === "image/jpeg" || ["jpg", "jpeg"].includes(extension);
  if (input.id === "cover") return file.type.startsWith("image/") || ["heic", "heif"].includes(extension);
  return file.type.startsWith("video/") || ["mov", "mp4", "m4v"].includes(extension);
}

document.querySelectorAll('input[type="file"]').forEach((input) => {
  input.addEventListener("change", () => {
    fileLabel(input);
    if (input === templateInput && input.files.length) {
      templateChoice.value = "";
      inspectTemplate();
    }
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
  templateInput.value = "";
  fileLabel(templateInput);
  inspectTemplate();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  if (!templateInput.files[0] && !templateChoice.value) {
    setStatus("error", "请选择手机模板", "请选择内置模板，或上传目标手机的原生实况 JPG。");
    return;
  }
  submitButton.disabled = true;
  submitButton.textContent = "正在生成，请稍候…";
  setStatus("working", "正在生成实况照片", "视频转码通常需要几十秒，请保持页面打开。");
  try {
    const response = await fetch("/api/convert", { method: "POST", body: new FormData(form) });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(serverError(payload, "转换失败"));
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    link.href = url;
    link.download = `IMG${stamp}.jpg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus("success", "生成完成", "JPG 已开始下载，可原样复制到手机 DCIM/Camera。");
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
    templateChoice.add(new Option("其他机型（上传模板）", ""));
    if (payload.templates.length) templateChoice.value = payload.templates[0].id;
    await inspectTemplate();
  } catch {
    setStatus("error", "本机服务未就绪", "刷新页面后重试。");
  }
}

initialize();
