/**
 * #1464：写作页上下文注入「一键清除」按章持久化 —— 持久层纯模块契约。
 *
 * 现象（0.16.0-rc1 打包产物目视）：对某章清除「角色 / 伏笔 / 世界观」分类后，切走再回
 *   （或 F5 刷新）→ 被清除的条目**全部复活**，重新参与注入。
 * 根因：`writing.tsx` 的 `contextOverride` 只存组件 state（无 localStorage / 无 API 写 /
 *   无 store 持久层）→ 组件重挂载（切章 / 路由重进 / 刷新）即归 null → assemble 回缺省全注入。
 * 修复（方案 1·轻量）：localStorage 按 `chapter:{id}` 存 override —— 零后端改动、零 DDL。
 *
 * 本模块 = 纯读写 + 不信任存储内容：
 * - key 按章隔离（镜像 #1378 `rail_layout` / #964 `reasoning_effort` 形态）：
 *   `inkflow.context_override.<chapterId>`
 * - 无记录 / JSON 损坏 / 形态非法 / 存储不可用 → **null**
 *   （null = 缺省全注入 = 未清除过的章行为与改动前完全一致）
 * - 空 chapterId（章节未选 / 已删）→ 读回 null、写 no-op（**不落脏键**）
 * - 集合等价比较（`contextOverrideEquals`）：顺序无关、三类全比 ——
 *   供「回到全选 ⇒ 抹掉记录（恢复缺省全注入）」的归一化判定
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { ContextOverride } from '../api/context';
import {
  CONTEXT_OVERRIDE_STORAGE_PREFIX,
  clearContextOverride,
  contextOverrideEquals,
  contextOverrideStorageKey,
  readContextOverride,
  writeContextOverride,
} from './contextOverride';

const FULL: ContextOverride = {
  character_ids: ['c-a', 'c-b'],
  world_ids: ['w-a'],
  foreshadowing_ids: ['f-a'],
};

/** 清除「角色」后的收窄集合（显式空 = 该类不注入，#1235 语义） */
const NARROWED: ContextOverride = {
  character_ids: [],
  world_ids: ['w-a'],
  foreshadowing_ids: ['f-a'],
};

beforeEach(() => {
  localStorage.clear();
});

describe('#1464 contextOverride — 键与缺省', () => {
  it('存储键按章隔离：inkflow.context_override.<chapterId>', () => {
    expect(CONTEXT_OVERRIDE_STORAGE_PREFIX).toBe('inkflow.context_override.');
    expect(contextOverrideStorageKey('c1')).toBe('inkflow.context_override.c1');
  });

  it('无记录 → null（= 缺省全注入；未清除过的章行为不变）', () => {
    expect(readContextOverride('c1')).toBeNull();
  });
});

describe('#1464 contextOverride — 读写往返与按章隔离', () => {
  it('写入后读回同值', () => {
    writeContextOverride('c1', NARROWED);
    expect(readContextOverride('c1')).toEqual(NARROWED);
  });

  it('按章隔离：c1 的覆盖不影响 c2（不同键）', () => {
    writeContextOverride('c1', NARROWED);
    expect(readContextOverride('c1')).toEqual(NARROWED);
    expect(readContextOverride('c2')).toBeNull();
  });

  it('clearContextOverride 删除记录 → 读回 null（键亦被移除）', () => {
    writeContextOverride('c1', NARROWED);
    clearContextOverride('c1');
    expect(readContextOverride('c1')).toBeNull();
    expect(localStorage.getItem(contextOverrideStorageKey('c1'))).toBeNull();
  });
});

describe('#1464 contextOverride — 存储内容不可信', () => {
  it('JSON 损坏 → null，不抛错', () => {
    localStorage.setItem(contextOverrideStorageKey('c1'), '{not-json');
    expect(readContextOverride('c1')).toBeNull();
  });

  it('形态非法（非对象 / 缺字段 / 非数组 / 元素非字符串）→ null', () => {
    const key = contextOverrideStorageKey('c1');
    const bads = [
      'null',
      '[]',
      '"nope"',
      JSON.stringify({ character_ids: ['c-a'] }),
      JSON.stringify({ character_ids: 'c-a', world_ids: [], foreshadowing_ids: [] }),
      JSON.stringify({ character_ids: [1], world_ids: [], foreshadowing_ids: [] }),
    ];
    for (const bad of bads) {
      localStorage.setItem(key, bad);
      expect(readContextOverride('c1'), `bad payload: ${bad}`).toBeNull();
    }
  });

  it('存储不可用（隐私模式）→ 读 null / 写与清空静默，不抛给调用方', () => {
    const getSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    try {
      expect(readContextOverride('c1')).toBeNull();
    } finally {
      getSpy.mockRestore();
    }

    const setSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    try {
      expect(() => writeContextOverride('c1', NARROWED)).not.toThrow();
    } finally {
      setSpy.mockRestore();
    }

    const rmSpy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    try {
      expect(() => clearContextOverride('c1')).not.toThrow();
    } finally {
      rmSpy.mockRestore();
    }
  });
});

describe('#1464 contextOverride — 空 chapterId（章节未选 / 已删）不写脏键', () => {
  it('读空 id → null；写空 id → no-op（不落盘）', () => {
    expect(readContextOverride('')).toBeNull();
    writeContextOverride('', NARROWED);
    expect(localStorage.length).toBe(0);
  });
});

describe('#1464 contextOverride — 集合等价比较（归一化判定用）', () => {
  it('contextOverrideEquals 顺序无关，三类全比', () => {
    expect(
      contextOverrideEquals(FULL, {
        character_ids: ['c-b', 'c-a'],
        world_ids: ['w-a'],
        foreshadowing_ids: ['f-a'],
      }),
    ).toBe(true);
    expect(contextOverrideEquals(FULL, FULL)).toBe(true);
    expect(contextOverrideEquals(FULL, NARROWED)).toBe(false);
    expect(contextOverrideEquals(FULL, { ...FULL, world_ids: ['w-b'] })).toBe(false);
    expect(contextOverrideEquals(FULL, { ...FULL, foreshadowing_ids: ['f-a', 'f-b'] })).toBe(false);
  });
});
