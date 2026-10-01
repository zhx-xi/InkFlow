/**
 * #1405 RED 契约：上下文注入面板「分类一键清除」（角色 / 世界观 / 伏笔 各自一键清除）。
 *
 * 现象：面板只有**面板级全局**「清除」（三类全清，#1379）与「全选」；只想清掉某一类
 * （例如本章不要任何伏笔）必须逐条取消勾选 —— 分类粒度缺失。
 *
 * 语义口径（#1235 三态，勿偏）：`[]` = **该类显式不注入**；「全注入」只由**缺省 override**
 * 表达。→ 分类清除必须走 runAssemble 并传**该类空列表**，**不是**「不传该键」。
 *
 * 本文件锁定：
 *  1. 三类各自清除 → assemble override **仅该类为空列表**，另两类**保持当前勾选值**
 *  2. 边界：该类勾选数为 0 时按钮 `disabled`（另两类仍可用）
 *  3. 清除后不锁死：仍可经「＋ 选择注入」重新勾选该类 → 外传恢复非空
 *  4. 回归：#1379 全局清除/全选语义不劣化；#1017 写作要求栏不受影响
 *  5. 可证伪自证：实现漏掉「该类空列表 + 重组装」→ 本文件必 FAIL
 *
 * 不重复既有 ContextPanel.test.tsx（662 行渲染契约）与 preselect-1379（265 行）的面。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ContextPanel } from './ContextPanel';
import type { ContextOverride } from '../api/context';

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

/** 三类各 ≥1 条候选（伏笔也有条目 —— 分类清除必须在三个方向都成立）。 */
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

/** 初始全选（无 override 组装）→ 等三类勾选都到位，作为各用例的共同起点。 */
async function renderReady(props: Record<string, unknown> = {}) {
  const onOverrideChange = vi.fn();
  render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} {...props} />);
  await waitFor(() => {
    expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
  });
  expect(lastOverride(onOverrideChange).world_ids).toEqual(['w-a']);
  expect(lastOverride(onOverrideChange).foreshadowing_ids).toEqual(['f-a']);
  return onOverrideChange;
}

function lastOverride(mock: ReturnType<typeof vi.fn>): ContextOverride {
  return mock.mock.calls.at(-1)?.[0] as ContextOverride;
}

function lastBody(): { override?: ContextOverride } {
  return assembleMock.mock.calls.at(-1)?.[0] as { override?: ContextOverride };
}

beforeEach(() => {
  assembleMock.mockReset();
  preselectMock.mockReset();
  ctxMocks.fetchChapterInjections.mockReset();
  ctxMocks.listProjectWorldSettings.mockReset();
  ctxMocks.listProjectForeshadowings.mockReset();
  charMocks.listProjectCharacters.mockReset();
  assembleMock.mockImplementation(fakeAssemble);
  // 预选不生效（回退全选）→ 聚焦分类清除本身，不引入子集覆盖
  preselectMock.mockResolvedValue({
    character_ids: ['c-a', 'c-b'],
    world_ids: ['w-a'],
    foreshadowing_ids: ['f-a'],
    mode: 'fallback',
  });
  ctxMocks.fetchChapterInjections.mockResolvedValue(null);
});

// ─────────────────────────────────────────────────────────────────────
// 1 · 三类各自清除：仅该类为空，另两类保持当前值
// ─────────────────────────────────────────────────────────────────────
const CLEAR_CASES: Array<{
  source: string;
  cleared: keyof ContextOverride;
  kept: Array<[keyof ContextOverride, string[]]>;
}> = [
  {
    source: 'character_setting',
    cleared: 'character_ids',
    kept: [
      ['world_ids', FULL.world_ids],
      ['foreshadowing_ids', FULL.foreshadowing_ids],
    ],
  },
  {
    source: 'world_setting',
    cleared: 'world_ids',
    kept: [
      ['character_ids', FULL.character_ids],
      ['foreshadowing_ids', FULL.foreshadowing_ids],
    ],
  },
  {
    source: 'foreshadowing',
    cleared: 'foreshadowing_ids',
    kept: [
      ['character_ids', FULL.character_ids],
      ['world_ids', FULL.world_ids],
    ],
  },
];

