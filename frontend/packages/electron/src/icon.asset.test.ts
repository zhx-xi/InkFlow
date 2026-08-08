/**
 * 回归防护（#192 F4，2026-08-08）：托盘图标源图完整性。
 *
 * 背景：rc2 复验发现托盘 logo 只显示左半/右半被裁——根因 = 源图
 * `inkflow-icon-256.png` 渲染损坏（alpha 内容仅占右半，bbox 107,0-255,255，
 * 中心偏移 dx=+53.5px；品牌资产包 512/128/48/32/16 全部居中，仅 256 版损坏）。
 * 修复 = 从 512 居中版 HighQualityBicubic 重生成（bbox 0-255，dx=0）。
 *
 * 本测试防止源图再次被损坏/替换：解码 PNG（非交错 RGBA）→ 扫描 alpha
 * bbox → 断言内容居中（dx/dy ≤ 5px）且非空。纯 node 实现（无第三方依赖）。
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import path from 'node:path';

const ICON = path.resolve(__dirname, '..', 'inkflow-icon-256.png');

/** 最小 PNG 解码（8-bit RGBA 非交错）：返回 { width, height, pixels(RGBA) } */
function decodePng(buf: Buffer): { width: number; height: number; pixels: Uint8Array } {
  // 签名 8 字节
  expect(buf.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  const width = buf.readUInt32BE(16);
  const height = buf.readUInt32BE(20);
  const bitDepth = buf[24];
  const colorType = buf[25];
  expect(bitDepth).toBe(8);
  expect(colorType).toBe(6); // RGBA（托盘源图必须带 alpha）

  // 收集 IDAT
  const chunks: Buffer[] = [];
  let off = 8;
  for (;;) {
    const len = buf.readUInt32BE(off);
    const type = buf.subarray(off + 4, off + 8).toString('ascii');
    if (type === 'IDAT') chunks.push(buf.subarray(off + 8, off + 8 + len));
    if (type === 'IEND') break;
    off += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(chunks));

  // 逐行 unfilter（filter 0-4，Paeth 预测器）
  const bpp = 4;
  const stride = width * bpp;
  const pixels = new Uint8Array(width * height * bpp);
  let src = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[src++];
    const row = y * stride;
    for (let x = 0; x < stride; x++) {
      const left = x >= bpp ? pixels[row + x - bpp] : 0;
      const up = y > 0 ? pixels[row - stride + x] : 0;
      const upLeft = x >= bpp && y > 0 ? pixels[row - stride + x - bpp] : 0;
      let v = raw[src++];
      switch (filter) {
        case 0:
          break;
        case 1:
          v += left;
          break;
        case 2:
          v += up;
          break;
        case 3:
          v += (left + up) >> 1;
          break;
        case 4: {
          const p = left + up - upLeft;
          const pa = Math.abs(p - left);
          const pb = Math.abs(p - up);
          const pc = Math.abs(p - upLeft);
          v += pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
          break;
        }
        default:
          throw new Error(`unknown PNG filter ${filter}`);
      }
      pixels[row + x] = v & 0xff;
    }
  }
  return { width, height, pixels };
}

describe('托盘图标源图完整性（#192 F4 回归防护）', () => {
  it('inkflow-icon-256.png：256x256 RGBA + alpha 内容居中（dx/dy ≤ 5px）+ 非空', () => {
    const buf = readFileSync(ICON);
    const { width, height, pixels } = decodePng(buf);
    expect(width).toBe(256);
    expect(height).toBe(256);

    let minX = 999;
    let minY = 999;
    let maxX = -1;
    let maxY = -1;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (pixels[(y * width + x) * 4 + 3] > 0) {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }
      }
    }
    // 非空（#192 F4 损坏版内容仅右半 149px——此处保证内容存在且不偏）
    expect(maxX).toBeGreaterThan(0);
    expect(maxY).toBeGreaterThan(0);
    const dx = (minX + maxX) / 2 - (width - 1) / 2;
    const dy = (minY + maxY) / 2 - (height - 1) / 2;
    expect(Math.abs(dx)).toBeLessThanOrEqual(5);
    expect(Math.abs(dy)).toBeLessThanOrEqual(5);
  });
});
