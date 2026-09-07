/**
 * DraftApprovalDrawer 契约测试（#976 草稿审批弹层 + #988 来源锚定 fallback）
 *
 * ⚠️ 本文件 = 契约。实现 src/components/DraftApprovalDrawer.tsx 必须匹配：
 * export function DraftApprovalDrawer(props: { open: boolean; onClose(): void }): JSX.Element
 *
 * 结构 testid：
 * - drafts-overlay（遮罩）/ drafts-drawer（面板）
 * - drafts-drawer-item-{draftId}（草稿行）
 * - drafts-drawer-confirm-{draftId}（确认钮 → confirmDraft）
 * - drafts-drawer-error（确认失败错误）
 *
 * 行为契约：
 * - open=false → 不渲染（queryByTestId('drafts-drawer') 为 null，不发 listDrafts）
 * - open=true → listDrafts(projectId, 'draft') 载入并渲染每草稿行
 * - 点确认钮 → confirmDraft(draftId, options) 成功 → onClose() 关框
 *   （#988 契约升级：第二参恒为 options 对象；无来源可传时为 {}）
 * - 确认失败 → drafts-drawer-error 展示
 * - Esc → onClose()
 *
 * #988 确认面来源锚定 fallback（handleConfirm 前置计算，按优先级）:
 * 1. draft.source_outline_id 非空（创建时已记）→ options={sourceOutlineId: 该值}，
 *    不拉 outline 树（零多余请求）；
 * 2. draft.chapter_id == null 且无记录 → 反查项目 outline 树（apiFetch GET
 *    /api/v1/projects/{pid}/outlines，limit=100 分页至多 5 页），level=chapter 节点：
 *    唯一精确命中（name === draft.summary）> 唯一包含命中（summary 包含 name）
 *    → options={sourceOutlineId: 命中节点 id}；无命中/多命中 → options={}（不上传，
 *    后端 D4 自然不触发，零误绑）；
 * 3. draft.chapter_id 非空（已绑章，D4 不触发）→ options={}，且不拉 outline 树。
 * title 显式默认不传（后端自动建章标题规则已存在：显式 > summary[:30] > 默认）。
 *
 * projectId 自 useProjectStore 当前项目；确认成功后 useChapterStore.loadChapterTree 重拉
 * （apiFetch 已 mock 吸收，避免真实网络请求）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DraftApprovalDrawer } from './DraftApprovalDrawer';
import { listDrafts, confirmDraft } from '../api/drafts';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/drafts', () => ({
  listDrafts: vi.fn(),
  confirmDraft: vi.fn(),
  rejectDraft: vi.fn(),
  updateDraft: vi.fn(),
  pruneOrphans: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const listDraftsMock = vi.mocked(listDrafts);
const confirmDraftMock = vi.mocked(confirmDraft);
const apiFetchMock = vi.mocked(apiFetch);

/** RED 期契约种子：与 api/drafts.ts DraftDto 对齐（status='draft'，volume_id/source_outline_id 可选） */
interface SeedDraft {
  id: string;
  project_id: string;
  chapter_id: string | null;
  agent_run_id: string | null;
  content: string;
  status: string;
  summary: string;
  created_at: string;
  confirmed_at: string | null;
  volume_id?: string | null;
  source_outline_id?: string | null;
}

const seedDraft1: SeedDraft = {
  id: 'd1',
  project_id: 'p1',
  chapter_id: null,
  agent_run_id: 'r1',
  content: 'AI 生成的章节草稿正文',
  status: 'draft',
  summary: '第3章 渡口夜雾',
  created_at: '2026-08-25T10:00:00Z',
  confirmed_at: null,
  volume_id: 'v1',
};

const seedDraft2: SeedDraft = {
  ...seedDraft1,
  id: 'd2',
  agent_run_id: 'r2',
  content: '第二份草稿正文',
  summary: '第4章 山中客栈',
  volume_id: null,
};

/** outline 树分发器：按 path 返回章点（apiFetch mock 统一入口） */
function mockOutlineRoute(items: Array<{ id: string; name: string; level: string }>) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (typeof path === 'string' && path.startsWith('/api/v1/projects/p1/outlines')) {
      return { items, total: items.length, offset: 0, limit: 100 } as never;
    }
    return { items: [], total: 0 } as never;
  });
}

beforeEach(() => {
  listDraftsMock.mockReset();
  confirmDraftMock.mockReset();
  apiFetchMock.mockReset();
  // loadChapterTree 等内部 apiFetch 调用安全吸收（返回空列表，不触发真实 fetch）
  apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
  useProjectStore.setState({
    projects: [
      { id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' },
    ],
    currentProjectId: 'p1',
    loading: false,
    error: null,
  });
  // 中文文案断言锚：实现侧 t('write.drafts.*') 依赖 zh 语言包，显式播种 zh
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('DraftApprovalDrawer — 渲染与加载', () => {
  it('open=false → 不渲染（不发 listDrafts）', () => {
    render(<DraftApprovalDrawer open={false} onClose={() => {}} />);
    expect(screen.queryByTestId('drafts-drawer')).not.toBeInTheDocument();
    expect(screen.queryByTestId('drafts-overlay')).not.toBeInTheDocument();
    expect(listDraftsMock).not.toHaveBeenCalled();
  });

  it('open=true → listDrafts(projectId, draft) 载入 + 渲染遮罩/面板/草稿行', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1, seedDraft2], total: 2 });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    expect(await screen.findByTestId('drafts-drawer')).toBeInTheDocument();
    expect(screen.getByTestId('drafts-overlay')).toBeInTheDocument();
    await waitFor(() => expect(listDraftsMock).toHaveBeenCalledWith('p1', 'draft'));
    expect(screen.getByTestId('drafts-drawer-item-d1')).toBeInTheDocument();
    expect(screen.getByTestId('drafts-drawer-item-d2')).toBeInTheDocument();
  });
});

