/**
 * #999 章节标题双编号归一化 — 格式冲突检测纯函数（前端镜像）
 *
 * hasChineseNumberingPrefix：仅识别「标题开头」的 `第X章` 前缀，
 * X 为中文数字（〇零一二两三四五六七八九十百千、廿=20、卅=30）。
 * 开头为阿拉伯数字（第3章）→ false；前缀不在开头（怀念第一章）→ false；
 * 无前缀纯名（一叶落）→ false；空串 → false。
 */

/** 中文数字字符集（含 廿=20 / 卅=30，与后端前缀识别口径一致） */
const CHINESE_NUMERAL_CHARS = '〇零一二两三四五六七八九十百千廿卅';

export function hasChineseNumberingPrefix(title: string): boolean {
  return new RegExp(`^第[${CHINESE_NUMERAL_CHARS}]+章`).test(title);
}
