/**
 * #1464 RED 契约：上下文注入「一键清除」按章持久化（切章再回 / 刷新**不复活**）。
 *
 * 现象：对「角色 / 伏笔 / 世界观」分类点「一键清除」后，切走再回同一章（或 F5 刷新）
 *   → 被清除条目**全部复活**。#1405 交付的清除只**本屏有效**，不**按章生效**。
 * 根因：override 只存 `writing.tsx` 组件 state（`ContextPanel.tsx:32` 亦注明「缺省 = 组件内部 state」）
 *   → 组件重挂载即归 null → assemble 回缺省全注入。
 *
 * 本文件锁定（方案 1：localStorage 按 `chapter:{id}` 存 override）：
 *  1. 清除某分类 → **同章重挂载**（模拟切走再回 / 刷新）→ 仍保持清除，**不复活**
 *  2. **按章隔离**：cA 的清除不影响 cB（不同 `chapter:{id}` 键）
 *  3. 挂载即**从持久层恢复**：预置 override → 面板按其组装（不复活）
 *  4. **反例守护**：从未清除过的章 → 行为与改动前一致（缺省全注入 + 不落盘）
 *  5. 边界：无 chapterId（章节未选 / 已删）→ **不写脏键**
 *  6. #1379 非劣化：重挂载后「全选」仍可用；回到全选 → 抹掉记录（恢复缺省全注入）
 *  7. 可证伪自证：同章同条件，唯一变量 = 有无 localStorage 记录 → 无读回即 FAIL
 *
 * 不重复既有 ContextPanel.test.tsx（渲染面）/ category-clear-1405（清除语义）/
 * wiring-1342（外传接线）/ preselect-1379 / injections-1349 的面。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ContextOverride } from '../api/context';
import {
  CONTEXT_OVERRIDE_STORAGE_PREFIX,
  contextOverrideStorageKey,
  readContextOverride,
  writeContextOverride,
} from '../lib/contextOverride';
import { ContextPanel } from './ContextPanel';

const ctxMocks = vi.hoisted(() => ({
  assembleContext: vi.fn(),
  preselectContext: vi.fn(),
  fetchChapterInjections: vi.fn(),
  listProjectWorldSettings: vi.fn(),
  listProjectForeshadowings: vi.fn(),
}));
vi.mock('../api/context', () => ctxMocks);
const charMocks = vi.hoisted(() => ({ listProjectCharacters: vi.fn() }));
vi.mock('../api/character', () => charMocks);

const assembleMock = ctxMocks.assembleContext;
const preselectMock = ctxMocks.preselectContext;

interface Block {
  item: {
    source: string;
    title: string;
    content: string;
    priority: number;
    metadata: Record<string, unknown>;
  };
  layer: string;
  token_count: number;
  compressed: boolean;
}

function block(source: string, metadata: Record<string, unknown>, title = 'T'): Block {
  return {
    item: { source, title, content: `内容-${title}`, priority: 50, metadata },
    layer: 'working',
    token_count: 10,
    compressed: false,
  };
}

/** 三类各 ≥1 条候选（章无关的候选池；清除必须在三个方向都成立）。 */
const ALL_BLOCKS: Block[] = [
  block('character_setting', { character_id: 'c-a' }, '角色甲'),
  block('character_setting', { character_id: 'c-b' }, '角色乙'),
  block('world_setting', { world_setting_id: 'w-a' }, '世界观甲'),
  block('foreshadowing', { foreshadowing_id: 'f-a' }, '伏笔甲'),
];

const FULL: ContextOverride = {
  character_ids: ['c-a', 'c-b'],
  world_ids: ['w-a'],
  foreshadowing_ids: ['f-a'],
};

const CLEARED_CHAR: ContextOverride = {
  character_ids: [],
  world_ids: ['w-a'],
  foreshadowing_ids: ['f-a'],
};

/** 尊重 override 的假 assemble：白名单命中才进 blocks（与后端 #1235 语义同构）。 */
function fakeAssemble(body: { override?: ContextOverride }) {
  const blocks = ALL_BLOCKS.filter((b) => {
    if (!body.override) return true;
    const meta = b.item.metadata;
    const id = String(meta.character_id ?? meta.world_setting_id ?? meta.foreshadowing_id ?? '');
    if (b.item.source === 'character_setting') return body.override.character_ids.includes(id);
    if (b.item.source === 'world_setting') return body.override.world_ids.includes(id);
    if (b.item.source === 'foreshadowing') return body.override.foreshadowing_ids.includes(id);
    return true;
  });
  return { blocks, budget_tokens: 8000, total_tokens: 100, model: 'm', dropped: [] };
}

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  model: 'deepseek/deepseek-v4-flash',
  writingRequirements: '小说创作',
};

