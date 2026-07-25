/**
 * Dependency-free PNG decode + deterministic diff for the SAATHI-286 calendar
 * visual harness. Committed to the repo so a clean checkout runs the visual gate
 * with only `playwright` (already a dependency) — no pixelmatch/pngjs install.
 *
 * Supports the PNGs Playwright emits: 8-bit, non-interlaced, colour type 2 (RGB)
 * or 6 (RGBA). Anything else throws (never a silent wrong result).
 */
import { inflateSync } from 'node:zlib';

const SIG = [137, 80, 78, 71, 13, 10, 26, 10];

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** Decode a PNG buffer into { width, height, data } where data is RGBA bytes. */
export function decodePng(buffer) {
  for (let i = 0; i < 8; i++) if (buffer[i] !== SIG[i]) throw new Error('not a PNG');
  let pos = 8;
  let width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
  const idat = [];
  while (pos < buffer.length) {
    const len = buffer.readUInt32BE(pos);
    const type = buffer.toString('ascii', pos + 4, pos + 8);
    const data = buffer.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === 'IDAT') {
      idat.push(Buffer.from(data));
    } else if (type === 'IEND') {
      break;
    }
    pos += 12 + len;
  }
  if (bitDepth !== 8 || interlace !== 0 || (colorType !== 2 && colorType !== 6)) {
    throw new Error(`unsupported PNG (bitDepth=${bitDepth}, colorType=${colorType}, interlace=${interlace})`);
  }
  const channels = colorType === 6 ? 4 : 3;
  const stride = width * channels;
  const raw = inflateSync(Buffer.concat(idat));
  const recon = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const ft = raw[y * (stride + 1)];
    const rowStart = y * (stride + 1) + 1;
    for (let x = 0; x < stride; x++) {
      const val = raw[rowStart + x];
      const a = x >= channels ? recon[y * stride + x - channels] : 0;
      const b = y > 0 ? recon[(y - 1) * stride + x] : 0;
      const c = x >= channels && y > 0 ? recon[(y - 1) * stride + x - channels] : 0;
      let r;
      if (ft === 0) r = val;
      else if (ft === 1) r = val + a;
      else if (ft === 2) r = val + b;
      else if (ft === 3) r = val + Math.floor((a + b) / 2);
      else if (ft === 4) r = val + paeth(a, b, c);
      else throw new Error(`bad filter ${ft}`);
      recon[y * stride + x] = r & 0xff;
    }
  }
  // Expand to RGBA.
  const rgba = new Uint8Array(width * height * 4);
  for (let p = 0; p < width * height; p++) {
    rgba[p * 4] = recon[p * channels];
    rgba[p * 4 + 1] = recon[p * channels + 1];
    rgba[p * 4 + 2] = recon[p * channels + 2];
    rgba[p * 4 + 3] = channels === 4 ? recon[p * channels + 3] : 255;
  }
  return { width, height, data: rgba };
}

/** Deterministic nearest-neighbour resize to (tw, th). A real resize — never a crop. */
export function resizeNearest(img, tw, th) {
  const out = new Uint8Array(tw * th * 4);
  for (let y = 0; y < th; y++) {
    const sy = Math.min(img.height - 1, Math.floor((y * img.height) / th));
    for (let x = 0; x < tw; x++) {
      const sx = Math.min(img.width - 1, Math.floor((x * img.width) / tw));
      const si = (sy * img.width + sx) * 4;
      const di = (y * tw + x) * 4;
      out[di] = img.data[si];
      out[di + 1] = img.data[si + 1];
      out[di + 2] = img.data[si + 2];
      out[di + 3] = img.data[si + 3];
    }
  }
  return { width: tw, height: th, data: out };
}

/**
 * Deterministic diff of two PNG buffers.
 *  - Aligns both to a documented common coordinate system (the min width/height)
 *    via a real nearest-neighbour resize — content is mapped, never discarded.
 *  - Reports both source dimensions and a dimensionDrift flag; large drift
 *    (> driftTolerance fraction) is treated as a failure by the caller.
 *  - A pixel counts as changed when any channel differs by more than
 *    `channelThreshold` (grayscale units), matching the QA >16 method.
 */
export function diffPngBuffers(aBuf, bBuf, { channelThreshold = 16, driftTolerance = 0.02 } = {}) {
  const a = decodePng(aBuf);
  const b = decodePng(bBuf);
  const tw = Math.min(a.width, b.width);
  const th = Math.min(a.height, b.height);
  const ra = a.width === tw && a.height === th ? a : resizeNearest(a, tw, th);
  const rb = b.width === tw && b.height === th ? b : resizeNearest(b, tw, th);
  let changed = 0;
  for (let p = 0; p < tw * th; p++) {
    const i = p * 4;
    const d = Math.max(
      Math.abs(ra.data[i] - rb.data[i]),
      Math.abs(ra.data[i + 1] - rb.data[i + 1]),
      Math.abs(ra.data[i + 2] - rb.data[i + 2]),
      Math.abs(ra.data[i + 3] - rb.data[i + 3]),
    );
    if (d > channelThreshold) changed++;
  }
  const widthDrift = Math.abs(a.width - b.width) / Math.max(a.width, b.width);
  const heightDrift = Math.abs(a.height - b.height) / Math.max(a.height, b.height);
  const drift = Math.max(widthDrift, heightDrift);
  return {
    percent: (changed / (tw * th)) * 100,
    aDims: { width: a.width, height: a.height },
    bDims: { width: b.width, height: b.height },
    target: { width: tw, height: th },
    dimensionDrift: drift > driftTolerance,
    driftFraction: Number(drift.toFixed(4)),
    changed,
    total: tw * th,
  };
}
