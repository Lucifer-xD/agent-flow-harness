// Generates placeholder icons so builds don't fail before the real artwork exists:
//   desktop/build/icon.ico   (16/32/48/256 px, PNG-compressed entries; used by electron-builder)
//   desktop/assets/icon.png  (256 px; window + tray icon at runtime)
// Pure Node, no dependencies. Run: node scripts/make-placeholder-icon.js
"use strict";

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const desktop = path.resolve(__dirname, "..", "desktop");

// ---- PNG encoder --------------------------------------------------------------------------

const CRC_TABLE = new Int32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});
function crc32(buf) {
  let c = -1;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function png(size, pixel) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x, y, size);
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = r;
      raw[o + 1] = g;
      raw[o + 2] = b;
      raw[o + 3] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ---- artwork: dark rounded tile with an amber "flow" arrow ----------------------------------

function pixel(x, y, size) {
  const u = (x + 0.5) / size;
  const v = (y + 0.5) / size;
  const radius = 0.22;
  // rounded-square mask
  const cx = Math.max(Math.abs(u - 0.5) - (0.5 - radius), 0);
  const cy = Math.max(Math.abs(v - 0.5) - (0.5 - radius), 0);
  if (Math.hypot(cx, cy) > radius) return [0, 0, 0, 0];

  // chevron ">" pointing right, drawn as two strokes
  const sx = u - 0.5;
  const sy = v - 0.5;
  const stroke = 0.075;
  const d1 = Math.abs(sy + (sx - 0.08)); // upper stroke of the chevron
  const d2 = Math.abs(sy - (sx - 0.08)); // lower stroke of the chevron
  const inUpper = d1 < stroke && sx > -0.22 && sx < 0.12 && sy <= 0.02;
  const inLower = d2 < stroke && sx > -0.22 && sx < 0.12 && sy >= -0.02;
  const inBar = Math.abs(sy) < stroke * 0.8 && sx > 0.1 && sx < 0.32;
  if (inUpper || inLower || inBar) return [232, 144, 58, 255]; // amber accent
  return [15, 13, 12, 255]; // #0f0d0c background
}

// ---- ICO container (PNG-compressed entries) --------------------------------------------------

function ico(sizes) {
  const images = sizes.map((s) => ({ size: s, data: png(s, pixel) }));
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(images.length, 4);
  const dir = Buffer.alloc(16 * images.length);
  let offset = header.length + dir.length;
  images.forEach((img, i) => {
    const o = i * 16;
    dir[o] = img.size >= 256 ? 0 : img.size; // width (0 means 256)
    dir[o + 1] = img.size >= 256 ? 0 : img.size; // height
    dir[o + 2] = 0; // palette
    dir[o + 3] = 0; // reserved
    dir.writeUInt16LE(1, o + 4); // planes
    dir.writeUInt16LE(32, o + 6); // bpp
    dir.writeUInt32LE(img.data.length, o + 8);
    dir.writeUInt32LE(offset, o + 12);
    offset += img.data.length;
  });
  return Buffer.concat([header, dir, ...images.map((i) => i.data)]);
}

fs.mkdirSync(path.join(desktop, "build"), { recursive: true });
fs.mkdirSync(path.join(desktop, "assets"), { recursive: true });
const icoPath = path.join(desktop, "build", "icon.ico");
const pngPath = path.join(desktop, "assets", "icon.png");
fs.writeFileSync(icoPath, ico([16, 32, 48, 256]));
fs.writeFileSync(pngPath, png(256, pixel));
console.log("wrote", icoPath);
console.log("wrote", pngPath);
