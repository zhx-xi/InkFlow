/**
 * #1342 RED 契约：上下文注入面板勾选「接线到生成链路」。
 *
 * 现象：面板勾选/取消对**实际生成**无影响（只影响 assemble 预览）。
 * 后端通道已由 #1341 打通（PipelineExecuteRequest.override / _assemble_setting_context(override=)）。
 * 缺口在前端上游接线：勾选集不上传 → usePipeline body 无 override。
 *
 * 本文件只测「上游接线」四件事（不重复 ContextPanel 既有渲染契约）：
 *  1. 勾选变化 → 回调收到 override（受控外传）
 *  2. pipeline body 带 override（mock fetch 断言请求体）
 *  3. 不勾选 = 全注入：无 override → body 无 override 字段（后端语义 = 全量）
 *  4. 显式清空 = 空数组：全取消 → body override 三字段为空数组（语义 = 该类不注入）
 *  5. 可证伪自证：把 override 传参去掉 → 用例 2 必 FAIL
 *
 * 决策（D1=A，本轨拍板）：受控 props + 回调；既有 662 行契约零改动
 *  （新 props 全部可选，缺省时组件退化为内部 state = 既有行为）。
 * D3=A：只接 character/world（后端 _assemble_setting_context 未消费 foreshadowing_ids，
 *  伏笔维度另开后端轨）；但 override 负载**保真透传**三字段，
 *  待后端补伏笔源时前端无需再改。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ContextPanel } from './ContextPanel';
import type { ContextOverride } from '../api/context';

const ctxMocks = vi.hoisted(() => ({
  assembleContext: vi.fn(),
  listProjectWorldSettings: vi.fn(),
  listProjectForeshadowings: vi.fn(),
}));
vi.mock('../api/context', () => ctxMocks);
vi.mock('../api/character', () => ({ listProjectCharacters: vi.fn() }));

const assembleMock = ctxMocks.assembleContext;

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

function result(blocks: Block[]) {
  return { blocks, budget_tokens: 8000, total_tokens: 100, model: 'm', dropped: [] };
}

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  model: 'deepseek/deepseek-v4-flash',
  writingRequirements: '小说创作',
};

beforeEach(() => {
  assembleMock.mockReset();
  ctxMocks.listProjectWorldSettings.mockReset();
  ctxMocks.listProjectForeshadowings.mockReset();
});

// ─────────────────────────────────────────────────────────────────────
// 1 · 勾选状态外传（受控回调）
// ─────────────────────────────────────────────────────────────────────
describe('#1342 — 1 面板勾选状态外传到父层', () => {
  it('取消勾选一个角色 → onOverrideChange 收到该角色被移除的白名单', async () => {
    assembleMock.mockResolvedValue(
      result([
        block('character_setting', { character_id: 'c-a' }, '角色甲'),
        block('character_setting', { character_id: 'c-b' }, '角色乙'),
      ]),
    );
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => expect(assembleMock).toHaveBeenCalled());
    // 初始全注入 → 回调应已被调用一次（两角色都在）
    await waitFor(() => expect(onOverrideChange).toHaveBeenCalled());
    const initial = onOverrideChange.mock.calls.at(-1)?.[0] as ContextOverride;
    expect(initial.character_ids).toEqual(['c-a', 'c-b']);

    // 取消「角色甲」
    onOverrideChange.mockClear();
    const toggles = screen.getAllByTestId(/^context-item-toggle-/);
    fireEvent.click(toggles[0]);

    await waitFor(() => expect(onOverrideChange).toHaveBeenCalled());
    const next = onOverrideChange.mock.calls.at(-1)?.[0] as ContextOverride;
    expect(next.character_ids).toEqual(['c-b']);
  });

  it('取消勾选一个世界观 → onOverrideChange 的 world_ids 反映移除', async () => {
    assembleMock.mockResolvedValue(
      result([
        block('world_setting', { world_setting_id: 'w-a' }, '世界观甲'),
        block('world_setting', { world_setting_id: 'w-b' }, '世界观乙'),
      ]),
    );
    const onOverrideChange = vi.fn();
    render(<ContextPanel {...OPTS} onOverrideChange={onOverrideChange} />);

    await waitFor(() => expect(onOverrideChange).toHaveBeenCalled());
    onOverrideChange.mockClear();
    fireEvent.click(screen.getAllByTestId(/^context-item-toggle-/)[0]);

    await waitFor(() => expect(onOverrideChange).toHaveBeenCalled());
    const next = onOverrideChange.mock.calls.at(-1)?.[0] as ContextOverride;
    expect(next.world_ids).toEqual(['w-b']);
  });

  it('不传 onOverrideChange → 组件退化为内部 state，不抛错（既有行为兼容）', async () => {
    assembleMock.mockResolvedValue(result([block('character_setting', { character_id: 'c-a' })]));
    render(<ContextPanel {...OPTS} />);
    await waitFor(() => expect(assembleMock).toHaveBeenCalled());
    // 能点，不崩
    fireEvent.click(screen.getAllByTestId(/^context-item-toggle-/)[0]);
    await waitFor(() => expect(assembleMock).toHaveBeenCalledTimes(2));
  });
});

// ─────────────────────────────────────────────────────────────────────
// 2-4 · usePipeline 构造 body 带 override（生成链路真源）
// ─────────────────────────────────────────────────────────────────────
describe('#1342 — 2 生成请求体携带 override', () => {
  it('传 override → PipelineExecuteRequest body 含 override 三字段', async () => {
    const { usePipeline } = await import('../hooks/usePipeline');
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify({ execution_id: 'e1', status: 'completed', final_output: 'x' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const override: ContextOverride = {
      character_ids: ['c-a'],
      foreshadowing_ids: [],
      world_ids: ['w-a'],
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let api: any = null;
    function Harness() {
      api = usePipeline({
        projectId: 'p1',
        chapterId: 'c1',
        tags: [],
        targetWords: 0,
        writingStyle: '',
        chapterTitle: '',
        supervisor: null,
        override,
      });
      return null;
    }
    render(<Harness />);
    api.start('write_auto');

    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    const body = bodies[0] as Record<string, unknown>;
    expect(body.override).toEqual({
      character_ids: ['c-a'],
      foreshadowing_ids: [],
      world_ids: ['w-a'],
    });
  });

  it('不传 override → body 不含 override 字段（后端语义 = 全注入）', async () => {
    const { usePipeline } = await import('../hooks/usePipeline');
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify({ execution_id: 'e1', status: 'completed', final_output: 'x' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let api: any = null;
    function Harness() {
      api = usePipeline({
        projectId: 'p1',
        chapterId: 'c1',
        tags: [],
        targetWords: 0,
        writingStyle: '',
        chapterTitle: '',
        supervisor: null,
      });
      return null;
    }
    render(<Harness />);
    api.start('write_auto');

    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect('override' in (bodies[0] as Record<string, unknown>)).toBe(false);
  });

  it('override 显式空数组 → body 保留空数组（语义 = 该类不注入，非「全注入」）', async () => {
    const { usePipeline } = await import('../hooks/usePipeline');
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify({ execution_id: 'e1', status: 'completed', final_output: 'x' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const override: ContextOverride = { character_ids: [], foreshadowing_ids: [], world_ids: [] };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let api: any = null;
    function Harness() {
      api = usePipeline({
        projectId: 'p1',
        chapterId: 'c1',
        tags: [],
        targetWords: 0,
        writingStyle: '',
        chapterTitle: '',
        supervisor: null,
        override,
      });
      return null;
    }
    render(<Harness />);
    api.start('write_auto');

    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect((bodies[0] as Record<string, unknown>).override).toEqual({
      character_ids: [],
      foreshadowing_ids: [],
      world_ids: [],
    });
  });
});

// ─────────────────────────────────────────────────────────────────────
// 5 · 可证伪自证（falsifiability）
// ─────────────────────────────────────────────────────────────────────
describe('#1342 — 5 可证伪自证', () => {
  it('契约 2 的判据是「body.override 存在且等值」——实现里删掉 override 传参必须 FAIL', async () => {
    // 该断言即契约 2 的判据；若 usePipeline.start 不传 override，
    // body.override === undefined → toEqual 必失败。此用例显式固化这一事实。
    const { usePipeline } = await import('../hooks/usePipeline');
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      bodies.push(JSON.parse(String((init as RequestInit).body)));
      return new Response(JSON.stringify({ execution_id: 'e1', status: 'completed', final_output: 'x' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const override: ContextOverride = { character_ids: ['must-appear'], foreshadowing_ids: [], world_ids: [] };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let api: any = null;
    function Harness() {
      api = usePipeline({
        projectId: 'p1',
        chapterId: 'c1',
        tags: [],
        targetWords: 0,
        writingStyle: '',
        chapterTitle: '',
        supervisor: null,
        override,
      });
      return null;
    }
    render(<Harness />);
    api.start('write_auto');

    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    const body = bodies[0] as { override?: ContextOverride };
    // 反面对照：若实现未接线 → body.override === undefined → 下面两条必失败
    expect(body.override).toBeDefined();
    expect(body.override?.character_ids).toContain('must-appear');
  });
});
