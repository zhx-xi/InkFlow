/**
 * #1464：写作页上下文注入「一键清除」按章持久化 —— 持久层纯模块。
 *
 * 现象：对某章清除「角色 / 伏笔 / 世界观」分类后，切走再回（或 F5 刷新）
 *   → 被清除的条目全部复活，重新参与注入。
 * 修复（方案 1·轻量）：localStorage 按 `chapter:{id}` 存 override —— 零后端改动、零 DDL。
 *
 * 存储契约：key = `inkflow.context_override.<chapterId>`（按章隔离，镜像 #1378 rail_layout）。
 * - 无记录 / JSON 损坏 / 形态非法 / 存储不可用 → null
 *   （null = 缺省全注入 = 未清除过的章行为与改动前完全一致）
 * - 空 chapterId（章节未选 / 已删）→ 读回 null、写 no-op（不落脏键）
 * - 集合等价比较（contextOverrideEquals）：顺序无关、三类全比。
 */
import type { ContextOverride } from '../api/context';

/** 存储键前缀；按章隔离（镜像 #1378 rail_layout / #964 reasoning_effort 形态） */
export const CONTEXT_OVERRIDE_STORAGE_PREFIX = 'inkflow.context_override.';

export function contextOverrideStorageKey(chapterId: string): string {
  return `${CONTEXT_OVERRIDE_STORAGE_PREFIX}${chapterId}`;
}

/** 三段 id 均为字符串数组才算合法形态（字段缺失 / 非数组 / 含非字符串 → 非法） */
function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string');
}

/**
 * 读取该章的持久化覆盖；缺省 / 非法 / 损坏 / 存储不可用一律 null（不抛错）。
 * 多余字段忽略，只要求三段 id 齐全合法。
 */
export function readContextOverride(chapterId: string): ContextOverride | null {
  if (chapterId === '') return null;
  try {
    const raw = localStorage.getItem(contextOverrideStorageKey(chapterId));
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    const characterIds = record.character_ids;
    const foreshadowingIds = record.foreshadowing_ids;
    const worldIds = record.world_ids;
    if (!isStringArray(characterIds) || !isStringArray(foreshadowingIds) || !isStringArray(worldIds)) {
      return null;
    }
    return {
      character_ids: characterIds,
      foreshadowing_ids: foreshadowingIds,
      world_ids: worldIds,
    };
  } catch {
    // 存储不可用（隐私模式等）/ JSON 损坏：静默回退缺省全注入
    return null;
  }
}

/** 写入该章覆盖（三段 id 全量落盘）；空 chapterId / 存储不可用均静默 no-op */
export function writeContextOverride(chapterId: string, override: ContextOverride): void {
  if (chapterId === '') return;
  try {
    const payload: ContextOverride = {
      character_ids: override.character_ids,
      foreshadowing_ids: override.foreshadowing_ids,
      world_ids: override.world_ids,
    };
    localStorage.setItem(contextOverrideStorageKey(chapterId), JSON.stringify(payload));
  } catch {
    // 存储不可用：静默（下次读取回退缺省全注入）
  }
}

/** 清除该章覆盖（回到「无记录」= 缺省全注入）；空 chapterId / 存储不可用均静默 */
export function clearContextOverride(chapterId: string): void {
  if (chapterId === '') return;
  try {
    localStorage.removeItem(contextOverrideStorageKey(chapterId));
  } catch {
    // 存储不可用：静默
  }
}

/** 单类 id 集合等价：顺序无关（按集合比较，重复项不影响） */
function sameIdSet(a: string[], b: string[]): boolean {
  const setA = new Set(a);
  const setB = new Set(b);
  if (setA.size !== setB.size) return false;
  for (const id of setA) {
    if (!setB.has(id)) return false;
  }
  return true;
}

/** 三类 id 全等的集合等价比较（供「回到全选 ⇒ 抹掉记录」的归一化判定） */
export function contextOverrideEquals(a: ContextOverride, b: ContextOverride): boolean {
  return (
    sameIdSet(a.character_ids, b.character_ids) &&
    sameIdSet(a.foreshadowing_ids, b.foreshadowing_ids) &&
    sameIdSet(a.world_ids, b.world_ids)
  );
}
