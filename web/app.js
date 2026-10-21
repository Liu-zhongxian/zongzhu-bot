import { ESPLoader, Transport } from "./vendor/esptool-js-0.6.1/bundle.js";
import { parseAppDesc } from "./lib/appdesc.js";
import { setWakeWord, wakeWordOf } from "./lib/assets.js";
import { md5 } from "./lib/md5.js";
import { zongzhuNvs } from "./lib/nvs.js";

const REPO = "https://github.com/Liu-zhongxian/zongzhu-bot";
// Only used to pre-fill the pinyin of a custom wake word; typing it works without it.
const PINYIN_PRO = "https://cdn.jsdelivr.net/npm/pinyin-pro@3.27.0/+esm";
const ESPRESSIF_USB_VID = 0x303a;
const NVS_OFFSET = 0x9000;
const ASSETS_PARTITION_SIZE = 0x800000;
const APP_OFFSETS = [0x20000, 0x410000];
// Same rule as tools/build_firmware.py.
const OTA_URL = /^https?:\/\/[A-Za-z0-9.-]+(:\d+)?\/[A-Za-z0-9._~/-]*$/;
const BOOT_LOG_SECONDS = 45;

const $ = (id) => document.getElementById(id);
const state = {
  boards: [], wakewords: [], board: null,
  chip: "", mac: "", flashSize: "",
  port: null, transport: null, loader: null,
  // flashed: the last flash finished; the page then disconnects, so no port is open.
  pinyinTouched: false, flashing: false, flashed: false,
  step: 0, valid: [false, false, false, false, false],
};

// ---------- log ----------

function log(line) {
  const pre = $("log");
  pre.textContent += line + "\n";
  pre.scrollTop = pre.scrollHeight;
}

const terminal = {
  clean() {},
  writeLine: log,
  write: (text) => { $("log").textContent += text; },
};

// ---------- step 1: connect ----------

async function connect(filtered) {
  if (state.flashing) return;
  try {
    await disconnect();
    const port = await navigator.serial.requestPort(
      filtered ? { filters: [{ usbVendorId: ESPRESSIF_USB_VID }] } : {});
    state.port = port;
    state.transport = new Transport(port, false);
    state.loader = new ESPLoader({ transport: state.transport, baudrate: 921600, terminal });
    $("connect").disabled = true;
    $("connect").textContent = "正在连接…";
    state.chip = await state.loader.main();
    state.mac = await state.loader.chip.readMac(state.loader);
    state.flashSize = await state.loader.detectFlashSize();
    let existing = null;
    for (const offset of APP_OFFSETS) {
      try {
        existing = parseAppDesc(await state.loader.readFlash(offset, 0x100)) || existing;
      } catch (error) {
        log(`读取 0x${offset.toString(16)} 失败：${error}`);
      }
    }
    state.flashed = false;
    showChip(existing);
  } catch (error) {
    if (error?.name !== "NotFoundError") {
      log(String(error));
      alert("连接失败：" + (error?.message || error) + "\n\n可以按住 BOOT 键拔插 USB，进入下载模式后再试。");
    }
    await disconnect();
  } finally {
    $("connect").disabled = false;
    $("connect").textContent = state.loader ? "重新连接" : "连接板子";
  }
}

async function disconnect() {
  if (state.transport) {
    try { await state.transport.disconnect(); } catch { /* already closed */ }
  }
  state.transport = state.loader = null;
}

function showChip(existing) {
  $("chip-info").hidden = false;
  const facts = [
    ["芯片", state.chip],
    ["Flash", state.flashSize],
    ["MAC", state.mac],
    ["现有程序", existing ? `${existing.project} ${existing.version}（${existing.date}）` : "无法识别"],
  ];
  $("chip-facts").replaceChildren(...facts.flatMap(([k, v]) => [el("dt", k), el("dd", v)]));

  const matches = state.boards.filter((b) => state.chip.startsWith(b.chip) && state.flashSize === b.flashSize);
  const list = $("board-list");
  list.replaceChildren(...state.boards.map((board) => {
    const ok = matches.includes(board);
    const why = ok ? board.look : `不匹配：需要 ${board.chip}、${board.flashSize} Flash`;
    return choice("board", board.id, board.name, why, { disabled: !ok, checked: ok && matches.length === 1 });
  }));
  state.board = matches.length === 1 ? matches[0] : null;
  const notice = $("board-unsupported");
  notice.hidden = matches.length > 0;
  notice.textContent = `暂不支持这块板子（${state.chip}，${state.flashSize} Flash）。目前支持：` +
    state.boards.map((b) => b.name).join("、") + "。";
  $("board-question").textContent = matches.some((b) => b.flashSize === "16MB")
    ? "请对照屏幕确认（不带 C 的微雪 1.75 也是 16MB，本页不支持）："
    : "请确认是哪一块板子：";
  update();
}

