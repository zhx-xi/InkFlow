/**
 * DraftApprovalDrawer 契约测试（#976 草稿审批弹层，Issue 976 RED）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/DraftApprovalDrawer.tsx 并匹配：
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
 * - 点确认钮 → confirmDraft(draftId) 成功 → onClose() 关框
 * - 确认失败 → drafts-drawer-error 展示
 * - Esc → onClose()
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

/** RED 期契约种子：与 api/drafts.ts DraftDto 对齐（status='draft'，chapter_id=null，volume_id 可选） */
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

describe('DraftApprovalDrawer — 确认 / 失败 / Esc 闭环', () => {
  it('点确认钮 → confirmDraft(draftId) 成功 → onClose 关框', async () => {
    const onClose = vi.fn();
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    const user = userEvent.setup();
    render(<DraftApprovalDrawer open onClose={onClose} />);
    await screen.findByTestId('drafts-drawer-item-d1');
    await user.click(screen.getByTestId('drafts-drawer-confirm-d1'));
    await waitFor(() => expect(confirmDraftMock).toHaveBeenCalledWith('d1'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('确认失败 → drafts-drawer-error 展示', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    confirmDraftMock.mockRejectedValue(new Error('草稿未绑定目标章节'));
    const user = userEvent.setup();
    render(<DraftApprovalDrawer open onClose={() => {}} />);
    await screen.findByTestId('drafts-drawer-item-d1');
    await user.click(screen.getByTestId('drafts-drawer-confirm-d1'));
    expect(await screen.findByTestId('drafts-drawer-error')).toBeInTheDocument();
  });

  it('Esc → onClose', async () => {
    const onClose = vi.fn();
    listDraftsMock.mockResolvedValue({ items: [seedDraft1], total: 1 });
    render(<DraftApprovalDrawer open onClose={onClose} />);
    await screen.findByTestId('drafts-drawer');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
