/**
 * #1238 正文首行「后退两格」契约：编辑区渲染层不得携带 text-indent。
 *
 * 根因（浏览器实证，2026-09-17）：CSS `text-indent` 只作用于块容器的**第一条格式化行**。
 * textarea 的整个 value 是单一文本块 → `[text-indent:2em]`（computed 32px）只把
 * **全文首行**额外右移 2em；而内容层 `_indent_paragraphs()`（#1095）已给**每段**
 * 前置 U+3000×2（≈2em）→ 首行 = 4 字缩进、其余段 = 2 字缩进 = 用户所见
 * 「第一行比其他行首列后退两格」。用户「首行被其他元素包裹」的直觉不成立：
 * 无额外 DOM 元素，纯 CSS text-indent 视觉后退。
 *
 * 契约：
 * - 首行缩进职责由内容层（U+3000×2，#1095）唯一承担；
 * - 渲染层 textarea 不得再叠加任何 text-indent（任意值类 / indent-* utility / 内联样式）；
 * - textarea 保持纯文本容器（无子元素包裹），防未来换成富文本包裹结构回归本缺陷。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChapterEditor } from './ChapterEditor';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';

// 真实落库形态（#1238 字节级取证）：每段 U+3000×2 前导 + \n\n 段间
const REAL_CONTENT =
  '\u3000\u3000天还没亮，檐下那只破铃先响了一声。\n\n' +
  '\u3000\u3000为真子推门进来，带来一身寒气。\n\n' +
  '\u3000\u3000叶知秋起初以为那是块砖。';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    chapters: [{ id: 'c1', title: '第2章', volume_id: 'v1', order_index: 1, word_count: 2810 }],
    currentChapterId: 'c1',
    content: REAL_CONTENT,
  });
});

describe('ChapterEditor — #1238 首行缩进唯一来源=内容层，渲染层零 text-indent', () => {
  it('textarea 类名不得携带任何 text-indent 形态（任意值类 / indent utility）', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const editor = screen.getByTestId('chapter-editor');
    // RED 主失败点：现状 className 含 `[text-indent:2em]` → 首行叠加缩进
    expect(editor.className).not.toMatch(/text-indent/);
    expect(editor.className).not.toMatch(/(^|\s)indent-/);
  });

  it('textarea 无内联 text-indent 样式', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.style.textIndent).toBe('');
  });

  it('textarea 保持纯文本容器：无子元素包裹（防富文本包裹结构回归首行异常）', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const editor = screen.getByTestId('chapter-editor');
    expect(editor.children.length).toBe(0);
    // 内容原样呈现（缩进字符来自数据层，非 DOM 注入）
    expect(editor.textContent ?? (editor as HTMLTextAreaElement).value).toContain(
      '\u3000\u3000天还没亮',
    );
  });

  it('字号/行高保持 spec §5.2.4 token（16px / 1.85），本修复不动排版基线', () => {
    render(<ChapterEditor onEditorKeyDown={vi.fn()} onContentChange={vi.fn()} />);
    const editor = screen.getByTestId('chapter-editor');
    expect(editor.className).toMatch(/(^|\s)text-\[16px\](\s|$)/);
    expect(editor.className).toMatch(/(^|\s)leading-\[1\.85\](\s|$)/);
  });
});
