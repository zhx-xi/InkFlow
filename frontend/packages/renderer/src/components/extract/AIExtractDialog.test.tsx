/**
 * 「AI 提取」弹窗 RED 契约测试（#652 建 / #1528 + #1544 扩展）。
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【契约 v2（#1528 / #1544，2026-10-09）】
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 组件 components/extract/AIExtractDialog.tsx。直调 apiFetch。
 *
 * Props：{ open, onClose, projectId, defaultChapterId?, defaultText? }
 * - open=true 挂载时拉取：
 *   GET /api/v1/projects/{projectId}/chapters       （章节列表，全量翻页）
 *   GET /api/v1/projects/{projectId}/volumes        （卷列表，#1544 新增）
 *   GET /api/v1/projects/{projectId}/extractions/runs（最近一次运行摘要）
 *
 * DOM 结构（data-testid 即契约）：
 * - ai-extract-dialog         对话框根容器
 * - ai-extract-type           提取类型 radio 组（容器）
 *   选项可访问名「角色 / 世界观 / 时间线 / 伏笔 / 知识图谱 / 通用」
 *   （i18n extract.character/world/timeline/foreshadowing/knowledgeGraph/generic）
 * - ai-extract-generic        「通用」多选面板（容器，仅「通用」选中时渲染）
 *   选项可访问名同上 5 类（不含「通用」）
 * - ai-extract-scope          提取范围 radio 组（容器）
 *   选项可访问名「全文 / 按卷 / 按章」（i18n extract.scope.all/volume/chapter）
 * - ai-extract-volume-list    「按卷」卷多选容器（仅「按卷」时渲染）
 * - ai-extract-range-from / ai-extract-range-to / ai-extract-range-add
 *                             「按章」区间输入 + 添加按钮（仅「按章」时渲染）
 * - ai-extract-run            提交按钮「开始提取」
 * - ai-extract-running        运行中指示
 * - ai-extract-last-run       最近一次运行摘要卡
 *
 * 提交语义（#1544 统一走 POST /api/v1/extract，type 由所选类型决定）：
 * - 类型 → type 映射：角色→character、世界观→setting、时间线→timeline、
 *   伏笔→foreshadowing、知识图谱→knowledge_relation
 * - 单选 = 只发 1 次；「通用」多选 = 每个选中类型各发 1 次
 * - 范围 → chapter_ids：全文=全部章；按卷=选中卷全部章；按章=各区间展开
 * - 单次 chapter_ids ≤ 100；超出自动分批（每批 ≤100，多请求）
 * - timeline：body 带 chapter_ids + auto_extract=true（不带 text）
 * - knowledge_relation：body 不带 text / chapter_ids（项目级提取）
 *
 * 反馈三态（保留 #652 语义）：
 * - 进行中：按钮 disabled + ai-extract-running
 * - 完成：toast ok「提取完成 · ...」+ 重拉最近运行摘要
 * - 失败：toast err（errorMessage）+ 按钮恢复 enabled
 *
 * ───────────────────────────────────────────────────────────────────────────
 * 【RED 预期失败形态】v2 新契约在 v1 实现下必 FAIL（无 timeline radio / 无范围选择 /
 * 无多选 / 仍打 /characters/extract 等）；结构性 testid 不存在 = element-missing。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIExtractDialog } from './AIExtractDialog';
import { apiFetch } from '../../api/client';
import { useToastStore } from '../../stores/toast';
import { extractEn, extractZh } from '../../i18n/extract-keys';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 卷列表响应（镜像 GET /projects/{pid}/volumes） */
const VOLUMES_RESP = {
  items: [
    { id: 'v1', project_id: 'p1', title: '第一卷 起', order_index: 0 },
    { id: 'v2', project_id: 'p1', title: '第二卷 承', order_index: 1 },
  ],
};

/** 章节列表响应（全量翻页后） */
const CHAPTERS_RESP = {
  items: [
    { id: 'ch1', title: '第一章', volume_id: 'v1', order_index: 0, word_count: 10 },
    { id: 'ch2', title: '第二章', volume_id: 'v1', order_index: 1, word_count: 10 },
    { id: 'ch3', title: '第三章', volume_id: 'v2', order_index: 2, word_count: 10 },
  ],
  total: 3,
  offset: 0,
  limit: 50,
};

/** 最近一次运行：GET extractions/runs 响应（ExtractionRun 形态） */
const RUN_LIST = {
  items: [
    {
      id: 9,
      project_id: 'p1',
      type: 'timeline',
      source_key: 'ch1',
      content_hash: 'abc',
      status: 'success',
      created_count: 3,
      updated_count: 1,
      warnings_json: '[]',
      error: null,
      model: 'deepseek-chat',
      indexed: false,
      run_at: '2026-10-09T00:00:00Z',
    },
  ],
  total: 1,
  offset: 0,
  limit: 1,
};