// ---------- step 2: wake word ----------

function renderWakewords() {
  $("wake-list").replaceChildren(...state.wakewords.map((w, i) => choice(
    "wake", String(i), w.text, w.command,
    { checked: i === 0, badge: w.tested ? ["已实测", "ok"] : ["未实测", "warn"] })));
}

function wakeChoice() {
  const picked = document.querySelector('input[name="wake"]:checked')?.value;
  if (picked !== "custom") {
    const w = state.wakewords[Number(picked)];
    return { text: w.text, command: w.command };
  }
  const text = $("wake-text").value.trim();
  const command = $("wake-pinyin").value.trim().toLowerCase().replace(/ü/g, "v").replace(/\s+/g, " ");
  if (!/^[一-鿿]{2,8}$/.test(text)) return { error: "唤醒词请填 2–8 个汉字" };
  if (!/^[a-z]+( [a-z]+)*$/.test(command)) return { error: "拼音只能是小写字母，每个字之间一个空格" };
  if (command.split(" ").length !== [...text].length) return { error: "拼音的个数要和汉字个数一样" };
  return { text, command };
}

let pinyinLib = null;
async function fillPinyin() {
  if (state.pinyinTouched) return;
  const text = $("wake-text").value.trim();
  if (!text) return;
  try {
    pinyinLib ||= await import(PINYIN_PRO);
    const syllables = pinyinLib.pinyin(text, { toneType: "none", type: "array" });
    if ($("wake-text").value.trim() === text) $("wake-pinyin").value = syllables.join(" ").replace(/ü/g, "v");
  } catch {
    // Offline or blocked: the user types the pinyin.
  }
  update();
}

// ---------- step 4/5: backend and Wi-Fi ----------

function backendChoice() {
  const mode = document.querySelector('input[name="backend"]:checked').value;
  $("backend-local").hidden = mode !== "local";
  $("backend-server").hidden = mode !== "server";
  let url;
  if (mode === "local") {
    const host = $("local-host").value.trim();
    if (!host) return { mode, error: "" };
    if (!/^[A-Za-z0-9.-]+$/.test(host)) return { mode, error: "只填电脑名或 IP，不要带 http:// 和端口" };
    url = `http://${host}:8003/xiaozhi/ota/`;
  } else {
    url = $("server-url").value.trim();
    if (!url) return { mode, error: "" };
    if (!OTA_URL.test(url)) return { mode, error: "地址格式不对，例如 https://example.com/xiaozhi/ota/" };
    if (!url.startsWith("https://")) return { mode, url, warn: "公网服务器建议用 https://" };
  }
  return { mode, url };
}

function wifiChoice() {
  const now = document.querySelector('input[name="wifi"]:checked').value === "now";
  $("wifi-now").hidden = !now;
  if (!now) return { skip: true };
  const ssid = $("wifi-ssid").value;
  const password = $("wifi-password").value;
  const bytes = (s) => new TextEncoder().encode(s).length;
  if (!ssid) return { error: "" };
  if (bytes(ssid) > 32) return { error: "Wi-Fi 名称太长（最多 32 字节）" };
  if (password && (bytes(password) < 8 || bytes(password) > 63)) return { error: "Wi-Fi 密码应为 8–63 个字符，没有密码就留空" };
  return { ssid, password };
}

// ---------- form state ----------

