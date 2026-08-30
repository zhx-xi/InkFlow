/**
 * DraftApprovalPanel 契约测试（T1 草稿审批）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/DraftApprovalPanel.tsx 并匹配：
 *
 * export function DraftApprovalPanel(props: { projectId: string | null }): JSX.Element
 *
 * 结构 testid：
 * - draft-approval-panel（容器）
 * - 顶部标题「草稿审批」+ 按钮「清理孤儿」draft-prune（点击 → pruneOrphans() + 刷新列表）
 * - 列表项 draft-item-<index>；项内标题 draft-title-<index>（summary）、正文 draft-content-<index>（content）
 * - 操作按钮 draft-confirm-<index> / draft-reject-<index> / draft-edit-<index>
 * - 编辑态：draft-edit-input-<index> + draft-edit-save-<index>（保存 → updateDraft(id, content) + 刷新）
 * - 空态 draft-empty（含「暂无待审批草稿」）/ 加载 draft-loading / 失败 draft-error
 *
 * 行为契约：
 * - 挂载时 projectId 非空 → listDrafts(projectId)；projectId 为 null → 不发请求
 * - confirm/reject/update 成功后 → listDrafts(projectId) 重新加载（刷新闭环）
 *
 * i18n key（GREEN 补 zh.ts）：write.drafts.* —— 本测试以中文字面量断言，zh 语言包必须解析出同文案
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DraftApprovalPanel } from './DraftApprovalPanel';
import { listDrafts, confirmDraft, rejectDraft, updateDraft, pruneOrphans } from '../api/drafts';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/drafts', () => ({
  listDrafts: vi.fn(),
  confirmDraft: vi.fn(),
  rejectDraft: vi.fn(),
  updateDraft: vi.fn(),
  pruneOrphans: vi.fn(),
}));

const listDraftsMock = vi.mocked(listDrafts);
const confirmDraftMock = vi.mocked(confirmDraft);
const rejectDraftMock = vi.mocked(rejectDraft);
const updateDraftMock = vi.mocked(updateDraft);
const pruneOrphansMock = vi.mocked(pruneOrphans);

/** RED 期契约签名：与 api/drafts.ts 的 DraftDto 对齐（status='draft'，chapter_id=null） */
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
};

const seedDraft2: SeedDraft = {
  ...seedDraft1,
  id: 'd2',
  agent_run_id: 'r2',
  content: '第二份草稿正文',
  summary: '第4章 山中客栈',
};

