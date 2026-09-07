/**
 * chapterTitleFormat 纯函数契约测试（Issue #999 章节标题双编号归一化，RED-3 批）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 frontend/packages/renderer/src/lib/chapterTitleFormat.ts
 * 并导出 `hasChineseNumberingPrefix(title: string): boolean`：
 *   - 仅识别「标题开头」的 `第X章` 前缀（X = 中文数字：〇零一二两三...十百千、廿=20、卅=30）；
 *   - 开头为阿拉伯数字前缀（如 `第3章`）→ false；前缀不在开头（如 `怀念第一章`）→ false；
 *   - 无前缀纯名（`一叶落`）→ false；空串 → false。
 *
 * RED 期该模块不存在 → import 解析失败 = 预期文件级失败。
 */
import { describe, it, expect } from 'vitest';
import { hasChineseNumberingPrefix } from './chapterTitleFormat';

describe('chapterTitleFormat — hasChineseNumberingPrefix', () => {
  it.each([
    // [title, expected]
    ['第一章 风起', true],
    ['第卅章', true],
    ['第3章 起点', false],
    ['一叶落', false],
    ['怀念第一章', false],
    ['第二章第1章 x', true],
    ['', false],
    ['第三百章', true],
  ])('%j → %s', (title, expected) => {
    expect(hasChineseNumberingPrefix(title as string)).toBe(expected);
  });
});