function update() {
  const picked = document.querySelector('input[name="board"]:checked')?.value;
  state.board = state.boards.find((b) => b.id === picked) || null;

  const custom = document.querySelector('input[name="wake"]:checked')?.value === "custom";
  $("wake-custom").hidden = !custom;
  const wake = wakeChoice();
  $("wake-error").textContent = custom ? wake.error || "" : "";

  const backend = backendChoice();
  $("ota-preview").textContent = backend.url || "—";
  $("backend-error").textContent = backend.error || backend.warn || "";

  const wifi = wifiChoice();
  $("wifi-error").textContent = wifi.error || "";

  // Whether each of steps 1–5 is filled in; step 6 is reachable once all are.
  state.valid = [
    !!state.board && !!state.loader,
    !wake.error,
    true,
    !!backend.url && !backend.error,
    !wifi.error && (wifi.skip || !!wifi.ssid),
  ];
  const ready = state.valid.every(Boolean);
  $("flash").disabled = !ready || !$("confirm-erase").checked || state.flashing;
  const hint = $("flash-hint");
  hint.textContent = state.loader || state.flashing ? ""
    : state.flashed ? "已经刷好。要再刷一次，请回到第 1 步重新连接板子。"
    : "板子没有连接，请回到第 1 步重新连接。";
  hint.classList.toggle("error-text", !state.flashed);
  render();

  if (ready) {
    const facts = [
      ["板子", state.board.name],
      ["唤醒词", `${wake.text}（${wake.command}）`],
      ["界面", "眼睛"],
      ["后端", backend.url],
      ["Wi-Fi", wifi.skip ? "刷完用手机配网" : wifi.ssid],
    ];
    $("summary").replaceChildren(...facts.flatMap(([k, v]) => [el("dt", k), el("dd", v)]));
  }
  return { wake, backend, wifi };
}

// ---------- wizard ----------

const STEPS = ["step-connect", "step-wake", "step-ui", "step-backend", "step-wifi", "step-flash"];

function reachable(i) {
  return state.valid.slice(0, i).every(Boolean);
}

function render() {
  STEPS.forEach((id, i) => { $(id).hidden = i !== state.step; });
  document.querySelectorAll("#stepper button").forEach((button, i) => {
    button.disabled = state.flashing || (i !== state.step && !reachable(i));
    button.classList.toggle("current", i === state.step);
    button.classList.toggle("done", i !== state.step && i < STEPS.length - 1 && state.valid[i] && reachable(i));
    button.setAttribute("aria-current", i === state.step ? "step" : "false");
  });
  $("prev").hidden = state.step === 0;
  $("prev").disabled = state.flashing;
  $("next").hidden = state.step === STEPS.length - 1;
  $("next").disabled = !state.valid[state.step];
}

function go(step) {
  if (state.flashing || step < 0 || step >= STEPS.length || (step > state.step && !reachable(step))) return;
  state.step = step;
  render();
  $("stepper").scrollIntoView({ block: "start", behavior: "smooth" });
}

// ---------- step 6: flash ----------

async function fetchBytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`下载 ${url} 失败（${response.status}）`);
  return new Uint8Array(await response.arrayBuffer());
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function progress(label, value) {
  $("progress").hidden = false;
  $("progress-label").textContent = label;
  if (value === undefined) $("progress-bar").removeAttribute("value");
  else $("progress-bar").value = value;
}