/** 统一提取结果信封（ExtractionResult 形态） */
const ENVELOPE = {
  type: 'character',
  status: 'success',
  skipped_reason: null,
  processed_sources: 1,
  skipped_sources: 0,
  created: 2,
  updated: 1,
  warnings: [],
  model: 'deepseek-chat',
  indexed: false,
  batch_id: 'ext-abc',
  detail: {},
};

/** 已拨出的 POST /api/v1/extract 请求体清单（按调用顺序） */
function extractBodies(): Array<Record<string, unknown>> {
  return apiFetchMock.mock.calls
    .filter((c) => c[0] === '/api/v1/extract' && (c[1] as { method?: string })?.method === 'POST')
    .map((c) => (c[1] as { body: Record<string, unknown> }).body);
}

function renderDialog(props: Partial<React.ComponentProps<typeof AIExtractDialog>> = {}) {
  return render(<AIExtractDialog open onClose={() => {}} projectId="p1" {...props} />);
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/chapters') return { ...CHAPTERS_RESP };
    if (path.startsWith('/api/v1/projects/p1/chapters')) return { ...CHAPTERS_RESP };
    if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUN_LIST };
    if (path === '/api/v1/extract' && init?.method === 'POST') return { ...ENVELOPE };
    return { ok: true };
  });
});

