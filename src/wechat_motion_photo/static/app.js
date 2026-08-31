const form = document.querySelector("#convert-form");
const templateInput = document.querySelector("#template");
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

document.querySelectorAll('input[type="file"]').forEach((input) => {
  input.addEventListener("change", () => {
    const label = document.querySelector(`[data-filename="${input.id}"]`);
    label.textContent = input.files[0]?.name || (input.id === "video" ? "选择视频" : "选择图片");
  });
});

templateInput.addEventListener("change", async () => {
  const file = templateInput.files[0];
  templateInfo.hidden = true;
  if (!file) return;
  setStatus("working", "正在检查模板", "读取目标手机的机型与实况格式…");
  const body = new FormData();
  body.append("template", file);
  try {
    const response = await fetch("/api/inspect", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(serverError(payload, "模板无法识别"));
    document.querySelector("#device-value").textContent = `${payload.make} ${payload.model}`;
    document.querySelector("#video-value").textContent = `${payload.video_codec.toUpperCase()} · ${payload.video_duration.toFixed(2)} 秒`;
    document.querySelector("#trailer-value").textContent = `${payload.trailer_length} B`;
    templateInfo.hidden = false;
    setStatus("ready", "模板有效", "继续选择封面与实况视频，然后生成。");
  } catch (error) {
    setStatus("error", "模板检查失败", error.message);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
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
    setStatus("success", "生成完成", "JPG 已开始下载，可原样复制到手机 DCIM/Camera。 ");
  } catch (error) {
    setStatus("error", "生成失败", error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "生成实况照片";
  }
});

fetch("/api/health")
  .then((response) => response.json())
  .then((payload) => {
    if (!payload.ok) setStatus("error", "缺少系统工具", `请先安装：${payload.missing.join("、")}`);
  })
  .catch(() => setStatus("error", "本机服务未就绪", "刷新页面后重试。"));