async function flash() {
  const { wake, backend, wifi } = update();
  if (!state.loader || !state.board) return;
  state.flashing = true;
  state.flashed = false;
  update();
  $("result").hidden = true;
  try {
    const base = `firmware/${state.board.id}/`;
    const manifest = await (await fetch(base + "manifest.json")).json();
    const files = [];
    for (const [i, part] of manifest.parts.entries()) {
      progress(`下载固件 ${i + 1}/${manifest.parts.length}：${part.file}`, (100 * i) / manifest.parts.length);
      let data = await fetchBytes(base + part.file);
      if ((await sha256(data)) !== part.sha256) throw new Error(`${part.file} 校验失败，请刷新页面重试`);
      if (part.file === state.board.assets) {
        const current = wakeWordOf(data);
        if (current?.command !== wake.command || current?.text !== wake.text) {
          data = setWakeWord(data, wake);
          if (data.length > ASSETS_PARTITION_SIZE) throw new Error("资源分区放不下");
          log(`唤醒词改为 ${wake.text}（${wake.command}）`);
        }
      }
      files.push({ data, address: part.offset });
    }
    const uuid = crypto.randomUUID();
    files.push({
      address: NVS_OFFSET,
      data: zongzhuNvs({ uuid, otaUrl: backend.url, ssid: wifi.ssid, password: wifi.password }),
    });
    files.sort((a, b) => a.address - b.address);

    progress("正在擦除整块 Flash（约 30–90 秒，不要拔线）…");
    await state.loader.writeFlash({
      fileArray: files,
      flashMode: "keep", flashFreq: "keep", flashSize: "keep",
      eraseAll: true, compress: true,
      calculateMD5Hash: md5,
      reportProgress: (index, written, total) => {
        progress(`写入第 ${index + 1}/${files.length} 段`, 100 * (index + written / total) / files.length);
      },
    });
    progress("写入完成，校验通过。正在重启板子…", 100);
    const port = state.port;
    await disconnect();
    const boot = await watchBoot(port);
    $("progress").hidden = true;
    state.flashed = true;
    showResult({ uuid, backend, wifi, boot });
  } catch (error) {
    $("progress").hidden = true;
    log(String(error?.stack || error));
    $("result").hidden = false;
    $("result").className = "notice error";
    $("result").textContent = "刷机失败：" + (error?.message || error) +
      "。板子可能处于不完整状态，重新连接后再刷一次即可。";
    await disconnect();
  } finally {
    state.flashing = false;
    $("connect").textContent = "重新连接";
    update();
  }
}

// Reset the board and read its boot log to tell the user whether it got online.
async function watchBoot(port) {
  const status = { wifi: null, backend: false, otaFailed: false, hotspot: null, read: false };
  try {
    await port.open({ baudRate: 115200 });
    await port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await new Promise((r) => setTimeout(r, 100));
    await port.setSignals({ requestToSend: false });
    const reader = port.readable.getReader();
    const decoder = new TextDecoder();
    const timer = setTimeout(() => reader.cancel(), BOOT_LOG_SECONDS * 1000);
    let buffer = "";
    progress("板子已重启，正在看它能不能联网…");
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        status.read = true;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const raw of lines) {
          const line = raw.replace(/\x1b\[[0-9;]*m/g, "").trimEnd();
          // SmartConfig / BluFi log the password; never show it.
          log(line.replace(/(password\s*:?\s*).*/i, "$1***"));
          let m;
          if ((m = line.match(/Connected to WiFi: (.*)$/))) status.wifi = m[1];
          if (/Activation done/.test(line)) status.backend = true;
          if (/Failed to check version/.test(line)) status.otaFailed = true;
          if ((m = line.match(/Access Point started with SSID (\S+)/))) status.hotspot = m[1];
        }
        if (status.backend || status.hotspot || (status.otaFailed && status.wifi)) break;
      }
    } finally {
      clearTimeout(timer);
      try { await reader.cancel(); } catch { /* done */ }
      reader.releaseLock();
    }
  } catch (error) {
    log(`读取开机日志失败：${error}`);
  } finally {
    try { await port.close(); } catch { /* already closed */ }
  }
  return status;
}