/** 渲染面板（不等待任何组装结果 —— 各用例显式 waitFor 自己的目标态）。 */
function renderPanel(chapterId: string | null = 'c1') {
  const onOverrideChange = vi.fn();
  const utils = render(
    <ContextPanel {...OPTS} chapterId={chapterId} onOverrideChange={onOverrideChange} />,
  );
  return { onOverrideChange, ...utils };
}

function lastOverride(mock: ReturnType<typeof vi.fn>): ContextOverride {
  return mock.mock.calls.at(-1)?.[0] as ContextOverride;
}

function lastBody(): { override?: ContextOverride } {
  return assembleMock.mock.calls.at(-1)?.[0] as { override?: ContextOverride };
}

/** 现存的上下文覆盖持久键（判「不写脏键」用，避免受 i18n/主题等并存键干扰）。 */
function overrideKeys(): string[] {
  const keys: string[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key !== null && key.startsWith(CONTEXT_OVERRIDE_STORAGE_PREFIX)) keys.push(key);
  }
  return keys;
}

beforeEach(() => {
  localStorage.clear();
  assembleMock.mockReset();
  preselectMock.mockReset();
  ctxMocks.fetchChapterInjections.mockReset();
  ctxMocks.listProjectWorldSettings.mockReset();
  ctxMocks.listProjectForeshadowings.mockReset();
  charMocks.listProjectCharacters.mockReset();
  assembleMock.mockImplementation(fakeAssemble);
  // 预选不生效（回退全选）→ 聚焦「持久化」本身，不引入子集覆盖
  preselectMock.mockResolvedValue({ ...FULL, mode: 'fallback' });
  ctxMocks.fetchChapterInjections.mockResolvedValue(null);
});

// ─────────────────────────────────────────────────────────────────────
// 1 · 清除 → 同章重挂载（切走再回 / 刷新）→ 保持清除
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 1 清除后重挂载不复活', () => {
  it('清除角色类 → 同章重挂载 → 角色类仍为空 + 面板勾选面收窄 + 组装带持久化 override', async () => {
    const first = renderPanel('cA');
    await waitFor(() => expect(lastOverride(first.onOverrideChange).character_ids).toEqual(FULL.character_ids));

    fireEvent.click(screen.getByTestId('context-clear-character_setting'));
    await waitFor(() => expect(lastOverride(first.onOverrideChange).character_ids).toEqual([]));
    // 落盘 = 该章收窄集合（显式空 = 该类不注入）
    expect(readContextOverride('cA')).toEqual(CLEARED_CHAR);

    first.unmount(); // 模拟切走别处 / F5 刷新 → 组件重挂载

    const second = renderPanel('cA');
    await waitFor(() => expect(lastOverride(second.onOverrideChange).character_ids).toEqual([]));
    expect(lastOverride(second.onOverrideChange).world_ids).toEqual(FULL.world_ids);
    expect(lastOverride(second.onOverrideChange).foreshadowing_ids).toEqual(FULL.foreshadowing_ids);
    // 重组装请求体带持久化 override（不是缺省全注入 undefined）
    expect(lastBody().override).toEqual(CLEARED_CHAR);
    // 面板勾选面：被清除的角色条目不再渲染，其余两类照常
    expect(screen.queryByTestId('context-item-character_setting-0')).toBeNull();
    expect(screen.getByTestId('context-item-world_setting-0')).toBeTruthy();
  });

  it('三类各自清除后重挂载都保持（角色 / 世界观 / 伏笔 三个方向）', async () => {
    const cases: Array<{ source: string; key: keyof ContextOverride }> = [
      { source: 'character_setting', key: 'character_ids' },
      { source: 'world_setting', key: 'world_ids' },
      { source: 'foreshadowing', key: 'foreshadowing_ids' },
    ];
    for (const { source, key } of cases) {
      const chapterId = `c-${source}`;
      const first = renderPanel(chapterId);
      await waitFor(() => expect(lastOverride(first.onOverrideChange).character_ids).toEqual(FULL.character_ids));
      fireEvent.click(screen.getByTestId(`context-clear-${source}`));
      await waitFor(() => expect(lastOverride(first.onOverrideChange)[key]).toEqual([]));
      first.unmount();

      const second = renderPanel(chapterId);
      await waitFor(() => expect(lastOverride(second.onOverrideChange)[key]).toEqual([]));
      expect(lastBody().override?.[key]).toEqual([]);
      second.unmount();
    }
  });
});

