/**
 * #477 聊天回复意图分离：<<<CONTENT>>> / <<<END>>> 标记解析（纯函数）
 *
 * 语义（6 条，测试逐条锁定）：
 * 1. 含成对标记（start 后出现 end）→ intent='content'，body = 两标记之间文本 trim（保留内部换行）
 * 2. 无 start 标记 → intent='conversation'，body = raw 原文
 * 3. 有 start 无 end → intent='content'，body = start 之后全部文本 trim（容错恢复）
 * 4. 只有 end 无 start → intent='conversation'，body = raw 原文
 * 5. content 解析后 body trim 为空 → 降级 intent='conversation'，body = raw 原文
 * 6. 只解析第一对标记；body 内部多余标记按字面保留（不递归解析）
 */

export const CONTENT_START_MARKER = '<<<CONTENT>>>';
export const CONTENT_END_MARKER = '<<<END>>>';

export type ChatIntent = 'content' | 'conversation';

export interface ParsedChatReply {
  intent: ChatIntent;
  body: string;
}

export function parseChatReply(raw: string): ParsedChatReply {
  const startIndex = raw.indexOf(CONTENT_START_MARKER);
  // 语义 2/4：无 start 标记（含只有 end）→ conversation，body = raw 原文
  if (startIndex === -1) {
    return { intent: 'conversation', body: raw };
  }
  const bodyStart = startIndex + CONTENT_START_MARKER.length;
  // 语义 6：只取第一对标记——end 从 start 之后开始查找，body 内部多余标记按字面保留
  const endIndex = raw.indexOf(CONTENT_END_MARKER, bodyStart);
  // 语义 1/3：有 end → 截取标记之间；无 end → 容错取 start 之后全部文本
  const body = (endIndex === -1 ? raw.slice(bodyStart) : raw.slice(bodyStart, endIndex)).trim();
  // 语义 5：content 解析后 body 为空（标记间空白 / 纯空白 raw）→ 降级 conversation
  if (body === '') {
    return { intent: 'conversation', body: raw };
  }
  return { intent: 'content', body };
}