beforeEach(() => {
  listDraftsMock.mockReset();
  confirmDraftMock.mockReset();
  rejectDraftMock.mockReset();
  updateDraftMock.mockReset();
  pruneOrphansMock.mockReset();
  // 中文文案断言锚：实现侧 t('write.drafts.*') 依赖 zh 语言包，显式播种 zh
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('DraftApprovalPanel — 挂载与列表渲染', () => {
  it('projectId 非空 → 挂载时 listDrafts(projectId) + 渲染标题/清理按钮/列表项', async () => {
    listDraftsMock.mockResolvedValue({ items: [seedDraft1, seedDraft2], total: 2 });
    render(<DraftApprovalPanel projectId="p1" />);
    expect(await screen.findByTestId('draft-approval-panel')).toBeInTheDocument();
    expect(screen.getByText('草稿审批')).toBeInTheDocument();
    expect(screen.getByTestId('draft-prune')).toHaveTextContent('清理孤儿');
    await waitFor(() => {
      expect(listDraftsMock).toHaveBeenCalledWith('p1');
    });
    expect(await screen.findByTestId('draft-item-0')).toBeInTheDocument();
    expect(screen.getByTestId('draft-item-1')).toBeInTheDocument();
    expect(screen.getByTestId('draft-title-0')).toHaveTextContent('第3章 渡口夜雾');
    expect(screen.getByTestId('draft-content-0')).toHaveTextContent('AI 生成的章节草稿正文');
    expect(screen.getByTestId('draft-title-1')).toHaveTextContent('第4章 山中客栈');
    // 每项三个操作按钮
    expect(screen.getByTestId('draft-confirm-0')).toBeInTheDocument();
    expect(screen.getByTestId('draft-reject-0')).toBeInTheDocument();
    expect(screen.getByTestId('draft-edit-0')).toBeInTheDocument();
    expect(screen.getByTestId('draft-confirm-1')).toBeInTheDocument();
    expect(screen.getByTestId('draft-reject-1')).toBeInTheDocument();
    expect(screen.getByTestId('draft-edit-1')).toBeInTheDocument();
  });

  it('projectId 为 null → 不发请求（守卫）', () => {
    render(<DraftApprovalPanel projectId={null} />);
    expect(listDraftsMock).not.toHaveBeenCalled();
  });

  it('空列表 → draft-empty 空态（含「暂无待审批草稿」）', async () => {
    listDraftsMock.mockResolvedValue({ items: [], total: 0 });
    render(<DraftApprovalPanel projectId="p1" />);
    const empty = await screen.findByTestId('draft-empty');
    expect(empty).toHaveTextContent('暂无待审批草稿');
  });

  it('加载中 → draft-loading 反馈', async () => {
    let resolveList!: (v: { items: SeedDraft[]; total: number }) => void;
    listDraftsMock.mockImplementation(
      () => new Promise<{ items: SeedDraft[]; total: number }>((res) => {
        resolveList = res;
      }),
    );
    render(<DraftApprovalPanel projectId="p1" />);
    expect(await screen.findByTestId('draft-loading')).toBeInTheDocument();
    // 收尾：resolve 避免残留 pending
    await act(async () => {
      resolveList({ items: [seedDraft1], total: 1 });
    });
    expect(await screen.findByTestId('draft-item-0')).toBeInTheDocument();
  });

  it('加载失败 → draft-error 反馈', async () => {
    listDraftsMock.mockRejectedValue(new Error('内核不可达'));
    render(<DraftApprovalPanel projectId="p1" />);
    expect(await screen.findByTestId('draft-error')).toBeInTheDocument();
  });
});

describe('DraftApprovalPanel — 操作闭环（成功后刷新列表）', () => {
  it('点 draft-confirm-0 → confirmDraft(d1) + 列表重新加载 + 已确认项消失', async () => {
    listDraftsMock
      .mockResolvedValueOnce({ items: [seedDraft1, seedDraft2], total: 2 })
      .mockResolvedValueOnce({ items: [seedDraft2], total: 1 });
    confirmDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null });
    const user = userEvent.setup();
    render(<DraftApprovalPanel projectId="p1" />);
    await screen.findByTestId('draft-item-1');
    await user.click(screen.getByTestId('draft-confirm-0'));
    await waitFor(() => {
      expect(confirmDraftMock).toHaveBeenCalledWith('d1');
    });
    // 刷新闭环：confirm 成功后重新加载列表（挂载 1 次 + 刷新 1 次）
    await waitFor(() => {
      expect(listDraftsMock).toHaveBeenCalledTimes(2);
    });
    // 已确认项从列表消失，其余项保留
    await waitFor(() => {
      expect(screen.queryByText('第3章 渡口夜雾')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('draft-title-0')).toHaveTextContent('第4章 山中客栈');
  });

  it('点 draft-reject-0 → rejectDraft(d1) + 列表重新加载 → 空态', async () => {
    listDraftsMock
      .mockResolvedValueOnce({ items: [seedDraft1], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 });
    rejectDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'rejected' });
    const user = userEvent.setup();
    render(<DraftApprovalPanel projectId="p1" />);
    await screen.findByTestId('draft-item-0');
    await user.click(screen.getByTestId('draft-reject-0'));
    await waitFor(() => {
      expect(rejectDraftMock).toHaveBeenCalledWith('d1');
    });
    await waitFor(() => {
      expect(listDraftsMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByTestId('draft-empty')).toBeInTheDocument();
  });

  it('点 draft-prune → pruneOrphans() + 列表重新加载', async () => {
    listDraftsMock
      .mockResolvedValueOnce({ items: [seedDraft1], total: 1 })
      .mockResolvedValueOnce({ items: [seedDraft1], total: 1 });
    pruneOrphansMock.mockResolvedValue({ deleted: 0 });
    const user = userEvent.setup();
    render(<DraftApprovalPanel projectId="p1" />);
    await screen.findByTestId('draft-item-0');
    await user.click(screen.getByTestId('draft-prune'));
    await waitFor(() => {
      expect(pruneOrphansMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(listDraftsMock).toHaveBeenCalledTimes(2);
    });
  });

  it('点 draft-edit-0 → 编辑框出现 → 保存 → updateDraft(d1, 新正文) + 列表重新加载', async () => {
    listDraftsMock
      .mockResolvedValueOnce({ items: [seedDraft1], total: 1 })
      .mockResolvedValueOnce({ items: [seedDraft1], total: 1 });
    updateDraftMock.mockResolvedValue({ draft_id: 'd1', status: 'draft', word_count: 120, learned: true });
    const user = userEvent.setup();
    render(<DraftApprovalPanel projectId="p1" />);
    await screen.findByTestId('draft-item-0');
    await user.click(screen.getByTestId('draft-edit-0'));
    const input = await screen.findByTestId('draft-edit-input-0');
    await user.clear(input);
    await user.type(input, '修改后的草稿正文');
    await user.click(screen.getByTestId('draft-edit-save-0'));
    await waitFor(() => {
      expect(updateDraftMock).toHaveBeenCalledWith('d1', '修改后的草稿正文');
    });
    await waitFor(() => {
      expect(listDraftsMock).toHaveBeenCalledTimes(2);
    });
  });
});

describe('DraftApprovalPanel — 草稿概要不撑满右栏（#749）', () => {
  it('长草稿默认截断为概要 + 点「展开看全文」显示全文', async () => {
    const longContent = '蜀山修仙宇宙设定：修炼体系/势力格局/核心法则。'.repeat(40);
    listDraftsMock.mockResolvedValue({ items: [{ ...seedDraft1, content: longContent }], total: 1 });
    const user = userEvent.setup();
    render(<DraftApprovalPanel projectId="p1" />);
    await screen.findByTestId('draft-item-0');
    // 默认概要：不显示全文（截断 + 省略号）
    expect(screen.getByTestId('draft-content-0').textContent).toContain('…');
    expect(screen.getByTestId('draft-content-0').textContent).not.toContain(longContent);
    // 展开看全文
    await user.click(screen.getByTestId('draft-expand-0'));
    expect(screen.getByTestId('draft-content-0')).toHaveTextContent(longContent);
  });
});
