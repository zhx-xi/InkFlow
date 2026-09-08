/**
 * F59-M3 (#964)：chat 思考级别七档常量 + per-project localStorage 记忆。
 *
 * - 七档顺序即 UI 选项顺序（plan §四 REASONING_EFFORTS 逐字）。
 * - key = inkflow.reasoning_effort.<projectId>（跨项目隔离）。
 * - read/write 均包 try/catch：隐私模式等存储不可用时静默回退，不崩 UI。
 * - write 仅接受七档值；非法值 no-op（不写入、不覆盖既有记忆）。
 */

export const REASONING_EFFORTS = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'default',
] as const;

export type ReasoningEffort = (typeof REASONING_EFFORTS)[number];

export const DEFAULT_REASONING_EFFORT: ReasoningEffort = 'default';

export const REASONING_EFFORT_STORAGE_PREFIX = 'inkflow.reasoning_effort.';

export function reasoningEffortStorageKey(projectId: string): string {
  return `${REASONING_EFFORT_STORAGE_PREFIX}${projectId}`;
}

function isReasoningEffort(value: string | null): value is ReasoningEffort {
  return value !== null && (REASONING_EFFORTS as readonly string[]).includes(value);
}

/** 读取 projectId 的档位记忆；缺失 / 非七档 / JSON 解析异常 → 'default'（不抛错）。 */
export function readReasoningEffort(projectId: string): ReasoningEffort {
  try {
    const raw = localStorage.getItem(reasoningEffortStorageKey(projectId));
    return isReasoningEffort(raw) ? raw : DEFAULT_REASONING_EFFORT;
  } catch {
    // 隐私模式 / 存储不可用：静默回退默认档
    return DEFAULT_REASONING_EFFORT;
  }
}

/** 写入 projectId 的档位记忆；value 不在七档 → no-op（不写入）。 */
export function writeReasoningEffort(projectId: string, value: string): void {
  if (!isReasoningEffort(value)) return;
  try {
    localStorage.setItem(reasoningEffortStorageKey(projectId), value);
  } catch {
    // 隐私模式 / 存储不可用：静默（下次读取回退默认档）
  }
}
