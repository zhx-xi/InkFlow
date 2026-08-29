/**
 * 上下文面板契约（specs/f6-context-service/gui-panel.md #594）：
 * 静态占位 → 接 assemble API 渲染真实上下文条目 + 三级大纲注入 + 角色/伏笔勾选 override。
 * ⚠️ 本文件 = 契约。GREEN 实现 ContextPanel 必须匹配（行为断言，不测样式）。
 * 决策（2026-08-23）：D3=A 三级全注入；D4=A 先自动注入+展开/修改；覆盖 D1 override 通道（#593 后端已做）。
 *
 * RED 契约核心 3 用例（RED 阶段当前实现=静态占位恒显 common.empty，故全 FAIL）：
 *  1. 有数据时面板显示真实条目（context-block-* / context-character-*），非「暂无数据」空态；
 *     无数据才空态 context-empty。
 *  2. 勾选/取消注入项 → assembleContext 被再次调用且 override.character_ids 变化（白名单生效）。
 *  3. 三级大纲（总体/卷/章）自动注入 context-outline，缺级降级透传。
 * 守护用例（当前实现天然 PASS）：无 projectId/chapterId/model 时空态。
 *
 * 结构 testid（gui-panel.md §3.2）：context-panel /
 *  context-panel-content / context-empty / context-error /
 *  context-block-<source> / context-outline / context-character-<n> / context-foreshadow-<n> /
 *  context-item-toggle-<n> / context-dropped / context-dropped-<n>。
 *
 * mock 方式：vi.mock('../api/context') → assembleContext 捕获 body（含 override），
 *  用例手动改写 resolved 值。本地类型镜像，避免依赖未建 api 模块（ChatPanel.test 同款套路）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContextPanel } from './ContextPanel';
import { useThemeStore } from '../stores/theme';
import { listProjectCharacters } from '../api/character';

/** api/context 模块 mock 聚合（GREEN 建 src/api/context.ts），vi.hoisted 供 vi.mock 工厂引用 */
const contextApiMocks = vi.hoisted(() => ({
  assembleContext: vi.fn(),
  listProjectWorldSettings: vi.fn(),
  listProjectForeshadowings: vi.fn(),
}));
vi.mock('../api/context', () => contextApiMocks);
vi.mock('../api/character', () => ({
  listProjectCharacters: vi.fn(),
}));

const assembleMock = contextApiMocks.assembleContext;

/** 与 src/api/context.ts 契约一致（GREEN 建）：本地镜像类型，避免依赖未建模块 */
type ContextSourceType =
  | 'writing_requirements'
  | 'outline'
  | 'character_setting'
  | 'world_setting'
  | 'chapter_summary'
  | 'foreshadowing'
  | 'preference';
interface ContextItem {
  source: ContextSourceType;
  title: string;
  content: string;
  priority: number;
  metadata: Record<string, unknown>;
}
interface ContextBlock {
  item: ContextItem;
  layer: string;
  token_count: number;
  compressed: boolean;
}
interface ContextAssemblyResult {
  blocks: ContextBlock[];
  budget_tokens: number;
  total_tokens: number;
  model: string;
  dropped: Array<{ item: ContextItem; reason: string }>;
}
interface AssembleRequest {
  project_id: string;
  chapter_id: string;
  model: string;
  writing_requirements: string;
  max_tokens?: number | null;
  override?: { character_ids: string[]; foreshadowing_ids: string[] };
}

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  model: 'deepseek/deepseek-v4-flash',
  writingRequirements: '小说创作',
};

/** 三级大纲 block（含换行） */
function outlineBlock(): ContextBlock {
  return {
    item: {
      source: 'outline',
      title: '大纲',
      content: '总体：全书主线 —— 少年成长\n卷：第一卷 —— 青云城\n章：第一章 —— 初入宗门',
      priority: 0,
      metadata: { outline_ids: ['o1', 'o2', 'o3'] },
    },
    layer: 'protected',
    token_count: 120,
    compressed: false,
  };
}

/** 角色 block（带 character_id metadata，供 override 白名单过滤） */
function characterBlock(id: string, name: string): ContextBlock {
  return {
    item: {
      source: 'character_setting',
      title: `角色：${name}`,
      content: `${name}：${name}的简介`,
      priority: 0,
      metadata: { character_id: id },
    },
    layer: 'compressible',
    token_count: 30,
    compressed: false,
  };
}

/** 组合 assemble 结果（可定制） */
function result(blocks: ContextBlock[], dropped: ContextAssemblyResult['dropped'] = []) {
  return {
    blocks,
    budget_tokens: 51200,
    total_tokens: 1000,
    model: 'deepseek/deepseek-v4-flash',
    dropped,
  };
}

