// Reads esp_app_desc_t from the start of an app partition, to show what the board runs now.
// The descriptor sits right after the image header (24 bytes) and first segment header (8).

const MAGIC = 0xabcd5432;

function cstr(bytes) {
  const end = bytes.indexOf(0);
  return new TextDecoder().decode(end < 0 ? bytes : bytes.subarray(0, end));
}

/** bytes: at least the first 0x100 bytes of an app partition. */
export function parseAppDesc(bytes) {
  if (bytes.length < 0x100 || bytes[0] !== 0xe9) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(32, true) !== MAGIC) return null;
  return {
    version: cstr(bytes.subarray(48, 80)),
    project: cstr(bytes.subarray(80, 112)),
    time: cstr(bytes.subarray(112, 128)),
    date: cstr(bytes.subarray(128, 144)),
    idf: cstr(bytes.subarray(144, 176)),
  };
}
