/**
 * 「AI 提取」弹窗 RED 契约测试（#652，GUI 提取通道）。
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【契约（父侧定稿，2026-08-26，排版确认门 M2 已过：触发=A 整章一键 / 通用带上 / 记录按建议 / 写作默认当前章）】
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 新组件 components/extract/AIExtractDialog.tsx（GREEN CREATE）。
 * 直调 apiFetch（镜像 KnowledgeExtractCard 先例，不建 api/extract.ts 模块，
 * 规避「测试 import 未建模块 → 文件级 0 用例连坐」）。
 *
 * Props：{ open, onClose, projectId, defaultChapterId?, defaultText? }
 * - open=true 挂载时拉取：GET /api/v1/projects/{projectId}/chapters（章节列表）+
 *   GET /api/v1/projects/{projectId}/extractions/runs?limit=1（最近一次运行摘要）
 *
 * DOM 结构（data-testid 即契约）：
 * - ai-extract-dialog：对话框根容器
 * - ai-extract-type：提取类型 radio 组（容器）
 *   选项可访问名「角色 / 世界观 / 通用」（i18n extract.character/world/generic）
 * - ai-extract-type-generic：通用模式下类型 Select（选项 foreshadowing / knowledge_relation）
 * - ai-extract-chapter：章节 Select（整章一键，源 = 所选章节）
 * - ai-extract-run：提交按钮「开始提取」
 * - ai-extract-running：运行中指示（按钮 disabled 时存在）
 * - ai-extract-last-run：最近一次运行摘要卡
 *
 * 提交语义（触发 = A，整章一键 → 前端取所选章节内容作 text）：
 * - 取 text：若已选章节 == defaultChapterId 且 defaultText 非空 → 直接用 defaultText；
 *   否则 GET /api/v1/chapters/{selectedId} → content
 * - 角色 → POST /api/v1/characters/extract，body { project_id, text }
 * - 世界观 → POST /api/v1/world-settings/extract，body { project_id, text }
 * - 通用 → POST /api/v1/extract，body { project_id, type, text }
 *   （通用 type Select 默认 foreshadowing；角色/世界观不填 type）
 *
 * 反馈三态：
 * - 进行中：提交后按钮 disabled + ai-extract-running 出现（await POST，不轮询）
 * - 完成：toast ok「提取完成 · 新增 N · 更新 M · 已落地设定库」+ 重拉最近运行摘要
 * - 失败：toast err（errorMessage 来自后端 ApiError.detail；未配模型/embedding 优雅降级
 *   ——拒绝时不硬崩、按钮恢复 enabled）
 *
 * i18n 键（GREEN 补 zh/en extract.*）：
 * extract.title/extract.character/extract.world/extract.generic/extract.typeGeneric/
 * extract.chapter/extract.run/extract.running/extract.done/extract.failed/extract.lastRun/
 * extract.noRun（中文：title=AI 提取、run=开始提取、running=提取中、
 * lastRun=最近一次提取、noRun=暂无提取记录；其余文案 GREEN 自由定但键必须存在）
 *
 * ───────────────────────────────────────────────────────────────────────────
 * 【RED 预期失败形态】
 * ① element-missing：ai-extract-* testid 不存在（组件未建）
 * ② i18n 键 undefined：zh/en 的 extract.* 为 undefined（assert 类）
 * ③ 本文件不 import 任何未建模块（apiFetch/client 已存在），module-not-found 不出现。
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

/** 章节列表响应（镜像 useChapterStore ChapterListResponse） */
const CHAPTERS_RESP = {
  items: [
    { id: 'ch1', title: '第三章 青云之巅', volume_id: null, order_index: 3, word_count: 3200 },
    { id: 'ch2', title: '第二章 往事', volume_id: null, order_index: 2, word_count: 2100 },
  ],
  total: 2, offset: 0, limit: 50,
};

/** 章节全文（镜像 Chapter 含 content） */
const CHAPTER_DETAIL = { id: 'ch1', title: '第三章 青云之巅', volume_id: null, order_index: 3, word_count: 3200, project_id: 'p1', content: '青云山巅，剑气纵横。' };