beforeEach(() => {
  assembleMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('ContextPanel — 有数据渲染真实条目（#594）', () => {
  it('有 outline + character blocks → 渲染 context-block-outline / context-block-character_setting / context-character-0；不渲染空态', async () => {
    assembleMock.mockResolvedValue(
      result([outlineBlock(), characterBlock('c-a', '林晚')]),
    );
    render(<ContextPanel {...OPTS} />);
    // 挂载自动注入
    await waitFor(() => {
      expect(assembleMock).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId('context-block-outline')).toBeInTheDocument();
    expect(screen.getByTestId('context-block-character_setting')).toBeInTheDocument();
    expect(screen.getByTestId('context-character-0')).toHaveTextContent('林晚');
    // 有数据不得显示空态
    expect(screen.queryByTestId('context-empty')).not.toBeInTheDocument();
  });

  it('已组装但 blocks 为空 → 渲染全部注入源分组骨架 context-block-<source>（UI 组件不能少，Issue #743）', async () => {
    assembleMock.mockResolvedValue(result([]));
    render(<ContextPanel {...OPTS} />);
    await waitFor(() => {
      expect(assembleMock).toHaveBeenCalledTimes(1);
    });
    // 每个注入源分组容器都渲染（角色/大纲/世界观/伏笔/章节摘要/写作要求），即使无条目
    for (const source of [
      'writing_requirements',
      'outline',
      'character_setting',
      'world_setting',
      'chapter_summary',
      'foreshadowing',
    ]) {
      expect(screen.getByTestId(`context-block-${source}`)).toBeInTheDocument();
    }
    // 不出现 JSON 原始
    expect(screen.getByTestId('context-panel-content').querySelector('pre')).toBeNull();
    expect(screen.getByTestId('context-panel-content').textContent).not.toMatch(/\{"source"|"metadata"/);
  });

  it('无 projectId/chapterId/model → 空态，不调 assemble（守护）', async () => {
    render(<ContextPanel projectId={null} chapterId={null} model={null} writingRequirements="x" />);
    expect(screen.getByTestId('context-empty')).toBeInTheDocument();
    expect(assembleMock).not.toHaveBeenCalled();
  });
});

describe('ContextPanel — 三级大纲自动注入（#594）', () => {
  it('outline block content 含总体/卷/章三级 → context-outline 显示三段（保留换行）', async () => {
    assembleMock.mockResolvedValue(result([outlineBlock()]));
    render(<ContextPanel {...OPTS} />);
    const el = await screen.findByTestId('context-outline');
    expect(el).toHaveTextContent('总体：全书主线');
    expect(el).toHaveTextContent('卷：第一卷');
    expect(el).toHaveTextContent('章：第一章');
    expect(el.textContent).toContain('\n');
  });

  it('缺级降级：content 只有总体+章（无卷）→ context-outline 显示存在的两级', async () => {
    const blk = outlineBlock();
    (blk.item as { content: string }).content = '总体：全书主线\n章：第一章 —— 初入宗门';
    assembleMock.mockResolvedValue(result([blk]));
    render(<ContextPanel {...OPTS} />);
    const el = await screen.findByTestId('context-outline');
    expect(el).toHaveTextContent('总体：全书主线');
    expect(el).toHaveTextContent('章：第一章');
    expect(el.textContent).not.toContain('卷：');
  });
});

describe('ContextPanel — 角色/伏笔勾选 override（#594）', () => {
  it('取消角色 A → assembleContext 再次调用且 override.character_ids 不含 A（白名单生效）', async () => {
    assembleMock.mockResolvedValue(
      result([characterBlock('c-a', '林晚'), characterBlock('c-b', '顾沉')]),
    );
    const user = userEvent.setup();
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-character-1');
    // 初始全注入 → override.character_ids 应为空（= 注入全部）或全量
    const firstCall = assembleMock.mock.calls[0][0] as AssembleRequest;
    expect(firstCall.override?.character_ids ?? []).toEqual([]);
    // 取消角色 A（勾选开关）
    await user.click(screen.getByTestId('context-item-toggle-0'));
    await waitFor(() => {
      expect(assembleMock).toHaveBeenCalledTimes(2);
    });
    const secondCall = assembleMock.mock.calls[1][0] as AssembleRequest;
    // 白名单：取消 A 后只剩 B 被注入 → override.character_ids 含 B 不含 A
    expect(secondCall.override?.character_ids).toContain('c-b');
    expect(secondCall.override?.character_ids).not.toContain('c-a');
  });

  it('勾选/取消后请求仍带 project_id/chapter_id/model/writing_requirements', async () => {
    assembleMock.mockResolvedValue(result([characterBlock('c-a', '林晚')]));
    const user = userEvent.setup();
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-character-0');
    await user.click(screen.getByTestId('context-item-toggle-0'));
    await waitFor(() => {
      expect(assembleMock).toHaveBeenCalledTimes(2);
    });
    const req = assembleMock.mock.calls[1][0] as AssembleRequest;
    expect(req.project_id).toBe('p1');
    expect(req.chapter_id).toBe('c1');
    expect(req.model).toBe('deepseek/deepseek-v4-flash');
    expect(req.writing_requirements).toBe('小说创作');
  });

  it('勾选开关渲染于角色/伏笔项内：context-item-toggle-<n> 存在（守护）', async () => {
    assembleMock.mockResolvedValue(
      result([characterBlock('c-a', '林晚'), characterBlock('c-b', '顾沉')]),
    );
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-character-1');
    expect(screen.getByTestId('context-item-toggle-0')).toBeInTheDocument();
    expect(screen.getByTestId('context-item-toggle-1')).toBeInTheDocument();
  });
});

describe('ContextPanel — 错误（守护）', () => {
  it('assemble 失败 → context-error 显示错误文案，不崩溃', async () => {
    assembleMock.mockRejectedValue(new Error('内核未就绪'));
    render(<ContextPanel {...OPTS} />);
    const err = await screen.findByTestId('context-error');
    expect(err).toHaveTextContent('内核未就绪');
  });
});
/** #704 分组「选择注入」搜索选择器多选追加（RED 契约） */
function worldBlock(id: string, name: string): ContextBlock {
  return {
    item: {
      source: 'world_setting',
      title: `世界观：${name}`,
      content: `${name}：${name}的设定`,
      priority: 0,
      metadata: { world_setting_id: id },
    },
    layer: 'compressible',
    token_count: 30,
    compressed: false,
  };
}
function foreshadowBlock(id: string, title: string): ContextBlock {
  return {
    item: {
      source: 'foreshadowing',
      title: `伏笔：${title}`,
      content: `${title}：伏笔内容`,
      priority: 0,
      metadata: { foreshadowing_id: id },
    },
    layer: 'dynamic',
    token_count: 20,
    compressed: false,
  };
}

describe('ContextPanel — 分组「＋ 选择注入」搜索选择器多选追加（#704）', () => {
  it('角色/世界观/伏笔分组标题行右侧各有「＋ 选择注入」按钮', async () => {
    assembleMock.mockResolvedValue(result([characterBlock('c-a', '林晚'), worldBlock('w-a', '李家'), foreshadowBlock('f-a', '归墟之约')]));
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-block-character_setting');
    expect(within(screen.getByTestId('context-block-character_setting')).getByRole('button', { name: /选择注入/ })).toBeInTheDocument();
    expect(within(screen.getByTestId('context-block-world_setting')).getByRole('button', { name: /选择注入/ })).toBeInTheDocument();
    expect(within(screen.getByTestId('context-block-foreshadowing')).getByRole('button', { name: /选择注入/ })).toBeInTheDocument();
  });

  it('点「＋ 选择注入」→ 弹出搜索选择器（搜索框 + 多选列表）', async () => {
    assembleMock.mockResolvedValue(result([characterBlock('c-a', '林晚')]));
    vi.mocked(listProjectCharacters).mockResolvedValue({ items: [{ id: 'c-a', name: '林晚' }, { id: 'c-b', name: '顾沉' }, { id: 'c-c', name: '白小宛' }], total: 3, offset: 0, limit: 50 });
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-block-character_setting');
    fireEvent.click(within(screen.getByTestId('context-block-character_setting')).getByRole('button', { name: /选择注入/ }));
    await screen.findByTestId('context-picker');
    expect(screen.getByTestId('context-picker-search')).toBeInTheDocument();
    expect(screen.getAllByTestId(/context-picker-opt-/)).toHaveLength(3);
  });

  it('搜索框过滤选项', async () => {
    assembleMock.mockResolvedValue(result([characterBlock('c-a', '林晚')]));
    vi.mocked(listProjectCharacters).mockResolvedValue({ items: [{ id: 'c-a', name: '林晚' }, { id: 'c-b', name: '顾沉' }], total: 2, offset: 0, limit: 50 });
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-block-character_setting');
    fireEvent.click(within(screen.getByTestId('context-block-character_setting')).getByRole('button', { name: /选择注入/ }));
    await screen.findByTestId('context-picker');
    fireEvent.change(screen.getByTestId('context-picker-search'), { target: { value: '林' } });
    expect(screen.getByText('林晚')).toBeInTheDocument();
    expect(screen.queryByText('顾沉')).not.toBeInTheDocument();
  });

  it('勾选后确认 → 追加到对应分组，assemble 重新调用且 override 含新增 id', async () => {
    assembleMock.mockResolvedValue(result([characterBlock('c-a', '林晚')]));
    vi.mocked(listProjectCharacters).mockResolvedValue({ items: [{ id: 'c-a', name: '林晚' }, { id: 'c-b', name: '顾沉' }], total: 2, offset: 0, limit: 50 });
    const user = userEvent.setup();
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-block-character_setting');
    fireEvent.click(within(screen.getByTestId('context-block-character_setting')).getByRole('button', { name: /选择注入/ }));
    await screen.findByTestId('context-picker');
    await user.click(screen.getByTestId('context-picker-opt-c-b'));
    await user.click(screen.getByTestId('context-picker-confirm'));
    await waitFor(() => expect(assembleMock).toHaveBeenCalledTimes(2));
    const req = assembleMock.mock.calls[1][0] as AssembleRequest;
    expect(req.override?.character_ids).toContain('c-b');
    expect(req.override?.character_ids).toContain('c-a');
  });
});

describe('ContextPanel — 结构化条目契约 context-item-<source>-<i>（#743）', () => {
  it('每个注入源条目渲染为 context-item-<source>-<i>，含 title+content+勾选框（含 world/章节摘要/writing_requirements）', async () => {
    const summaryBlock: ContextBlock = {
      item: {
        source: 'chapter_summary',
        title: '章节摘要',
        content: '第一章摘要：初入宗门',
        priority: 0,
        metadata: { chapter_id: 'c1' },
      },
      layer: 'protected',
      token_count: 10,
      compressed: false,
    };
    const reqBlock: ContextBlock = {
      item: {
        source: 'writing_requirements',
        title: '写作要求',
        content: '小说创作',
        priority: 0,
        metadata: {},
      },
      layer: 'protected',
      token_count: 5,
      compressed: false,
    };
    assembleMock.mockResolvedValue(
      result([
        reqBlock,
        characterBlock('c-a', '林晚'),
        worldBlock('w-a', '李家'),
        foreshadowBlock('f-a', '归墟之约'),
        summaryBlock,
      ]),
    );
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-item-character_setting-0');
    // 角色条目：统一 testid + title + content + 勾选框
    const charItem = screen.getByTestId('context-item-character_setting-0');
    expect(charItem).toHaveTextContent('林晚');
    expect(within(charItem).getByRole('checkbox')).toBeInTheDocument();
    // 世界观条目：当前实现无勾选框 → RED
    const worldItem = screen.getByTestId('context-item-world_setting-0');
    expect(worldItem).toHaveTextContent('李家');
    expect(within(worldItem).getByRole('checkbox')).toBeInTheDocument();
    // 伏笔条目
    const foreItem = screen.getByTestId('context-item-foreshadowing-0');
    expect(foreItem).toHaveTextContent('归墟之约');
    expect(within(foreItem).getByRole('checkbox')).toBeInTheDocument();
    // 章节摘要条目（当前走裸 div，无统一 testid → RED）
    const sumItem = screen.getByTestId('context-item-chapter_summary-0');
    expect(sumItem).toHaveTextContent('初入宗门');
    // 写作要求条目
    const reqItem = screen.getByTestId('context-item-writing_requirements-0');
    expect(reqItem).toHaveTextContent('小说创作');
  });

  it('不出现 JSON 原始数据（无 <pre>、无 {"source 字面量、无 metadata 直渲）', async () => {
    assembleMock.mockResolvedValue(
      result([characterBlock('c-a', '林晚'), worldBlock('w-a', '李家'), foreshadowBlock('f-a', '归墟之约')]),
    );
    render(<ContextPanel {...OPTS} />);
    await screen.findByTestId('context-item-character_setting-0');
    const panel = screen.getByTestId('context-panel-content');
    expect(panel.querySelector('pre')).toBeNull();
    expect(panel.textContent).not.toMatch(/\{"source"|"metadata"|"character_id"|"world_setting_id"/);
  });
});

describe('ContextPanel — 空写作要求优雅占位（#759）', () => {
  it('#759: writingRequirements 为空 → 不调 assemble + 显示「未填写写作要求」占位', async () => {
    render(<ContextPanel {...OPTS} writingRequirements="" />);
    await waitFor(() => {
      expect(assembleMock).not.toHaveBeenCalled();
    });
    const err = await screen.findByTestId('context-error');
    expect(err).toHaveTextContent('未填写写作要求');
  });

  it('#759: assemble 返回 422 string_too_short → 显示「未填写写作要求」占位，不渲染原始 JSON', async () => {
    assembleMock.mockRejectedValue(
      new Error(
        '[{"type":"string_too_short","loc":["body","writing_requirements"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]',
      ),
    );
    render(<ContextPanel {...OPTS} />);
    const err = await screen.findByTestId('context-error');
    expect(err).toHaveTextContent('未填写写作要求');
    expect(err.textContent).not.toMatch(/string_too_short/);
    expect(assembleMock).toHaveBeenCalled();
  });
});
