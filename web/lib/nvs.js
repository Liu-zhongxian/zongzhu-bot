// Builds an ESP-IDF NVS partition image (format version 2) in the browser, so Wi-Fi,
// the OTA address and the client-id can be written together with the firmware.
// Only what the firmware reads is supported: strings and u8 values, all on page 0.

const PAGE = 4096;
const ENT = 32;
const ENTRIES = 126;
const TYPE_U8 = 0x01;
const TYPE_STR = 0x21;

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

// Same as zlib.crc32(data, 0xFFFFFFFF), which is what NVS uses.
export function crc32(bytes, init = 0xffffffff) {
  let c = ~init >>> 0;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return ~c >>> 0;
}

function u32(view, offset, value) {
  view.setUint32(offset, value >>> 0, true);
}

function entryCrc(entry) {
  const data = new Uint8Array(28);
  data.set(entry.subarray(0, 4), 0);
  data.set(entry.subarray(8, 32), 4);
  return crc32(data);
}

function writeKey(entry, key) {
  const bytes = new TextEncoder().encode(key);
  if (bytes.length === 0 || bytes.length > 15) throw new Error(`NVS key too long: ${key}`);
  entry.fill(0, 8, 24);
  entry.set(bytes, 8);
}

/**
 * items: [{ ns: "wifi", key: "ssid", type: "string" | "u8", value }]
 * Returns a Uint8Array of `size` bytes (default 16 KiB, the nvs partition on both boards).
 */
export function buildNvs(items, size = 0x4000) {
  const image = new Uint8Array(size).fill(0xff);
  const page = image.subarray(0, PAGE);
  const view = new DataView(image.buffer, image.byteOffset, PAGE);

  // Page header: state ACTIVE, sequence 0, version 0xFE (v2), CRC over bytes 4..28.
  u32(view, 0, 0xfffffffe);
  u32(view, 4, 0);
  page[8] = 0xfe;
  u32(view, 28, crc32(page.subarray(4, 28)));

  let slot = 0;
  const namespaces = new Map();

  function take(count) {
    if (slot + count > ENTRIES) throw new Error("NVS page full");
    const start = slot;
    for (let i = start; i < start + count; i++) {
      const byte = 32 + (i >> 2);
      const shift = (i & 3) * 2;
      page[byte] = (page[byte] & ~(3 << shift)) | (0b10 << shift); // WRITTEN
    }
    slot += count;
    return start;
  }

  function entryAt(index) {
    return page.subarray(64 + index * ENT, 64 + (index + 1) * ENT);
  }

  function namespaceIndex(name) {
    if (!namespaces.has(name)) {
      const index = namespaces.size + 1;
      const entry = entryAt(take(1));
      entry[0] = 0;
      entry[1] = TYPE_U8;
      entry[2] = 1;
      entry[3] = 0xff;
      writeKey(entry, name);
      entry[24] = index;
      new DataView(entry.buffer, entry.byteOffset).setUint32(4, entryCrc(entry), true);
      namespaces.set(name, index);
    }
    return namespaces.get(name);
  }

  for (const item of items) {
    const ns = namespaceIndex(item.ns);
    if (item.type === "u8") {
      const entry = entryAt(take(1));
      entry[0] = ns;
      entry[1] = TYPE_U8;
      entry[2] = 1;
      entry[3] = 0xff;
      writeKey(entry, item.key);
      entry[24] = item.value & 0xff;
      new DataView(entry.buffer, entry.byteOffset).setUint32(4, entryCrc(entry), true);
    } else if (item.type === "string") {
      const payload = new Uint8Array([...new TextEncoder().encode(item.value), 0]);
      if (payload.length > 4000) throw new Error(`NVS string too long: ${item.key}`);
      const dataEntries = Math.ceil(payload.length / ENT);
      const start = take(1 + dataEntries);
      const entry = entryAt(start);
      const ev = new DataView(entry.buffer, entry.byteOffset, ENT);
      entry[0] = ns;
      entry[1] = TYPE_STR;
      entry[2] = 1 + dataEntries;
      entry[3] = 0xff;
      writeKey(entry, item.key);
      ev.setUint16(24, payload.length, true);
      ev.setUint16(26, 0xffff, true);
      ev.setUint32(28, crc32(payload), true);
      ev.setUint32(4, entryCrc(entry), true);
      page.set(payload, 64 + (start + 1) * ENT); // the remainder stays 0xFF
    } else {
      throw new Error(`Unsupported NVS type: ${item.type}`);
    }
  }
  return image;
}

/** The settings the Zongzhu firmware reads at boot. Wi-Fi is optional. */
export function zongzhuNvs({ uuid, otaUrl, ssid, password }) {
  const items = [{ ns: "board", key: "uuid", type: "string", value: uuid }];
  items.push({ ns: "wifi", key: "ota_url", type: "string", value: otaUrl });
  if (ssid) {
    items.push({ ns: "wifi", key: "ssid", type: "string", value: ssid });
    items.push({ ns: "wifi", key: "password", type: "string", value: password || "" });
  }
  return buildNvs(items);
}
