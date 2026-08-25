/**
 * ChapterSummaryPanel 契约测试（T3 章节摘要）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/ChapterSummaryPanel.tsx 并匹配：
 *
 * export function ChapterSummaryPanel(props: { projectId: string | null; chapterId: string | null }): JSX.Element
 *
 * 结构 testid：
 * - chapter-summary-panel（容器：标题「章节摘要」+ 摘要正文 + 「刷新摘要」按钮）
 * - chapter-summary-title（标题，含「章节摘要」）
 * - chapter-summary-content（摘要正文，展示 summary 文本）
 * - chapter-summary-refresh（刷新按钮，点击 → refreshChapterSummary(chapterId) 并更新展示）
 * - chapter-summary-empty（空态：summary 为空串/null，含「暂无摘要」）
 * - chapter-summary-loading（加载中）/ chapter-summary-error（失败反馈）
 *
 * 行为契约：
 * - 挂载时 projectId && chapterId 非空 → getChapterSummary(chapterId)；任一为 null → 不发请求
 * - 点刷新 → refreshChapterSummary(chapterId) → 摘要内容更新为新值（刷新闭环）
 * - get/refresh 失败 → chapter-summary-error 反馈
 *
 * i18n key（GREEN 补 zh.ts）：write.summary.* —— 本测试以中文字面量断言，zh 语言包必须解析出同文案
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChapterSummaryPanel } from './ChapterSummaryPanel';
import { getChapterSummary, refreshChapterSummary } from '../api/context';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/context', () => ({
  getChapterSummary: vi.fn(),
  refreshChapterSummary: vi.fn(),
  // 保留 assembleContext mock 防误：不替换整个模块为未定义
  assembleContext: vi.fn(),
}));

const getChapterSummaryMock = vi.mocked(getChapterSummary);
const refreshChapterSummaryMock = vi.mocked(refreshChapterSummary);

/** 与 api/context.ts ChapterSummaryDto 对齐的种子数据 */
interface SeedSummary {
  summary: string;
  chapter_id: string;
}

const initialSummary: SeedSummary = { summary: '第3章：少年雨夜渡口收信…', chapter_id: 'c1' };
const refreshedSummary: SeedSummary = { summary: '第3章（刷新）：渡口灯明，少年启程…', chapter_id: 'c1' };

beforeEach(() => {
  getChapterSummaryMock.mockReset();
  refreshChapterSummaryMock.mockReset();
  // 中文文案断言锚：实现侧 t('write.summary.*') 依赖 zh 语言包，显式播种 zh
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('ChapterSummaryPanel — 挂载加载与渲染', () => {
  it('projectId/chapterId 非空 → 挂载时 getChapterSummary(chapterId) + 渲染标题/正文/刷新按钮', async () => {
    getChapterSummaryMock.mockResolvedValue(initialSummary);
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    expect(await screen.findByTestId('chapter-summary-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-summary-title')).toHaveTextContent('章节摘要');
    await waitFor(() => {
      expect(getChapterSummaryMock).toHaveBeenCalledWith('c1');
    });
    expect(await screen.findByTestId('chapter-summary-content')).toHaveTextContent(
      '第3章：少年雨夜渡口收信…',
    );
    expect(screen.getByTestId('chapter-summary-refresh')).toHaveTextContent('刷新摘要');
  });

  it('projectId 为 null → 不发请求 + 空态（守卫）', async () => {
    render(<ChapterSummaryPanel projectId={null} chapterId="c1" />);
    expect(await screen.findByTestId('chapter-summary-empty')).toHaveTextContent('暂无摘要');
    expect(getChapterSummaryMock).not.toHaveBeenCalled();
  });

  it('chapterId 为 null → 不发请求 + 空态（守卫）', async () => {
    render(<ChapterSummaryPanel projectId="p1" chapterId={null} />);
    expect(await screen.findByTestId('chapter-summary-empty')).toHaveTextContent('暂无摘要');
    expect(getChapterSummaryMock).not.toHaveBeenCalled();
  });
});

describe('ChapterSummaryPanel — 加载/空态/失败反馈', () => {
  it('请求进行中 → chapter-summary-loading；完成后切换为内容', async () => {
    let resolveLoad!: (value: SeedSummary) => void;
    getChapterSummaryMock.mockReturnValue(
      new Promise<SeedSummary>((resolve) => {
        resolveLoad = resolve;
      }),
    );
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    expect(await screen.findByTestId('chapter-summary-loading')).toBeInTheDocument();
    await act(async () => {
      resolveLoad(initialSummary);
    });
    expect(await screen.findByTestId('chapter-summary-content')).toHaveTextContent(
      '第3章：少年雨夜渡口收信…',
    );
    expect(screen.queryByTestId('chapter-summary-loading')).not.toBeInTheDocument();
  });

  it('summary 为空串 → chapter-summary-empty 空态（含「暂无摘要」）', async () => {
    getChapterSummaryMock.mockResolvedValue({ summary: '', chapter_id: 'c1' });
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    const empty = await screen.findByTestId('chapter-summary-empty');
    expect(empty).toHaveTextContent('暂无摘要');
    expect(screen.queryByTestId('chapter-summary-content')).not.toBeInTheDocument();
  });

  it('初始加载失败 → chapter-summary-error', async () => {
    getChapterSummaryMock.mockRejectedValue(new Error('boom'));
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    expect(await screen.findByTestId('chapter-summary-error')).toBeInTheDocument();
  });

  it('刷新失败 → chapter-summary-error 反馈', async () => {
    getChapterSummaryMock.mockResolvedValue(initialSummary);
    refreshChapterSummaryMock.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    await screen.findByTestId('chapter-summary-content');
    await user.click(screen.getByTestId('chapter-summary-refresh'));
    expect(await screen.findByTestId('chapter-summary-error')).toBeInTheDocument();
  });
});

describe('ChapterSummaryPanel — 刷新闭环', () => {
  it('点刷新 → refreshChapterSummary(chapterId) → 摘要内容更新为新值（旧文本消失）', async () => {
    getChapterSummaryMock.mockResolvedValue(initialSummary);
    refreshChapterSummaryMock.mockResolvedValue(refreshedSummary);
    const user = userEvent.setup();
    render(<ChapterSummaryPanel projectId="p1" chapterId="c1" />);
    expect(await screen.findByTestId('chapter-summary-content')).toHaveTextContent(
      '第3章：少年雨夜渡口收信…',
    );
    await user.click(screen.getByTestId('chapter-summary-refresh'));
    await waitFor(() => {
      expect(refreshChapterSummaryMock).toHaveBeenCalledWith('c1');
    });
    await waitFor(() => {
      expect(screen.getByTestId('chapter-summary-content')).toHaveTextContent(
        '第3章（刷新）：渡口灯明，少年启程…',
      );
    });
    expect(screen.queryByText('第3章：少年雨夜渡口收信…')).not.toBeInTheDocument();
  });
});