/** 最近一次运行：GET extractions/runs 响应（ExtractionRun 形态） */
const RUN_LIST = {
  items: [
    {
      id: 9, project_id: 'p1', type: 'character', source_key: 'ch1',
      content_hash: 'abc', status: 'success', created_count: 3, updated_count: 1,
      warnings_json: '[]', error: null, model: 'deepseek-chat', indexed: false,
      run_at: '2026-08-26T00:00:00Z',
    },
  ],
  total: 1, offset: 0, limit: 1,
};

/** 角色提取结果（CharacterExtractionResult 形态） */
const CHAR_RESULT = {
  created: [{ id: 'c1', name: '苏云舟' }, { id: 'c2', name: '沈青梧' }],
  updated: [{ id: 'c3', name: '顾长生' }],
  relations_created: [], relations_updated: [], warnings: [], model: 'deepseek-chat',
};

/** 世界观提取结果（WorldExtractionResult 形态） */
const WORLD_RESULT = {
  created: [{ id: 'w1', name: '青云宗' }],
  updated: [], warnings: [], model: 'deepseek-chat',
};

/** 通用提取结果（ExtractionResult 形态，created/updated 为计数） */
const GENERIC_RESULT = {
  type: 'foreshadowing', status: 'success', skipped_reason: null,
  processed_sources: 1, skipped_sources: 0, created: 2, updated: 0,
  warnings: [], model: 'deepseek-chat', indexed: false, detail: {},
};

/** i18n 契约键集（extract.*，zh/en 双断言；RED 期 undefined） */
const EXTRACT_KEYS = [
  'title', 'character', 'world', 'generic', 'typeGeneric', 'chapter',
  'run', 'running', 'done', 'failed', 'lastRun', 'noRun',
] as const;

function renderDialog(props: Partial<React.ComponentProps<typeof AIExtractDialog>> = {}) {
  return render(
    <AIExtractDialog open onClose={() => {}} projectId="p1" {...props} />,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useToastStore.setState({ toasts: [] });
  // URL 分发默认 mock：章节 / runs / 章节全文 / 三提取端点
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects/p1/chapters') return { ...CHAPTERS_RESP };
    if (path === '/api/v1/projects/p1/extractions/runs') return { ...RUN_LIST };
    if (path === '/api/v1/chapters/ch1') return { ...CHAPTER_DETAIL };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUN_LIST };
    if (path === '/api/v1/characters/extract' && init?.method === 'POST') return { ...CHAR_RESULT };
    if (path === '/api/v1/world-settings/extract' && init?.method === 'POST') return { ...WORLD_RESULT };
    if (path === '/api/v1/extract' && init?.method === 'POST') return { ...GENERIC_RESULT };
    return { ok: true };
  });
});

