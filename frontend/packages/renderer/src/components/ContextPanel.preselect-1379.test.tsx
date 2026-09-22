/**
 * #1379 RED 契约：上下文注入面板「Agent 按大纲预选」+ 「一键清除 / 全选」。
 *
 * 现象（v0.15.0-rc5 GUI 目视）：进入空章时面板默认勾选**全部**候选条目；
 * 用户期望默认勾选 = 与本章相关的子集（由 Agent 按大纲预选），且需要
 * 「一键清除」（清空三类勾选 → 外传空列表 → 该类不注入）与「全选」恢复。
 *
 * 本文件只测新增三件事（不重复既有 662 行渲染契约与 #1342/#1349 的面）：
 *  1. 默认预选：预选端点返回子集 → 初始勾选 = 该子集（**非全量**）
 *  2. 回退：预选失败（reject）/ 不可用 → 回退全选（既有行为不变）
 *  3. 一键清除：点击 → 三类勾选为空 → onOverrideChange 收到三类空列表
 *     （外传空列表 = 复用 #1235 已验证的「该类不注入」语义）
 *  4. 全选：清除后点击 → 恢复全量候选
 *  5. 反向断言：清除后**不等于**全量
 *  6. 可证伪自证：实现去掉清除的「回传空 override + 重新组装」→ 用例 3 必 FAIL
 *
 * 决策：既有 `ContextPanel.test.tsx`（662 行）与 `wiring-1342` / `injections-1349`
 * 契约**零改动** —— 其模块 mock 不含 `preselectContext`，实现必须对「预选不可用」
 * 静默降级（等价于回退全选），故这些文件的 mock 形态天然兼容（同 #1342 先例）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ContextPanel } from './ContextPanel';
import type { ContextOverride } from '../api/context';

const ctxMocks = vi.hoisted(() => ({
  assembleContext: vi.fn(),
  preselectContext: vi.fn(),
  listProjectWorldSettings: vi.fn(),
  listProjectForeshadowings: vi.fn(),
}));
vi.mock('../api/context', () => ctxMocks);
vi.mock('../api/character', () => ({ listProjectCharacters: vi.fn() }));

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

const ALL_BLOCKS: Block[] = [
  block('character_setting', { character_id: 'c-a' }, '角色甲'),
  block('character_setting', { character_id: 'c-b' }, '角色乙'),
  block('world_setting', { world_setting_id: 'w-a' }, '世界观甲'),
];

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

function lastOverride(mock: ReturnType<typeof vi.fn>): ContextOverride {
  return mock.mock.calls.at(-1)?.[0] as ContextOverride;
}

beforeEach(() => {
  assembleMock.mockReset();
  preselectMock.mockReset();
  ctxMocks.listProjectWorldSettings.mockReset();
  ctxMocks.listProjectForeshadowings.mockReset();
  assembleMock.mockImplementation(fakeAssemble);
});

// ─────────────────────────────────────────────────────────────────────
// 1 · 默认按大纲预选（子集，非全量）
// ─────────────────────────────────────────────────────────────────────
describe('#1379 — 1 默认预选子集', () => {
  it('预选端点返回子集 → 初始勾选/外传 = 子集（非全量），且二次组装带子集 override', async () => {
    preselectMock.mockResolvedValue({
      character_ids: ['c-a'],
      world_ids: [],
      foreshadowing_ids: [],
      mode: 'agent',
    });
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => {
      const ov = lastOverride(onOverrideChange);
      expect(ov.character_ids).toEqual(['c-a']);
    });
    const ov = lastOverride(onOverrideChange);
    // 反向：全量候选里的 c-b / w-a 未被选中
    expect(ov.character_ids).not.toContain('c-b');
    expect(ov.world_ids).toEqual([]);
    // 预选已应用标记可见
    expect(screen.getByTestId('context-preselect-applied')).toBeTruthy();
    // 面板只渲染子集条目（blocks 随 override 收窄）
    expect(screen.getAllByTestId(/^context-item-toggle-/)).toHaveLength(1);
    // 二次组装确实带子集 override（生成链路真源）
    const lastBody = assembleMock.mock.calls.at(-1)?.[0] as { override?: ContextOverride };
    expect(lastBody.override?.character_ids).toEqual(['c-a']);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 2 · 回退全选
// ─────────────────────────────────────────────────────────────────────
describe('#1379 — 2 预选失败回退全选', () => {
  it('预选 reject → 保持全选（既有行为），并显示回退提示', async () => {
    preselectMock.mockRejectedValue(new Error('preselect down'));
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => {
      const ov = lastOverride(onOverrideChange);
      expect(ov.character_ids).toEqual(['c-a', 'c-b']);
    });
    expect(lastOverride(onOverrideChange).world_ids).toEqual(['w-a']);
    expect(screen.getByTestId('context-preselect-fallback')).toBeTruthy();
  });

  it('预选返回 mode="fallback" → 采用三类全量（不回退到空）', async () => {
    preselectMock.mockResolvedValue({
      character_ids: ['c-a', 'c-b'],
      world_ids: ['w-a'],
      foreshadowing_ids: [],
      mode: 'fallback',
    });
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => {
      expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    });
    expect(lastOverride(onOverrideChange).world_ids).toEqual(['w-a']);
  });

  it('预选函数不可用（既有契约 mock 形态）→ 静默降级为全选，不抛错', async () => {
    // 模拟「模块 mock 未提供 preselectContext」：调用即 TypeError
    preselectMock.mockImplementation(() => {
      throw new TypeError('preselectContext is not a function');
    });
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => {
      expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────
// 3-5 · 一键清除 / 全选
// ─────────────────────────────────────────────────────────────────────
describe('#1379 — 3 一键清除与全选', () => {
  beforeEach(() => {
    // 预选不生效（走全选），聚焦清除/全选本身
    preselectMock.mockResolvedValue({
      character_ids: ['c-a', 'c-b'],
      world_ids: ['w-a'],
      foreshadowing_ids: [],
      mode: 'fallback',
    });
  });

  it('点击一键清除 → 三类勾选为空且外传三类空列表（该类不注入）', async () => {
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);
    await waitFor(() => {
      expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    });

    onOverrideChange.mockClear();
    fireEvent.click(screen.getByTestId('context-clear-all'));

    await waitFor(() => expect(onOverrideChange).toHaveBeenCalled());
    const cleared = lastOverride(onOverrideChange);
    expect(cleared.character_ids).toEqual([]);
    expect(cleared.world_ids).toEqual([]);
    expect(cleared.foreshadowing_ids).toEqual([]);
    // 重组装请求体显式带三类空数组（不是 undefined = 全注入）
    const lastBody = assembleMock.mock.calls.at(-1)?.[0] as { override?: ContextOverride };
    expect(lastBody.override).toEqual({
      character_ids: [],
      foreshadowing_ids: [],
      world_ids: [],
    });
    // 反向断言：清除后不等于全量
    expect(cleared.character_ids).not.toEqual(['c-a', 'c-b']);
  });

  it('清除后点击全选 → 恢复全量候选', async () => {
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);
    await waitFor(() => {
      expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    });

    fireEvent.click(screen.getByTestId('context-clear-all'));
    await waitFor(() => expect(lastOverride(onOverrideChange).character_ids).toEqual([]));

    fireEvent.click(screen.getByTestId('context-select-all'));
    await waitFor(() => {
      const restored = lastOverride(onOverrideChange);
      expect(restored.character_ids).toEqual(['c-a', 'c-b']);
    });
    expect(lastOverride(onOverrideChange).world_ids).toEqual(['w-a']);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 6 · 可证伪自证
// ─────────────────────────────────────────────────────────────────────
describe('#1379 — 6 可证伪自证', () => {
  it('清除必须触发「带三类空 override 的重新组装」——移除任一半即 FAIL', async () => {
    preselectMock.mockResolvedValue({
      character_ids: ['c-a', 'c-b'],
      world_ids: ['w-a'],
      foreshadowing_ids: [],
      mode: 'fallback',
    });
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);
    await waitFor(() => {
      expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    });

    const callsBefore = assembleMock.mock.calls.length;
    fireEvent.click(screen.getByTestId('context-clear-all'));
    // 反面对照：若清除不重新组装 → 调用次数不增 → 本条必 FAIL
    await waitFor(() => expect(assembleMock.mock.calls.length).toBeGreaterThan(callsBefore));

    const lastBody = assembleMock.mock.calls.at(-1)?.[0] as { override?: ContextOverride };
    // 反面对照：若实现漏传 override（undefined = 全注入）→ 下面三条必 FAIL
    expect(lastBody.override?.character_ids).toEqual([]);
    expect(lastBody.override?.foreshadowing_ids).toEqual([]);
    expect(lastBody.override?.world_ids).toEqual([]);
  });
});