describe('DraftApprovalDrawer — 确认闭环', () => {
  it('【#988 迁移】点确认钮 → confirmDraft(draftId, {}) 成功 → onClose 关框（无来源可传形态）', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    const onClose = vi.fn();
    render(<DraftApprovalDrawer open onClose={onClose} />);
    const btn = await screen.findByTestId('drafts-drawer-confirm-d1');
    // 无 outline 树命中（apiFetch 兜底空 items）→ 不上传来源锚（options 恒对象形态）
    fireEvent.click(btn);
    await waitFor(() => expect(confirmDraftMock).toHaveBeenCalledWith('d1', {}));
    // 关框 = 受控语义：组件调 onClose，父级置 open=false（契约不要求自关闭）
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('确认失败 → drafts-drawer-error 展示', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    confirmDraftMock.mockRejectedValue(new Error('草稿未绑定目标章节'));
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    const btn = await screen.findByTestId('drafts-drawer-confirm-d1');
    fireEvent.click(btn);
    expect(await screen.findByTestId('drafts-drawer-error')).toHaveTextContent('草稿未绑定目标章节');
  });

  it('Esc 关闭 → onClose', async () => {
    listDraftsMock.mockResolvedValue({ items: [], total: 0 });
    const onClose = vi.fn();
    render(<DraftApprovalDrawer open onClose={onClose} />);
    await screen.findByTestId('drafts-drawer');
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});

describe('DraftApprovalDrawer — #988 来源锚定 fallback', () => {
  it('【R】草稿已记录 source_outline_id → 直接上传，不拉 outline 树', async () => {
    const recorded: SeedDraft = { ...seedDraft1, source_outline_id: 'o1' };
    listDraftsMock.mockResolvedValue({ items: [recorded], total: 1 });
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    const btn = await screen.findByTestId('drafts-drawer-confirm-d1');
    fireEvent.click(btn);
    await waitFor(() =>
      expect(confirmDraftMock).toHaveBeenCalledWith('d1', { sourceOutlineId: 'o1' }),
    );
    // 零多余请求：不反查 outline 树
    const outlineCalls = apiFetchMock.mock.calls.filter((c) =>
      String(c[0]).includes('/outlines'),
    );
    expect(outlineCalls).toHaveLength(0);
  });

  it('【R】未记录 + 未绑章 + summary 精确命中章点名 → 反查上传', async () => {
    const draft: SeedDraft = { ...seedDraft1, summary: '渡口夜雾' };
    listDraftsMock.mockResolvedValue({ items: [draft], total: 1 });
    mockOutlineRoute([
      { id: 'o1', name: '渡口夜雾', level: 'chapter' },
      { id: 'o2', name: '山中客栈', level: 'chapter' },
      { id: 'v1', name: '第一卷', level: 'volume' },
    ]);
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('drafts-drawer-confirm-d1'));
    await waitFor(() =>
      expect(confirmDraftMock).toHaveBeenCalledWith('d1', { sourceOutlineId: 'o1' }),
    );
    expect(
      apiFetchMock.mock.calls.some((c) => String(c[0]).includes('/api/v1/projects/p1/outlines')),
    ).toBe(true);
  });

  it('【R】summary 包含唯一章点名（书名式摘要）→ 包含命中上传', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    mockOutlineRoute([{ id: 'o9', name: '渡口夜雾', level: 'chapter' }]);
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('drafts-drawer-confirm-d1'));
    await waitFor(() =>
      expect(confirmDraftMock).toHaveBeenCalledWith('d1', { sourceOutlineId: 'o9' }),
    );
  });

  it('【R】多义命中（两章点同名包含）→ 宁缺勿误绑：不上传 + confirm {}', async () => {
    const draft: SeedDraft = { ...seedDraft1, summary: '第3章 渡口夜雾' };
    listDraftsMock.mockResolvedValue({ items: [draft], total: 1 });
    mockOutlineRoute([
      { id: 'oa', name: '渡口', level: 'chapter' },
      { id: 'ob', name: '渡口夜', level: 'chapter' },
    ]);
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('drafts-drawer-confirm-d1'));
    await waitFor(() => expect(confirmDraftMock).toHaveBeenCalledWith('d1', {}));
  });

  it('【R】已绑章草稿 → confirmDraft {} 且不拉 outline 树（D4 天然不触发）', async () => {
    const bound: SeedDraft = { ...seedDraft1, chapter_id: 'c1' };
    listDraftsMock.mockResolvedValue({ items: [bound], total: 1 });
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: 'c1' });
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('drafts-drawer-confirm-d1'));
    await waitFor(() => expect(confirmDraftMock).toHaveBeenCalledWith('d1', {}));
    expect(
      apiFetchMock.mock.calls.some((c) => String(c[0]).includes('/outlines')),
    ).toBe(false);
  });
});