// ─────────────────────────────────────────────────────────────────────
// 2 · 按章隔离
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 2 按章隔离', () => {
  it('cA 的清除不影响 cB（不同 chapter:{id} 键；cB 仍缺省全注入）', async () => {
    const a = renderPanel('cA');
    await waitFor(() => expect(lastOverride(a.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    fireEvent.click(screen.getByTestId('context-clear-world_setting'));
    await waitFor(() => expect(lastOverride(a.onOverrideChange).world_ids).toEqual([]));
    expect(readContextOverride('cA')).not.toBeNull();
    a.unmount();

    assembleMock.mockClear();
    const b = renderPanel('cB');
    await waitFor(() => expect(lastOverride(b.onOverrideChange).world_ids).toEqual(FULL.world_ids));
    await waitFor(() => expect(lastOverride(b.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    // cB 首轮组装 = 缺省全注入（无 override），且无 cB 持久化键
    expect(assembleMock.mock.calls[0]?.[0]?.override).toBeUndefined();
    expect(readContextOverride('cB')).toBeNull();
    // cA 的记录仍在（互不干扰）
    expect(readContextOverride('cA')).not.toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 3 · 挂载即从持久层恢复
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 3 挂载即从持久层恢复', () => {
  it('预置某章 override → 面板按其组装（不复活）', async () => {
    writeContextOverride('c1', CLEARED_CHAR);
    const p = renderPanel('c1');
    await waitFor(() => expect(lastOverride(p.onOverrideChange).character_ids).toEqual([]));
    expect(lastBody().override).toEqual(CLEARED_CHAR);
    expect(screen.queryByTestId('context-item-character_setting-0')).toBeNull();
    expect(screen.getByTestId('context-item-world_setting-0')).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 4 · 反例守护：未清除过的章行为不变
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 4 反例守护：未清除过的章', () => {
  it('从未清除过的章 → 缺省全注入（首轮无 override）+ 不落任何持久化键', async () => {
    const p = renderPanel('fresh');
    await waitFor(() => expect(lastOverride(p.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    expect(lastOverride(p.onOverrideChange)).toEqual(FULL);
    expect(assembleMock.mock.calls[0]?.[0]?.override).toBeUndefined();
    expect(readContextOverride('fresh')).toBeNull();
    expect(overrideKeys()).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 5 · 边界：无 chapterId 不写脏键
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 5 边界：无 chapterId（章节未选 / 已删）', () => {
  it('chapterId=null → 不组装、不落任何上下文覆盖键', async () => {
    renderPanel(null);
    await waitFor(() => expect(screen.getByTestId('context-panel')).toBeTruthy());
    expect(assembleMock).not.toHaveBeenCalled();
    expect(overrideKeys()).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 6 · #1379 非劣化 + 归一化
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 6 #1379 非劣化与归一化', () => {
  it('重挂载后「全选」仍可用（恢复基准不因持久化缩水）', async () => {
    writeContextOverride('c1', CLEARED_CHAR);
    renderPanel('c1');
    await waitFor(() => expect(screen.queryByTestId('context-item-character_setting-0')).toBeNull());
    expect(screen.getByTestId('context-select-all')).toBeEnabled();
  });

  it('清除后点「全选」→ 抹掉该章持久化记录（恢复缺省全注入语义）', async () => {
    const p = renderPanel('c1');
    await waitFor(() => expect(lastOverride(p.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    fireEvent.click(screen.getByTestId('context-clear-character_setting'));
    await waitFor(() => expect(readContextOverride('c1')).toEqual(CLEARED_CHAR));

    fireEvent.click(screen.getByTestId('context-select-all'));
    await waitFor(() => expect(lastOverride(p.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    expect(readContextOverride('c1')).toBeNull();
    expect(localStorage.getItem(contextOverrideStorageKey('c1'))).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 7 · 可证伪自证
// ─────────────────────────────────────────────────────────────────────
describe('#1464 — 7 可证伪自证', () => {
  it('同章同条件，唯一变量 = 有无 localStorage 记录：无读回 ⇒ 两条断言必 FAIL', async () => {
    // 情形 A：无记录 → 缺省全注入
    const a = renderPanel('cX');
    await waitFor(() => expect(lastOverride(a.onOverrideChange).character_ids).toEqual(FULL.character_ids));
    a.unmount();

    // 情形 B：同一章、同一 mock、仅多一条持久化记录 → 必须收窄
    writeContextOverride('cX', CLEARED_CHAR);
    const b = renderPanel('cX');
    await waitFor(() => expect(lastOverride(b.onOverrideChange).character_ids).toEqual([]));
    // 反面对照：实现若不读持久层 → 这里会回到 FULL → 断言失败
    expect(lastOverride(b.onOverrideChange).character_ids).not.toEqual(FULL.character_ids);
    expect(lastBody().override).toEqual(CLEARED_CHAR);
  });
});
