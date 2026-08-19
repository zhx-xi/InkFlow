/**
 * #477 聊天回复意图分离：parseChatReply 纯函数契约
 *
 * 导出契约（GREEN 建 src/lib/chatIntent.ts）：
 * - export const CONTENT_START_MARKER = '<<<CONTENT>>>'
 * - export const CONTENT_END_MARKER = '<<<END>>>'
 * - export type ChatIntent = 'content' | 'conversation'
 * - export interface ParsedChatReply { intent: ChatIntent; body: string }
 * - export function parseChatReply(raw: string): ParsedChatReply
 *
 * 语义（6 条，逐条锁定）：
 * 1. 含成对标记（start 后出现 end）→ intent='content'，body = 两标记之间文本 trim（保留内部换行）
 * 2. 无 start 标记 → intent='conversation'，body = raw 原文
 * 3. 有 start 无 end → intent='content'，body = start 之后全部文本 trim（容错恢复）
 * 4. 只有 end 无 start → intent='conversation'，body = raw 原文
 * 5. content 解析结果 body 为空串（trim 后空，含「标记间空」与「纯空白 raw」）
 *    → 降级 intent='conversation'，body = raw 原文
 * 6. 解析只取第一对标记；body 内部出现多余标记按字面保留（不递归解析）
 *
 * RED 形态：src/lib/chatIntent.ts 不存在 → import 失败（文件级 module-not-found）。
 */
import { describe, it, expect } from 'vitest';
import {
  CONTENT_START_MARKER,
  CONTENT_END_MARKER,
  parseChatReply,
  type ChatIntent,
  type ParsedChatReply,
} from './chatIntent';

describe('chatIntent — 常量导出契约（#477）', () => {
  it('导出标记常量 CONTENT_START_MARKER / CONTENT_END_MARKER', () => {
    expect(CONTENT_START_MARKER).toBe('<<<CONTENT>>>');
    expect(CONTENT_END_MARKER).toBe('<<<END>>>');
  });
});

describe('chatIntent — parseChatReply 语义（#477）', () => {
  it('语义 1：成对标记 → content，body = 标记间文本 trim（去掉前言）', () => {
    const r: ParsedChatReply = parseChatReply('好的，以下是续写内容：\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>');
    const intent: ChatIntent = r.intent;
    expect(intent).toBe('content');
    expect(r.body).toBe('他握紧了剑。');
  });

  it('语义 1 补充：多行 body 保留内部换行（仅 trim 首尾空白）', () => {
    const r = parseChatReply('<<<CONTENT>>>\n第一段。\n\n第二段。\n<<<END>>>');
    expect(r.intent).toBe('content');
    expect(r.body).toBe('第一段。\n\n第二段。');
  });

  it('语义 2：无 start 标记 → conversation，body = raw 原文', () => {
    const raw = '对话回复内容';
    const r = parseChatReply(raw);
    expect(r.intent).toBe('conversation');
    expect(r.body).toBe(raw);
  });

  it('语义 3：有 start 无 end → content，body = start 之后全部文本 trim（容错恢复）', () => {
    const r = parseChatReply('好的：\n<<<CONTENT>>>\n他握紧了剑。\n（回复被截断');
    expect(r.intent).toBe('content');
    expect(r.body).toBe('他握紧了剑。\n（回复被截断');
  });

  it('语义 4：只有 end 无 start → conversation，body = raw 原文', () => {
    const raw = '这个问题我不太确定<<<END>>>';
    const r = parseChatReply(raw);
    expect(r.intent).toBe('conversation');
    expect(r.body).toBe(raw);
  });

  it('语义 5：标记间为空白（trim 后空）→ 降级 conversation，body = raw 原文', () => {
    const raw = '前言\n<<<CONTENT>>>\n   \n<<<END>>>';
    const r = parseChatReply(raw);
    expect(r.intent).toBe('conversation');
    expect(r.body).toBe(raw);
  });

  it('语义 5 补充：纯空白 raw（无标记）→ conversation，body = raw 原文', () => {
    const raw = '   \n  ';
    const r = parseChatReply(raw);
    expect(r.intent).toBe('conversation');
    expect(r.body).toBe(raw);
  });

  it('语义 6：只取第一对标记；body 内部多余标记按字面保留（不递归解析）', () => {
    const r = parseChatReply('<<<CONTENT>>>\n第一段 <<<CONTENT>>> 嵌套标记\n<<<END>>> 尾部');
    expect(r.intent).toBe('content');
    expect(r.body).toBe('第一段 <<<CONTENT>>> 嵌套标记');
  });
});
