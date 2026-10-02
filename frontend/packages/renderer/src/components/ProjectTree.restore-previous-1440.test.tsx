/**
 * #1440 被覆盖章的「已有上一稿」徽标 + 恢复入口（book 第 2 位）契约测试（RED）。
 *
 * 背景：#1430 A2（PR #1433）已交付 `book run --force` 覆盖正文章前把旧稿落到
 *   `chapters.previous_content`，并提供恢复读口
 *   `POST /api/v1/chapters/{id}/restore-previous`（经 update_chapter 覆盖写
 *   ⇒ content ⇄ previous_content **互换**，双向可再切回）。GUI 侧此前零消费。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须实现（三处）：
 *
 * ① src/api/chapters.ts 新增：
 *    export async function restorePreviousContent(chapterId: string): Promise<ChapterRestoreDto>
 *      → POST /api/v1/chapters/${chapterId}/restore-previous（**无请求体**）
 *    （openapi.d.ts 已含该端点；后端 200 返回章 JSON，404 章不存在 / 409 无可恢复旧稿）
 *
 * ② src/stores/chapter.ts：
 *    - ChapterMeta 新增可选字段 `previous_content?: string | null`
 *    - 新增 action restorePreviousContent(chapterId: string): Promise<void>
 *        · 成功 → chapters 内该章合并响应（含互换后的 previous_content）；
 *          且 currentChapterId === chapterId 时同步 content = 响应 content（正文刷新）
 *        · 失败 → **向上抛**（组件负责展示错误，不静默吞掉）
 *
 * ③ src/components/ProjectTree.tsx 章节行（renderChapter）：
 *    - `previous_content` 非空白（`(v ?? '').trim() !== ''`）→
 *      渲染徽标 data-testid=`chapter-prev-badge-<id>`（常显，非 hover 区）
 *    - 同条件 → hover 操作区渲染恢复按钮 data-testid=`chapter-restore-<id>`
 *    - 点恢复按钮 → 打开共享 <ConfirmDialog/>（testidPrefix='chapter-restore'）：
 *        title   = t('write.chapter.restore.title')
 *        message = t('write.chapter.restore.message') ← 必须说明「双向切换（再恢复可切回）」
 *        confirmText = t('write.chapter.restore.confirm')
 *    - 取消 / Esc → 关闭且**不发**请求
 *    - 确认 → 调 store.restorePreviousContent(id) **恰好一次** → 成功后关框
 *    - 失败（如 ApiError 409「无可恢复的旧稿」）→ 关框 + 渲染错误行
 *      data-testid=`chapter-restore-error`（透传 ApiError.detail，明确提示而非静默失败）
 *
 * i18n（i18n/writing-ux.ts 成对新增，zh/en 键集合必须对称 —— i18n.contract.test.ts）：
 *    write.chapter.previousBadge / write.chapter.restore /
 *    write.chapter.restore.title / write.chapter.restore.message / write.chapter.restore.confirm
 *
 * 断言锚 testid / 关键词，不锁死整句文案（除「双向切换」这一要点）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ProjectTree } from './ProjectTree';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { apiFetch, ApiError } from '../api/client';
import type { ChapterMeta, Volume } from '../stores/chapter';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const RESTORE_PATH = '/api/v1/chapters/c1/restore-previous';

const volumes: Volume[] = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];

/** c1 有非空上一稿；c2 无 previous_content 键；c3 previous_content 为纯空白 */
const chapters: ChapterMeta[] = [
  {
    id: 'c1',
    title: '第1章 初见',
    volume_id: 'v1',
    order_index: 0,
    word_count: 2347,
    previous_content: '上一稿正文（被覆盖）',
  },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
  {
    id: 'c3',
    title: '第3章 独行',
    volume_id: null,
    order_index: 2,
    word_count: 120,
    previous_content: '   \n\t ',
  },
];

const project = {
  id: 'p1',
  name: '示例项目',
  tags: [],
  language: 'zh',
  target_words: 100000,
  config: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

/** 恢复成功响应（互换后：content = 旧稿，previous_content = 被替换的当前正文） */
const restoredResponse = {
  id: 'c1',
  project_id: 'p1',
  title: '第1章 初见',
  volume_id: 'v1',
  order_index: 0,
  word_count: 2347,
  content: '上一稿正文（被覆盖）',
  previous_content: '当前正文',
};

/** 恢复请求（POST /restore-previous）的调用次数 —— 其余 GET 不计入 */
function restoreCallCount(): number {
  return apiFetchMock.mock.calls.filter(
    ([path, init]) =>
      path === RESTORE_PATH && (init as { method?: string } | undefined)?.method === 'POST',
  ).length;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [project], currentProjectId: 'p1' });
  useChapterStore.setState({
    volumes,
    chapters: chapters.map((c) => ({ ...c })),
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
    pendingDrafts: [],
    approvalRequest: null,
    treeProjectId: 'p1',
  });
});