describe('「AI 提取」弹窗（#652 / #1528 / #1544）', () => {
  it('契约1（结构）：渲染出 dialog + 标题 + 六类型单选 + 三范围单选', async () => {
    renderDialog();
    const dlg = await screen.findByTestId('ai-extract-dialog');
    expect(within(dlg).getByText('AI 提取')).toBeInTheDocument();
    const typeGroup = within(dlg).getByTestId('ai-extract-type');
    for (const name of ['角色', '世界观', '时间线', '伏笔', '知识图谱', '通用']) {
      expect(within(typeGroup).getByRole('radio', { name })).toBeInTheDocument();
    }
    const scopeGroup = within(dlg).getByTestId('ai-extract-scope');
    for (const name of ['全文', '按卷', '按章']) {
      expect(within(scopeGroup).getByRole('radio', { name })).toBeInTheDocument();
    }
  });

  it('契约2（数据加载）：open 拉取章节 / 卷 / 最近运行摘要', async () => {
    renderDialog();
    await screen.findByTestId('ai-extract-dialog');
    await waitFor(() => {
      const paths = apiFetchMock.mock.calls.map((c) => c[0]);
      expect(paths).toContain('/api/v1/projects/p1/chapters');
      expect(paths).toContain('/api/v1/projects/p1/volumes');
    });
    const lastRun = await screen.findByTestId('ai-extract-last-run');
    // RUN_TYPE_LABELS 映射：timeline → 「时间线」（#1528 验收：非原始值）
    expect(within(lastRun).getByText(/时间线/)).toBeInTheDocument();
  });

  it('契约3a（角色 + 全文）：POST /extract {type:character, chapter_ids:全部章}', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const bodies = extractBodies();
      expect(bodies).toHaveLength(1);
      expect(bodies[0].project_id).toBe('p1');
      expect(bodies[0].type).toBe('character');
      expect(bodies[0].chapter_ids).toEqual(['ch1', 'ch2', 'ch3']);
    });
  });

  it('契约3b（世界观）：type=setting（非 world）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '世界观' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const bodies = extractBodies();
      expect(bodies).toHaveLength(1);
      expect(bodies[0].type).toBe('setting');
    });
  });

  it('契约3c（时间线）：token=timeline + chapter_ids + auto_extract（不带 text）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '时间线' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const bodies = extractBodies();
      expect(bodies[0].type).toBe('timeline');
      expect(bodies[0].auto_extract).toBe(true);
      expect(bodies[0].chapter_ids).toEqual(['ch1', 'ch2', 'ch3']);
      expect(bodies[0].text).toBeUndefined();
    });
  });

  it('契约3d（知识图谱）：type=knowledge_relation，不带 text / chapter_ids', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '知识图谱' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const bodies = extractBodies();
      expect(bodies).toHaveLength(1);
      expect(bodies[0].type).toBe('knowledge_relation');
      expect(bodies[0].chapter_ids).toBeUndefined();
      expect(bodies[0].text).toBeUndefined();
    });
  });

  it('契约4（通用多选）：勾选角色+伏笔 → 各发一次，type 正确', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '通用' }));
    const panel = await screen.findByTestId('ai-extract-generic');
    // 默认全不选 → 勾选角色 + 伏笔
    await user.click(within(panel).getByRole('checkbox', { name: '角色' }));
    await user.click(within(panel).getByRole('checkbox', { name: '伏笔' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const types = extractBodies().map((b) => b.type).sort();
      expect(types).toEqual(['character', 'foreshadowing']);
    });
  });

  it('契约5（按卷）：选中第二卷 → chapter_ids=该卷全部章', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '按卷' }));
    const volList = await screen.findByTestId('ai-extract-volume-list');
    await user.click(within(volList).getByRole('checkbox', { name: /第二卷/ }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      expect(extractBodies()[0].chapter_ids).toEqual(['ch3']);
    });
  });

  it('契约6（按章区间）：第 1–2 章 → chapter_ids=前两章', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '按章' }));
    await user.type(await screen.findByTestId('ai-extract-range-from'), '1');
    await user.type(await screen.findByTestId('ai-extract-range-to'), '2');
    await user.click(await screen.findByTestId('ai-extract-range-add'));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      expect(extractBodies()[0].chapter_ids).toEqual(['ch1', 'ch2']);
    });
  });

  it('契约7（分批）：全文 150 章 → 每批 ≤100，共 2 次请求', async () => {
    const many = Array.from({ length: 150 }, (_, i) => ({
      id: `c${i}`,
      title: `第${i + 1}章`,
      volume_id: 'v1',
      order_index: i,
      word_count: 1,
    }));
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path.startsWith('/api/v1/projects/p1/chapters')) {
        // 分页语义 mock：只翻全量才能真正拿到 150 章（覆盖 #1407 全量加载契约）
        const qs = new URLSearchParams(path.slice('/api/v1/projects/p1/chapters'.length));
        const offset = Number(qs.get('offset') ?? 0);
        const limit = Math.min(Number(qs.get('limit') ?? 50), 100);
        return { items: many.slice(offset, offset + limit), total: many.length, offset, limit };
      }
      if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
      if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUN_LIST };
      if (path === '/api/v1/extract' && init?.method === 'POST') return { ...ENVELOPE };
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const bodies = extractBodies();
      expect(bodies).toHaveLength(2);
      const sizes = bodies.map((b) => (b.chapter_ids as string[]).length).sort((a, b) => a - b);
      expect(sizes).toEqual([50, 100]);
    });
  });

  it('契约8（三态-进行中）：提交后按钮 disabled + running 指示', async () => {
    let resolvePost: (v: typeof ENVELOPE) => void;
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path.startsWith('/api/v1/projects/p1/chapters')) return { ...CHAPTERS_RESP };
      if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
      if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUN_LIST };
      if (path === '/api/v1/extract' && init?.method === 'POST') {
        return new Promise((res) => {
          resolvePost = res as (v: typeof ENVELOPE) => void;
        });
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    const run = await screen.findByTestId('ai-extract-run');
    await user.click(run);
    await waitFor(() => expect(run).toBeDisabled());
    expect(screen.getByTestId('ai-extract-running')).toBeInTheDocument();
    resolvePost!({ ...ENVELOPE });
  });

  it('契约9（失败降级）：后端拒绝 → err toast + 按钮恢复 enabled', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path.startsWith('/api/v1/projects/p1/chapters')) return { ...CHAPTERS_RESP };
      if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
      if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUN_LIST };
      if (path === '/api/v1/extract' && init?.method === 'POST') {
        throw new (await import('../../api/client')).ApiError(422, '未配置大模型，请先在设置中配置模型');
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByRole('radio', { name: '全文' }));
    const run = await screen.findByTestId('ai-extract-run');
    await user.click(run);
    await waitFor(() => {
      const toast = useToastStore.getState().toasts.find((x) => x.type === 'err');
      expect(toast?.message).toMatch(/未配置大模型/);
    });
    await waitFor(() => expect(run).toBeEnabled());
  });

  it('契约10（i18n）：新增 extract.* 键 zh/en 均存在', async () => {
    const keys = [
      'title',
      'character',
      'world',
      'timeline',
      'foreshadowing',
      'knowledgeGraph',
      'generic',
      'scope',
      'scope.all',
      'scope.volume',
      'scope.chapter',
      'genericHint',
      'rangeHint',
      'run',
      'running',
      'done',
      'failed',
      'lastRun',
      'noRun',
    ] as const;
    for (const k of keys) {
      const key = `extract.${k}`;
      expect(extractZh[key], `${key} zh`).toBeTruthy();
      expect(extractEn[key], `${key} en`).toBeTruthy();
    }
    expect(extractZh['extract.timeline']).toBe('时间线');
    expect(extractZh['extract.knowledgeGraph']).toBe('知识图谱');
  });
});
