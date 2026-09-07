/**
 * #998 写作编辑区双滚动条契约：滚动容器唯一。
 *
 * 根因：ChapterEditor 外层容器 `overflow-y-auto` 与 textarea（h-full 恒等容器高、
 * 自身走原生滚动）语义重叠 → 外层渲染一条顶满全高、无实际可滚量的死滚动条。
 *
 * 契约（方案 A，issue 998 已拍板）：
 * - 外层容器只保留布局语义（min-h-0 flex-1），**不得**携带任何 overflow 滚动类；
 * - textarea 显式声明 h-full + overflow-y-auto，是编辑区唯一滚动容器。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChapterEditor } from './ChapterEditor';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  // 种子：当前章 + 超长正文（复现场景：≥1000 字触发 textarea 原生滚动）
  useChapterStore.setState({
    chapters: [{ id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 3173 }],
    currentChapterId: 'c1',
    content: '已有正文第一段。\n'.repeat(100),
  });
});

describe('ChapterEditor — #998 编辑区滚动容器唯一（双滚动条修复）', () => {
  it('textarea 是滚动容器：显式声明 h-full + overflow-y-auto（原生滚动条出现）', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const editor = screen.getByTestId('chapter-editor');
    expect(editor.className).toMatch(/(^|\s)h-full(\s|$)/);
    expect(editor.className).toMatch(/(^|\s)overflow-y-auto(\s|$)/);
  });

  it('外层容器无滚动语义：保留 min-h-0 flex-1，但不得出现任何 overflow 滚动类', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const wrapper = screen.getByTestId('chapter-editor').parentElement as HTMLElement;
    expect(wrapper.className).toMatch(/(^|\s)min-h-0(\s|$)/);
    expect(wrapper.className).toMatch(/(^|\s)flex-1(\s|$)/);
    // overflow / overflow-x / overflow-y × auto|scroll 一律禁止（死滚动条来源）
    expect(wrapper.className).not.toMatch(/(^|\s)overflow(-[xy])?-(auto|scroll)(\s|$)/);
  });
});
