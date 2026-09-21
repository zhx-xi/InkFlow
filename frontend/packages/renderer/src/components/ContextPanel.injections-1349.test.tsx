/**
 * #1349 RED 契约：章级注入记录回显（「本章已注入」回执面）。
 *
 * 缺口：面板只展示 **assemble 预览**（"如果现在生成，将注入什么"），
 * 无法回答"上一章生成时**实际**注入了哪些条目"（注入结果无持久化痕迹）。
 *
 * 后端本 PR 已落库（agent_executions.injected_context）+ 新增章级读端点
 * `GET /api/v1/agent/chapters/{chapter_id}/injections`。本文件锁**前端消费面**：
 *  1. 有记录 → 渲染「本章已注入」明细（execution_id + 三源计数 + chip）
 *  2. 无记录（injected_context=null）→ 回退态提示（不渲染空的明细块）
 *  3. 反向断言：有记录时明细块**不**展示预览态文案；两者可区分
 *  4. 请求失败静默降级为回退态（不阻塞预览主路径）
 *  5. 可证伪自证：去掉 API 调用 → 用例 1 必 FAIL
 *
 * 设计边界：回执面只读，**不参与**勾选控制面（勾选框仍只在预览区块）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ContextPanel } from './ContextPanel';

const ctxMocks = vi.hoisted(() => ({
  assembleContext: vi.fn(),
  listProjectWorldSettings: vi.fn(),
  listProjectForeshadowings: vi.fn(),
  fetchChapterInjections: vi.fn(),
}));
vi.mock('../api/context', () => ctxMocks);
vi.mock('../api/character', () => ({ listProjectCharacters: vi.fn() }));

const assembleMock = ctxMocks.assembleContext;
const injectionsMock = ctxMocks.fetchChapterInjections;

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

function injectionRecord(payload: {
  character_ids?: string[];
  world_ids?: string[];
  foreshadowing_ids?: string[];
} | null) {
  return {
    chapter_id: 'c1',
    execution_id: 'e-1',
    injected_context: payload,
  };
}

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  model: 'deepseek/deepseek-v4-flash',
  writingRequirements: '小说创作',
};

beforeEach(() => {
  assembleMock.mockReset();
  injectionsMock.mockReset();
  ctxMocks.listProjectWorldSettings.mockReset();
  ctxMocks.listProjectForeshadowings.mockReset();
  // 既有用例缺省无记录（回退态）
  injectionsMock.mockResolvedValue(injectionRecord(null));
});

// ─────────────────────────────────────────────────────────────────────
// 1 · 有记录 → 显示实际注入明细
// ─────────────────────────────────────────────────────────────────────
describe('#1349 — 1 有记录 → 显示本章实际注入', () => {
  it('落库明细非空 → 渲染 context-injected-echo 明细块 + 计数 + 条目 chip', async () => {
    assembleMock.mockResolvedValue(
      result([block('character_setting', { character_id: 'c-a' }, '角色甲')]),
    );
    injectionsMock.mockResolvedValue(
      injectionRecord({ character_ids: ['c-a'], world_ids: ['w-a'], foreshadowing_ids: [] }),
    );

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-echo')).toBeTruthy());
    expect(screen.getByTestId('context-injected-count').textContent).toContain('2');
    expect(screen.getByTestId('context-injected-execution').textContent).toContain('e-1');
    // 三类分组明细（有 id 的来源才渲染条目）
    expect(screen.getByTestId('context-injected-character_ids')).toBeTruthy();
    expect(screen.getByTestId('context-injected-world_ids')).toBeTruthy();
  });

  it('明细条目 id 逐个渲染（chip 文本含 id，便于回溯）', async () => {
    assembleMock.mockResolvedValue(result([]));
    injectionsMock.mockResolvedValue(
      injectionRecord({ character_ids: ['c-a', 'c-b'], world_ids: [], foreshadowing_ids: [] }),
    );

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-echo')).toBeTruthy());
    expect(screen.getByTestId('context-injected-item-c-a')).toBeTruthy();
    expect(screen.getByTestId('context-injected-item-c-b')).toBeTruthy();
  });

  it('章级读端点按 chapterId 调一次（切章重取）', async () => {
    assembleMock.mockResolvedValue(result([]));
    render(<ContextPanel {...OPTS} />);
    await waitFor(() => expect(injectionsMock).toHaveBeenCalledWith('c1'));
  });
});

// ─────────────────────────────────────────────────────────────────────
// 2 · 无记录 → 回退态
// ─────────────────────────────────────────────────────────────────────
describe('#1349 — 2 无记录 → 回退态', () => {
  it('injected_context=null → 渲染 context-injected-empty 提示，不渲染明细块', async () => {
    assembleMock.mockResolvedValue(
      result([block('character_setting', { character_id: 'c-a' }, '角色甲')]),
    );
    injectionsMock.mockResolvedValue(injectionRecord(null));

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-empty')).toBeTruthy());
    // 回退态：无计数徽章、无任何明细分组/条目（区壳体仍在，用于承载回退提示）
    expect(screen.queryByTestId('context-injected-count')).toBeNull();
    expect(screen.queryByTestId('context-injected-execution')).toBeNull();
    expect(screen.queryByTestId('context-injected-character_ids')).toBeNull();
  });

  it('预览主路径不受影响：无记录时既有 context-block-* 照常渲染', async () => {
    assembleMock.mockResolvedValue(
      result([block('character_setting', { character_id: 'c-a' }, '角色甲')]),
    );
    injectionsMock.mockResolvedValue(injectionRecord(null));

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-block-character_setting')).toBeTruthy());
    expect(screen.getByTestId('context-injected-empty')).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────
// 3 · 反向断言：两态互斥可区分
// ─────────────────────────────────────────────────────────────────────
describe('#1349 — 3 两态互斥（反向断言）', () => {
  it('有记录 → 不渲染回退态空提示（两态不会同时出现）', async () => {
    assembleMock.mockResolvedValue(result([]));
    injectionsMock.mockResolvedValue(
      injectionRecord({ character_ids: ['c-a'], world_ids: [], foreshadowing_ids: [] }),
    );

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-echo')).toBeTruthy());
    expect(screen.queryByTestId('context-injected-empty')).toBeNull();
  });

  it('负数守卫：三源全空数组（有记录但零条目）→ 明确渲染零计数，不是回退态', async () => {
    assembleMock.mockResolvedValue(result([]));
    injectionsMock.mockResolvedValue(
      injectionRecord({ character_ids: [], world_ids: [], foreshadowing_ids: [] }),
    );

    render(<ContextPanel {...OPTS} />);

    // 「有记录但本次确实没注入任何东西」≠「无记录」——前者是事实回执，必须可区分
    await waitFor(() => expect(screen.getByTestId('context-injected-echo')).toBeTruthy());
    expect(screen.getByTestId('context-injected-count').textContent).toContain('0');
  });

  it('回执面只读：明细区不含勾选框（控制面仍只在预览区块）', async () => {
    assembleMock.mockResolvedValue(
      result([block('character_setting', { character_id: 'c-a' }, '角色甲')]),
    );
    injectionsMock.mockResolvedValue(
      injectionRecord({ character_ids: ['c-a'], world_ids: [], foreshadowing_ids: [] }),
    );

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-echo')).toBeTruthy());
    const echo = screen.getByTestId('context-injected-echo');
    expect(echo.querySelectorAll('input[type="checkbox"]').length).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────────────
// 4 · 失败静默降级
// ─────────────────────────────────────────────────────────────────────
describe('#1349 — 4 读端点失败 → 静默降级为回退态', () => {
  it('请求 reject → 渲染回退态，预览区块不受影响', async () => {
    assembleMock.mockResolvedValue(
      result([block('character_setting', { character_id: 'c-a' }, '角色甲')]),
    );
    injectionsMock.mockRejectedValue(new Error('boom'));

    render(<ContextPanel {...OPTS} />);

    await waitFor(() => expect(screen.getByTestId('context-injected-empty')).toBeTruthy());
    expect(screen.getByTestId('context-block-character_setting')).toBeTruthy();
  });

  it('无 chapterId → 不调读端点（无章可回显）', async () => {
    assembleMock.mockResolvedValue(result([]));
    render(<ContextPanel {...OPTS} chapterId={null} />);
    await waitFor(() => expect(screen.getByTestId('context-panel')).toBeTruthy());
    expect(injectionsMock).not.toHaveBeenCalled();
  });
});