describe('#1405 — 1 分类清除：只清该类', () => {
  it.each(CLEAR_CASES)(
    '点「$source 清除」→ override 仅 $cleared 为空列表，另两类保持当前勾选',
    async ({ source, cleared, kept }) => {
      const onOverrideChange = await renderReady();

      const callsBefore = assembleMock.mock.calls.length;
      fireEvent.click(screen.getByTestId(`context-clear-${source}`));

      await waitFor(() => expect(lastOverride(onOverrideChange)[cleared]).toEqual([]));
      // 确实发起了重新组装（不是只改本地 state）
      expect(assembleMock.mock.calls.length).toBeGreaterThan(callsBefore);

      // 重组装请求体：三类字段**显式**存在（#1235 —— [] 表示不注入，绝非 undefined 全注入）
      const body = lastBody();
      expect(body.override).toEqual({
        character_ids: cleared === 'character_ids' ? [] : FULL.character_ids,
        world_ids: cleared === 'world_ids' ? [] : FULL.world_ids,
        foreshadowing_ids: cleared === 'foreshadowing_ids' ? [] : FULL.foreshadowing_ids,
      });
      for (const [field, expected] of kept) {
        expect(lastOverride(onOverrideChange)[field]).toEqual(expected);
      }
    },
  );

  it('分类清除只移除本类：另两类勾选框仍为 checked（勾选面同步）', async () => {
    await renderReady();
    fireEvent.click(screen.getByTestId('context-clear-world_setting'));
    await waitFor(() => expect(screen.queryByTestId('context-item-world_setting-0')).toBeNull());

    const charBoxes = screen.getAllByTestId(/^context-item-toggle-/);
    const checked = charBoxes.filter((box) => (box as HTMLInputElement).checked);
    // 角色 2 条 + 伏笔 1 条仍在且勾选（世界观条目已随重组装收窄而消失）
    expect(checked.length).toBe(3);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 2 · 边界：空类按钮禁用
// ─────────────────────────────────────────────────────────────────────
describe('#1405 — 2 边界：空类禁用', () => {
  it('该类清空后其按钮 disabled（幂等，不再发请求）；另两类按钮仍可用', async () => {
    await renderReady();

    expect(screen.getByTestId('context-clear-character_setting')).toBeEnabled();
    fireEvent.click(screen.getByTestId('context-clear-character_setting'));
    await waitFor(() =>
      expect(screen.getByTestId('context-clear-character_setting')).toBeDisabled(),
    );

    expect(screen.getByTestId('context-clear-world_setting')).toBeEnabled();
    expect(screen.getByTestId('context-clear-foreshadowing')).toBeEnabled();

    const callsBefore = assembleMock.mock.calls.length;
    fireEvent.click(screen.getByTestId('context-clear-character_setting'));
    expect(assembleMock.mock.calls.length).toBe(callsBefore);
  });

  it('三类卡片头各渲染一个分类清除按钮（角色 / 世界观 / 伏笔）', async () => {
    await renderReady();
    for (const source of ['character_setting', 'world_setting', 'foreshadowing']) {
      expect(screen.getByTestId(`context-clear-${source}`)).toBeTruthy();
    }
  });

  it('assemble 失败（错误态）仍渲染三类清除按钮且禁用（#1017 常驻语义，勾选必为空）', async () => {
    assembleMock.mockRejectedValue(new Error('assemble down'));
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => expect(screen.getByTestId('context-error')).toBeTruthy());
    for (const source of ['character_setting', 'world_setting', 'foreshadowing']) {
      expect(screen.getByTestId(`context-clear-${source}`)).toBeDisabled();
    }
  });
});

// ─────────────────────────────────────────────────────────────────────
// 3 · 清除后不锁死：可经「＋ 选择注入」重新勾选该类
// ─────────────────────────────────────────────────────────────────────
describe('#1405 — 3 清除后可恢复注入', () => {
  it('清除角色类 → 经「＋ 选择注入」重选角色甲 → 外传恢复非空，另两类不受扰', async () => {
    charMocks.listProjectCharacters.mockResolvedValue({
      items: [
        { id: 'c-a', name: '角色甲' },
        { id: 'c-b', name: '角色乙' },
      ],
    });
    const onOverrideChange = await renderReady();

    fireEvent.click(screen.getByTestId('context-clear-character_setting'));
    await waitFor(() => expect(lastOverride(onOverrideChange).character_ids).toEqual([]));

    fireEvent.click(screen.getByTestId('context-pick-character_setting'));
    await waitFor(() => expect(screen.getByTestId('context-picker-opt-c-a')).toBeTruthy());
    const box = screen
      .getByTestId('context-picker-opt-c-a')
      .querySelector('input[type=checkbox]') as HTMLInputElement;
    fireEvent.click(box);
    fireEvent.click(screen.getByTestId('context-picker-confirm'));

    await waitFor(() => expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a']));
    expect(lastOverride(onOverrideChange).world_ids).toEqual(FULL.world_ids);
    expect(lastOverride(onOverrideChange).foreshadowing_ids).toEqual(FULL.foreshadowing_ids);
    // 按钮随勾选恢复可用
    expect(screen.getByTestId('context-clear-character_setting')).toBeEnabled();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 4 · 回归：#1379 全局清除/全选、#1017 写作要求栏
// ─────────────────────────────────────────────────────────────────────
describe('#1405 — 4 回归（#1379 / #1017）', () => {
  it('#1379 全局清除仍清三类（既有语义不劣化）', async () => {
    const onOverrideChange = await renderReady();
    onOverrideChange.mockClear();
    fireEvent.click(screen.getByTestId('context-clear-all'));
    await waitFor(() =>
      expect(lastBody().override).toEqual({
        character_ids: [],
        foreshadowing_ids: [],
        world_ids: [],
      }),
    );
    const cleared = lastOverride(onOverrideChange);
    expect(cleared.character_ids).toEqual([]);
    expect(cleared.world_ids).toEqual([]);
    expect(cleared.foreshadowing_ids).toEqual([]);
  });

  it('分类清除后点「全选」→ 三类恢复全量（与 #1379 全选协同）', async () => {
    const onOverrideChange = await renderReady();
    fireEvent.click(screen.getByTestId('context-clear-world_setting'));
    await waitFor(() => expect(lastOverride(onOverrideChange).world_ids).toEqual([]));

    fireEvent.click(screen.getByTestId('context-select-all'));
    await waitFor(() => expect(lastOverride(onOverrideChange).world_ids).toEqual(['w-a']));
    expect(lastOverride(onOverrideChange).character_ids).toEqual(['c-a', 'c-b']);
    expect(lastOverride(onOverrideChange).foreshadowing_ids).toEqual(['f-a']);
  });

  it('#1017 分类清除不触碰章级写作要求栏（无回调触发，栏位仍在）', async () => {
    const onWritingRequirementsChange = vi.fn();
    const onOverrideChange = await renderReady({ onWritingRequirementsChange });

    fireEvent.click(screen.getByTestId('context-clear-foreshadowing'));
    await waitFor(() => expect(lastOverride(onOverrideChange).foreshadowing_ids).toEqual([]));

    expect(onWritingRequirementsChange).not.toHaveBeenCalled();
    expect(screen.getByTestId('context-writing-requirements')).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 5 · 可证伪自证
// ─────────────────────────────────────────────────────────────────────
describe('#1405 — 5 可证伪自证', () => {
  it('分类清除必须「按该类空列表重新组装」——漏传空列表（或漏重组装）即 FAIL', async () => {
    const onOverrideChange = await renderReady();
    const callsBefore = assembleMock.mock.calls.length;

    fireEvent.click(screen.getByTestId('context-clear-foreshadowing'));

    // 反面对照：若清除不重新组装 → 调用次数不增 → FAIL
    await waitFor(() => expect(assembleMock.mock.calls.length).toBeGreaterThan(callsBefore));
    const body = lastBody();
    // 反面对照：若漏传 override（undefined = 全注入）或误传三类空 → 下面三条 FAIL
    expect(body.override?.foreshadowing_ids).toEqual([]);
    expect(body.override?.character_ids).toEqual(['c-a', 'c-b']);
    expect(body.override?.world_ids).toEqual(['w-a']);
    expect(lastOverride(onOverrideChange).foreshadowing_ids).toEqual([]);
  });
});
