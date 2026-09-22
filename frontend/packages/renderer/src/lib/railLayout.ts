/**
 * #1378：写作页右栏布局记忆（两面板比例 + 右栏宽度）。
 *
 * - key = `inkflow.rail_layout.<projectId>`（跨项目隔离，镜像 #964 reasoningEffort 形态）。
 * - 存 JSON `{ split, width }`；`split` = context 面板占「两面板合计高度」的比例
 *   （默认 2:1 → 2/3）。**存比例而非 px**：窗口 resize 时语义自然等比缩放，
 *   不会出现负高 / 塌陷（#1378 需求 1）。
 * - 读侧不信任存储内容：越界 → 夹到合法区间；非数字 / 缺字段 / JSON 损坏 → 该项回退默认。
 * - read / write 均包 try/catch：存储不可用（隐私模式等）静默降级，不崩 UI。
 * - 空 projectId（尚无当前项目）→ 读回默认、写 no-op（不落盘）。
 */

/** 面板比例默认 2:1（context : summary）—— #1378 验收基准 */
export const DEFAULT_RAIL_SPLIT = 2 / 3;

/** 比例上下限：任一面板不得被压成 0（镜像既有面板高度的「留得住」语义） */
export const RAIL_SPLIT_MIN = 0.2;
export const RAIL_SPLIT_MAX = 0.8;

/** 右栏宽度：默认值 + 拖拽区间（#720 既有形态，区间不变） */
export const DEFAULT_RAIL_WIDTH = 240;
export const RAIL_WIDTH_MIN = 90;
export const RAIL_WIDTH_MAX = 540;

export const RAIL_LAYOUT_STORAGE_PREFIX = 'inkflow.rail_layout.';

export interface RailLayout {
  /** context 面板占两面板合计高度的比例（RAIL_SPLIT_MIN ~ RAIL_SPLIT_MAX） */
  split: number;
  /** 右栏展开态宽度（px） */
  width: number;
}

export function railLayoutStorageKey(projectId: string): string {
  return `${RAIL_LAYOUT_STORAGE_PREFIX}${projectId}`;
}

/** 夹到合法比例区间；非有限数（NaN / ±Infinity——拖拽基准不可测时的产物）→ 默认 2:1 */
export function clampRailSplit(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_RAIL_SPLIT;
  return Math.min(RAIL_SPLIT_MAX, Math.max(RAIL_SPLIT_MIN, value));
}

/** 夹到 #720 既有拖拽区间；非有限数 → 默认宽度 */
export function clampRailWidth(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_RAIL_WIDTH;
  return Math.min(RAIL_WIDTH_MAX, Math.max(RAIL_WIDTH_MIN, value));
}

/** 取存储里的原始对象；不可用 / 损坏 / 非普通对象 → {}（调用方按项回退默认）。 */
function readStoredObject(projectId: string): Record<string, unknown> {
  if (projectId === '') return {};
  try {
    const raw = localStorage.getItem(railLayoutStorageKey(projectId));
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    // 存储不可用 / JSON 损坏：静默回退默认
    return {};
  }
}

/** 读取 projectId 的右栏布局记忆；缺失 / 非法 / 损坏 → 回退默认（不抛错）。 */
export function readRailLayout(projectId: string): RailLayout {
  const stored = readStoredObject(projectId);
  return {
    split: typeof stored.split === 'number' ? clampRailSplit(stored.split) : DEFAULT_RAIL_SPLIT,
    width: typeof stored.width === 'number' ? clampRailWidth(stored.width) : DEFAULT_RAIL_WIDTH,
  };
}

/** 写入 projectId 的右栏布局记忆（部分写：只覆盖传入字段，其余沿用既有 / 默认）。 */
export function writeRailLayout(projectId: string, patch: Partial<RailLayout>): void {
  if (projectId === '') return; // 无当前项目 → 不落盘（下次有项目时按默认起）
  try {
    const next: RailLayout = { ...readRailLayout(projectId), ...patch };
    localStorage.setItem(railLayoutStorageKey(projectId), JSON.stringify(next));
  } catch {
    // 存储不可用：静默（下次读取回退默认）
  }
}