function renderTree() {
  render(
    <MemoryRouter>
      <ProjectTree />
    </MemoryRouter>,
  );
}

describe('ProjectTree #1440 — 「已有上一稿」徽标渲染', () => {
  it('previous_content 非空白 → 渲染徽标 + 恢复按钮', () => {
    renderTree();
    expect(screen.getByTestId('chapter-prev-badge-c1')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-restore-c1')).toBeInTheDocument();
  });

  it('【反例】previous_content 缺失 → 不渲染徽标 / 恢复按钮', () => {
    renderTree();
    expect(screen.queryByTestId('chapter-prev-badge-c2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chapter-restore-c2')).not.toBeInTheDocument();
  });

  it('【反例】previous_content 纯空白 → 不渲染徽标 / 恢复按钮', () => {
    renderTree();
    expect(screen.queryByTestId('chapter-prev-badge-c3')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chapter-restore-c3')).not.toBeInTheDocument();
  });
});

describe('ProjectTree #1440 — 恢复上一稿确认闭环', () => {
  it('点恢复 → 确认框出现且文案说明「双向切换（可再切回）」；未发请求', async () => {
    const user = userEvent.setup();
    renderTree();
    await user.click(screen.getByTestId('chapter-restore-c1'));

    const dialog = await screen.findByTestId('chapter-restore-dialog');
    expect(dialog).toHaveTextContent('双向');
    expect(screen.getByTestId('chapter-restore-ok')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-restore-cancel')).toBeInTheDocument();
    expect(restoreCallCount()).toBe(0);
  });

  it('取消 → 确认框关闭且不发恢复请求', async () => {
    const user = userEvent.setup();
    renderTree();
    await user.click(screen.getByTestId('chapter-restore-c1'));
    await user.click(await screen.findByTestId('chapter-restore-cancel'));

    await waitFor(() => {
      expect(screen.queryByTestId('chapter-restore-dialog')).not.toBeInTheDocument();
    });
    expect(restoreCallCount()).toBe(0);
  });

  it('确认 → POST /restore-previous 恰好一次，且 content ⇄ previous_content 互换（可再切回）', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === RESTORE_PATH && init?.method === 'POST') return restoredResponse;
      throw new Error(`unexpected: ${path} ${init?.method ?? 'GET'}`);
    });
    useChapterStore.setState({ currentChapterId: 'c1', content: '当前正文' });

    const user = userEvent.setup();
    renderTree();
    await user.click(screen.getByTestId('chapter-restore-c1'));
    await user.click(await screen.findByTestId('chapter-restore-ok'));

    await waitFor(() => {
      expect(restoreCallCount()).toBe(1);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(RESTORE_PATH, { method: 'POST' });

    // 章列表项互换：previous_content 变「当前正文」，正文变「旧稿」
    const c1 = useChapterStore.getState().chapters.find((c) => c.id === 'c1');
    expect(c1?.previous_content).toBe('当前正文');
    // 当前章正文同步刷新（编辑器正文与树徽标同源）
    expect(useChapterStore.getState().content).toBe('上一稿正文（被覆盖）');
    // 互换后 previous_content 仍非空 → 徽标仍在（可再切回）
    await waitFor(() => {
      expect(screen.getByTestId('chapter-prev-badge-c1')).toBeInTheDocument();
    });
  });

  it('409（无可恢复旧稿）→ 明确错误提示，不静默失败', async () => {
    apiFetchMock.mockImplementation(async () => {
      throw new ApiError(409, '无可恢复的旧稿');
    });

    const user = userEvent.setup();
    renderTree();
    await user.click(screen.getByTestId('chapter-restore-c1'));
    await user.click(await screen.findByTestId('chapter-restore-ok'));

    const err = await screen.findByTestId('chapter-restore-error');
    expect(err).toHaveTextContent('无可恢复的旧稿');
  });
});
