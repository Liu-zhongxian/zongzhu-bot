// Rewrites the wake word inside a xiaozhi assets partition image.
//
// The firmware reads the custom wake word from index.json's "multinet_model" in the
// assets partition (main/audio/wake_words/custom_wake_word.cc), so changing it needs
// no rebuild. The layout matches pack_assets_simple() in scripts/build_default_assets.py:
//   u32 file count | u32 checksum | u32 length | table | data
//   table entry: name[32] | u32 size | u32 offset | u16 width | u16 height
//   each file in data is prefixed with "ZZ" (0x5A5A); offsets are relative to data start
//   checksum = sum of (table + data) bytes & 0xFFFF

const NAME_LEN = 32;
const TABLE_ENTRY = 44;

export function readAssets(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint32(0, true);
  const length = view.getUint32(8, true);
  const tableEnd = 12 + count * TABLE_ENTRY;
  if (count === 0 || count > 1000 || 12 + length > bytes.length) throw new Error("不是有效的资源分区文件");
  const files = [];
  for (let i = 0; i < count; i++) {
    const base = 12 + i * TABLE_ENTRY;
    const nameBytes = bytes.subarray(base, base + NAME_LEN);
    const end = nameBytes.indexOf(0);
    const name = new TextDecoder().decode(end < 0 ? nameBytes : nameBytes.subarray(0, end));
    const size = view.getUint32(base + 32, true);
    const offset = view.getUint32(base + 36, true);
    const start = tableEnd + offset;
    if (bytes[start] !== 0x5a || bytes[start + 1] !== 0x5a) throw new Error(`资源文件 ${name} 格式不对`);
    files.push({
      name, width: view.getUint16(base + 40, true), height: view.getUint16(base + 42, true),
      data: bytes.subarray(start + 2, start + 2 + size),
    });
  }
  return files;
}

export function packAssets(files) {
  const total = files.reduce((n, f) => n + 2 + f.data.length, 0);
  const tableLen = files.length * TABLE_ENTRY;
  const out = new Uint8Array(12 + tableLen + total);
  const view = new DataView(out.buffer);
  let offset = 0;
  files.forEach((file, i) => {
    const base = 12 + i * TABLE_ENTRY;
    const name = new TextEncoder().encode(file.name).subarray(0, NAME_LEN);
    out.set(name, base);
    view.setUint32(base + 32, file.data.length, true);
    view.setUint32(base + 36, offset, true);
    view.setUint16(base + 40, file.width, true);
    view.setUint16(base + 42, file.height, true);
    const start = 12 + tableLen + offset;
    out[start] = 0x5a;
    out[start + 1] = 0x5a;
    out.set(file.data, start + 2);
    offset += 2 + file.data.length;
  });
  let checksum = 0;
  for (let i = 12; i < out.length; i++) checksum = (checksum + out[i]) & 0xffff;
  view.setUint32(0, files.length, true);
  view.setUint32(4, checksum, true);
  view.setUint32(8, tableLen + total, true);
  return out;
}

export function wakeWordOf(bytes) {
  const index = readAssets(bytes).find((f) => f.name === "index.json");
  const model = index && JSON.parse(new TextDecoder().decode(index.data)).multinet_model;
  return model?.commands?.find((c) => c.action === "wake") ?? null;
}

/** command: pinyin without tones, e.g. "ni hao zong zhu"; text: the Chinese wake word. */
export function setWakeWord(bytes, { command, text, threshold }) {
  const files = readAssets(bytes);
  const index = files.find((f) => f.name === "index.json");
  if (!index) throw new Error("资源分区里没有 index.json");
  const json = JSON.parse(new TextDecoder().decode(index.data));
  if (!json.multinet_model) throw new Error("这个固件的资源分区不支持自定义唤醒词");
  json.multinet_model.commands = [{ command, text, action: "wake" }];
  if (threshold !== undefined) json.multinet_model.threshold = threshold;
  index.data = new TextEncoder().encode(JSON.stringify(json, null, 4));
  return packAssets(files);
}