describe('「AI 提取」弹窗（#652）', () => {
  it('契约1（结构）：渲染出 ai-extract-dialog + 标题「AI 提取」+ 三类型选项', async () => {
    renderDialog();
    const dlg = await screen.findByTestId('ai-extract-dialog');
    expect(within(dlg).getByText('AI 提取')).toBeInTheDocument();
    expect(within(dlg).getByRole('radio', { name: '角色' })).toBeInTheDocument();
    expect(within(dlg).getByRole('radio', { name: '世界观' })).toBeInTheDocument();
    expect(within(dlg).getByRole('radio', { name: '通用' })).toBeInTheDocument();
  });

  it('契约2（章节+记录）：open 拉取章节列表与最近一次运行摘要', async () => {
    renderDialog();
    // 章节 Select 渲染（整章一键来源）
    await screen.findByTestId('ai-extract-chapter');
    // 最近一次运行摘要卡渲染（记录 status + created/updated）
    const lastRun = await screen.findByTestId('ai-extract-last-run');
    expect(within(lastRun).getByText(/角色/)).toBeInTheDocument();
    expect(within(lastRun).getByText(/新增 3 · 更新 1/)).toBeInTheDocument();
  });

  it('契约3a（角色）：选「角色」+ 提交 → POST /api/v1/characters/extract，body {project_id,text}', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/extract' && (c[1] as { method?: string })?.method === 'POST',
      );
      expect(call).toBeDefined();
      const body = (call![1] as { body?: Record<string, unknown> }).body;
      expect(body?.project_id).toBe('p1');
      expect(typeof body?.text).toBe('string');
      expect(body?.text).toBeTruthy();
    });
    // 完成 toast：ok「提取完成 · 新增 2 · 更新 1 · 已落地设定库」（用 created.length/updated.length）
    await waitFor(() => {
      const toast = useToastStore.getState().toasts.find((x) => x.type === 'ok');
      expect(toast?.message).toMatch(/新增 2/);
      expect(toast?.message).toMatch(/更新 1/);
      expect(toast?.message).toMatch(/已落地设定库/);
    });
  });

  it('契约3b（世界观）：选「世界观」+ 提交 → POST /api/v1/world-settings/extract，body {project_id,text}', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '世界观' }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/world-settings/extract' && (c[1] as { method?: string })?.method === 'POST',
      );
      expect(call).toBeDefined();
      const body = (call![1] as { body?: Record<string, unknown> }).body;
      expect(body?.project_id).toBe('p1');
      expect(typeof body?.text).toBe('string');
    });
  });

  it('契约3c（通用）：选「通用」+ 提交 → POST /api/v1/extract，body {project_id,type,text}', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '通用' }));
    // 通用模式出现类型 Select（默认 foreshadowing）
    const typeSel = await screen.findByTestId('ai-extract-type-generic');
    await user.click(typeSel);
    await user.click(await screen.findByRole('option', { name: /伏笔/ }));
    await user.click(await screen.findByTestId('ai-extract-run'));
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/extract' && (c[1] as { method?: string })?.method === 'POST',
      );
      expect(call).toBeDefined();
      const body = (call![1] as { body?: Record<string, unknown> }).body;
      expect(body?.project_id).toBe('p1');
      expect(body?.type).toBeTruthy();
      expect(typeof body?.text).toBe('string');
    });
  });

  it('契约4（三态-进行中）：提交后运行中→按钮 disabled + ai-extract-running 出现', async () => {
    let resolvePost: (v: typeof CHAR_RESULT) => void;
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects/p1/chapters') return { ...CHAPTERS_RESP };
      if (path === '/api/v1/projects/p1/extractions/runs') return { ...RUN_LIST };
      if (path === '/api/v1/characters/extract' && init?.method === 'POST') {
        return new Promise((res) => { resolvePost = res; });
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    const run = await screen.findByTestId('ai-extract-run');
    await user.click(run);
    // 进行中：按钮 disabled + running 指示
    await waitFor(() => expect(run).toBeDisabled());
    expect(screen.getByTestId('ai-extract-running')).toBeInTheDocument();
    resolvePost!({ ...CHAR_RESULT } as typeof CHAR_RESULT);
  });

  it('契约5（三态-失败降级）：后端拒绝（未配模型）→ err toast + 按钮恢复 enabled（不硬崩）', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/chapters') return { ...CHAPTERS_RESP };
      if (path === '/api/v1/projects/p1/extractions/runs') return { ...RUN_LIST };
      if (path === '/api/v1/chapters/ch1') return { ...CHAPTER_DETAIL };
      if (path === '/api/v1/characters/extract' && init?.method === 'POST') {
        // 模拟后端 422（未配置模型/LLM 路径走 500，这里统一 ApiError 形态）
        throw new (await import('../../api/client')).ApiError(422, '未配置大模型，请先在设置中配置模型');
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByRole('radio', { name: '角色' }));
    const run = await screen.findByTestId('ai-extract-run');
    await user.click(run);
    // 失败 → err toast（优雅降级文案来自 errorMessage）
    await waitFor(() => {
      const toast = useToastStore.getState().toasts.find((x) => x.type === 'err');
      expect(toast?.message).toMatch(/未配置大模型/);
    });
    // 按钮恢复 enabled（不硬崩）
    await waitFor(() => expect(run).toBeEnabled());
  });

  it('契约6（i18n）：extract.* 键 zh/en 均存在（RED 期 undefined 失败形态）', () => {
    for (const k of EXTRACT_KEYS) {
      const key = `extract.${k}` as const;
      expect(extractZh[key]).toBeTruthy();
      expect(extractEn[key]).toBeTruthy();
    }
    expect(extractZh['extract.title']).toBe('AI 提取');
    expect(extractZh['extract.run']).toBe('开始提取');
  });
});
