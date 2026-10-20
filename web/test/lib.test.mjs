// cd web && npm test
// Set NVS_TOOL=<ESP-IDF>/components/nvs_flash/nvs_partition_tool/nvs_tool.py to also
// check the generated NVS image with ESP-IDF's own parser.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import zlib from "node:zlib";

import { parseAppDesc } from "../lib/appdesc.js";
import { packAssets, readAssets, setWakeWord, wakeWordOf } from "../lib/assets.js";
import { md5 } from "../lib/md5.js";
import { buildNvs, crc32, zongzhuNvs } from "../lib/nvs.js";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const PACKAGES = {
  szp: join(ROOT, "firmware/zongzhu-szp-2.5.2.9"),
  "1.75c": join(ROOT, "firmware/zongzhu-1.75c-2.5.2.9"),
};
const ASSETS = { szp: "generated_assets.bin", "1.75c": "assets.bin" };

test("crc32 matches zlib.crc32(data, 0xFFFFFFFF)", () => {
  for (const size of [0, 1, 28, 1000]) {
    const data = randomBytes(size);
    assert.equal(crc32(data), zlib.crc32(data, 0xffffffff));
  }
});

test("md5 matches node crypto", () => {
  for (const size of [0, 55, 56, 64, 1000, 70000]) {
    const data = randomBytes(size);
    assert.equal(md5(data), createHash("md5").update(data).digest("hex"));
  }
});

test("NVS image holds the Zongzhu settings", () => {
  const image = zongzhuNvs({
    uuid: "d2587624-0e1d-4554-bdc0-c10e5608e97e",
    otaUrl: "http://my-mac.local:8003/xiaozhi/ota/",
    ssid: "测试网络-2.4G",
    password: "pass word 123",
  });
  assert.equal(image.length, 0x4000);
  // Header CRC as NVS computes it.
  const header = image.subarray(0, 32);
  assert.equal(new DataView(header.buffer).getUint32(28, true), crc32(header.subarray(4, 28)));
  // Pages 1-3 stay erased.
  assert.ok(image.subarray(4096).every((b) => b === 0xff));

  const tool = process.env.NVS_TOOL;
  if (!tool) return;
  const dir = mkdtempSync(join(tmpdir(), "nvs-"));
  const file = join(dir, "nvs.bin");
  writeFileSync(file, image);
  const integrity = execFileSync("python3", [tool, "-d", "none", "-i", file]).toString();
  assert.match(integrity, /Page no\. 0\s+CRC32: OK/);
  assert.doesNotMatch(integrity, /mismatch|invalid|error/i);
  const dump = execFileSync("python3", [tool, "-d", "minimal", file]).toString().replaceAll("\0", "");
  for (const line of [
    "board:uuid = d2587624-0e1d-4554-bdc0-c10e5608e97e",
    "wifi:ota_url = http://my-mac.local:8003/xiaozhi/ota/",
    "wifi:ssid = 测试网络-2.4G",
    "wifi:password = pass word 123",
  ]) assert.ok(dump.includes(line), `${line}\n---\n${dump}`);
});

test("NVS without Wi-Fi keeps only the OTA address and client-id", () => {
  const image = zongzhuNvs({ uuid: "u", otaUrl: "https://example.com/xiaozhi/ota/" });
  const text = new TextDecoder().decode(image);
  assert.ok(text.includes("ota_url") && !text.includes("ssid"));
});

test("NVS rejects keys longer than 15 bytes and overfull pages", () => {
  assert.throws(() => buildNvs([{ ns: "wifi", key: "a".repeat(16), type: "u8", value: 1 }]));
  const many = Array.from({ length: 40 }, (_, i) => ({ ns: "x", key: `k${i}`, type: "string", value: "y".repeat(80) }));
  assert.throws(() => buildNvs(many), /full/);
});

for (const [board, dir] of Object.entries(PACKAGES)) {
  const original = new Uint8Array(readFileSync(join(dir, ASSETS[board])));

  test(`${board}: assets repack is byte-identical to the build script output`, () => {
    assert.deepEqual(packAssets(readAssets(original)), original);
  });

  test(`${board}: wake word can be changed and read back`, () => {
    assert.deepEqual(wakeWordOf(original), { command: "ni hao zong zhu", text: "你好宗主", action: "wake" });
    const changed = setWakeWord(original, { command: "ni hao xiao yu", text: "你好小雨" });
    assert.deepEqual(wakeWordOf(changed), { command: "ni hao xiao yu", text: "你好小雨", action: "wake" });
    // Every other file is untouched; checksum covers the new content.
    const before = readAssets(original), after = readAssets(changed);
    assert.equal(after.length, before.length);
    before.forEach((f, i) => f.name !== "index.json" && assert.deepEqual(after[i].data, f.data));
    const view = new DataView(changed.buffer);
    let sum = 0;
    for (let i = 12; i < changed.length; i++) sum = (sum + changed[i]) & 0xffff;
    assert.equal(view.getUint32(4, true), sum);
    assert.ok(changed.length <= 8 * 1024 * 1024);
  });

  test(`${board}: app descriptor`, () => {
    const app = new Uint8Array(readFileSync(join(dir, "xiaozhi.bin")));
    const desc = parseAppDesc(app.subarray(0, 0x100));
    assert.equal(desc.version, "2.5.2.9");
    assert.equal(desc.project, "xiaozhi");
    assert.equal(parseAppDesc(new Uint8Array(0x100).fill(0xff)), null);
  });
}