function showResult({ uuid, backend, wifi, boot }) {
  const box = $("result");
  box.hidden = false;
  box.replaceChildren();
  let message;
  let kind = "ok";
  if (boot.backend) message = "刷好了，板子已联网并连上后端。说出唤醒词试一下吧。";
  else if (boot.hotspot) {
    message = wifi.skip
      ? `刷好了。手机连接热点 ${boot.hotspot}，浏览器打开 http://192.168.4.1 选择 2.4GHz Wi-Fi。`
      : `板子没能连上 Wi-Fi，已开启热点 ${boot.hotspot}。请检查名称和密码，或用手机连这个热点，打开 http://192.168.4.1 重新配网。`;
    kind = wifi.skip ? "ok" : "warn";
  } else if (boot.wifi && boot.otaFailed) {
    message = `板子已连上 Wi-Fi（${boot.wifi}），但连不上后端 ${backend.url}。请确认后端已启动、地址正确，${backend.mode === "local" ? "电脑和板子在同一个网络，" : ""}然后按一下板子的复位键。`;
    kind = "warn";
  } else if (boot.wifi) message = `板子已连上 Wi-Fi（${boot.wifi}），还没等到后端的回应。启动后端后按一下复位键即可。`;
  else {
    message = boot.read
      ? "刷好了，但在限定时间内没看到联网结果。请看板子屏幕上的提示。"
      : "刷好了。没能读取开机日志，请看板子屏幕上的提示；如果屏幕没反应，按一下复位键。";
    kind = "warn";
  }
  box.className = `notice ${kind}`;
  box.append(el("p", message));
  const facts = [["MAC", state.mac], ["client-id", uuid], ["后端地址", backend.url]];
  const dl = el("dl");
  dl.className = "facts";
  for (const [k, v] of facts) {
    const dd = el("dd");
    dd.append(el("code", v));
    dl.append(el("dt", k), dd);
  }
  box.append(dl);
  box.append(el("p", backend.mode === "server"
    ? "服务器开启了设备白名单时，把上面的 MAC 和 client-id 加进去，板子才能连接。"
    : "后端没有开启白名单时不需要这两项；保存下来，以后换服务器时会用到。"));
}

// ---------- helpers ----------

function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function choice(name, value, title, detail, { disabled = false, checked = false, badge } = {}) {
  const label = el("label");
  label.className = "choice" + (disabled ? " disabled" : "");
  const input = el("input");
  Object.assign(input, { type: "radio", name, value, disabled, checked });
  const span = el("span");
  const b = el("b", title);
  span.append(b);
  if (badge) {
    const tag = el("span", badge[0]);
    tag.className = `badge ${badge[1]}`;
    b.append(tag);
  }
  span.append(el("small", detail));
  label.append(input, span);
  return label;
}

// ---------- init ----------

async function init() {
  $("link-repo").href = REPO;
  for (const a of document.querySelectorAll(".link-backend")) a.href = `${REPO}#2-后端`;
  $("link-deploy").href = `${REPO}/blob/main/deploy/README.md`;
  // The script is served next to this page, so the command follows wherever the page is hosted.
  const script = new URL("install-mac.sh", location.href).href;
  $("install-cmd").textContent = `/bin/bash -c "$(curl -fsSL ${script})"`;
  $("download-install").href = script;
  const isMac = /Mac/i.test(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent);
  $("install-mac").hidden = !isMac;
  $("install-other").hidden = isMac;
  if (!("serial" in navigator)) {
    $("unsupported").hidden = false;
    $("connect").disabled = $("connect-any").disabled = true;
  }
  [state.boards, state.wakewords] = await Promise.all(
    ["boards.json", "wakewords.json"].map(async (f) => (await fetch(f)).json()));
  renderWakewords();

  $("connect").addEventListener("click", () => connect(true));
  $("connect-any").addEventListener("click", () => connect(false));
  $("flash").addEventListener("click", flash);
  $("prev").addEventListener("click", () => go(state.step - 1));
  $("next").addEventListener("click", () => go(state.step + 1));
  $("stepper").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-step]");
    if (button) go(Number(button.dataset.step));
  });
  $("copy-install").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("install-cmd").textContent);
      $("copy-install").textContent = "已复制";
    } catch {
      getSelection().selectAllChildren($("install-cmd"));
      $("copy-install").textContent = "请按 ⌘C";
    }
    setTimeout(() => { $("copy-install").textContent = "复制"; }, 2000);
  });
  document.addEventListener("change", update);
  document.addEventListener("input", (event) => {
    if (event.target.id === "wake-pinyin") state.pinyinTouched = event.target.value !== "";
    if (event.target.id === "wake-text") fillPinyin();
    update();
  });
  navigator.serial?.addEventListener("disconnect", (event) => {
    if (event.target === state.port && !state.flashing) {
      state.transport = state.loader = null;
      $("connect").textContent = "重新连接";
      update();
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if (state.flashing) event.preventDefault();
  });
  update();
}

init();
