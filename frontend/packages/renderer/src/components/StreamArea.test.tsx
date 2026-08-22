/**
 * StreamArea SSE 流式区契约（spec §4.5）。
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 StreamArea 必须匹配：
 * - idle + text 空 → 不渲染「AI 已就绪，开始创作」空态栏（#580 整栏删除）
 * - idle + text 非空 → 渲染流式正文
 * - generating → 「生成中」+ 字数 + 停止按钮（onStop）
 * - done + summary → 完成摘要「已生成 {words} 字 · 模型 {model} · 格式校验{valid}」
 * - formatValid=false → warnings + 重试按钮（onRetry）
 * - error → 「生成失败: {message}」；stopped → 「生成中断 · 已保留前文」
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StreamArea } from './StreamArea';

const baseProps = {
  wordCount: 0,
  summary: null,
  error: null,
  onStop: vi.fn(),
  onRetry: vi.fn(),
};

/**
 * #580 拍板：删除 idle 空态栏「AI 已就绪，开始创作」（写作页 3 处渲染之一：StreamArea idle 分支）
 */
describe('StreamArea — idle 空态栏删除（#580）', () => {
  it('status=idle 且 text 为空 → 不渲染「AI 已就绪，开始创作」空态文案', () => {
    render(<StreamArea {...baseProps} status="idle" text="" />);
    // RED：当前实现 idle+空 text 渲染 t('write.stream.idle') → 断言 FAIL
    expect(screen.getByTestId('stream-area')).not.toHaveTextContent('AI 已就绪，开始创作');
    expect(screen.queryByText('AI 已就绪，开始创作')).not.toBeInTheDocument();
  });

  it('守护：status=idle 且 text 非空 → 渲染正文内容（不显示空态栏）', () => {
    render(<StreamArea {...baseProps} status="idle" text="流式回填正文" />);
    expect(screen.getByTestId('stream-area')).toHaveTextContent('流式回填正文');
    expect(screen.queryByText('AI 已就绪，开始创作')).not.toBeInTheDocument();
  });
});

describe('StreamArea — 既有流式态保持', () => {
  it('守护：status=generating → 渲染「生成中」+ 字数 + 停止按钮', () => {
    render(<StreamArea {...baseProps} status="generating" text="" wordCount={123} />);
    expect(screen.getByTestId('stream-area')).toHaveTextContent('生成中');
    expect(screen.getByTestId('stream-area')).toHaveTextContent(/123/);
    expect(screen.getByRole('button', { name: '停止' })).toBeInTheDocument();
  });

  it('守护：status=done + summary → 渲染完成摘要（字数/模型/格式校验）', () => {
    render(
      <StreamArea
        {...baseProps}
        status="done"
        text="成品正文"
        summary={{ wordCount: 500, model: 'gpt-4o', formatValid: true }}
      />,
    );
    expect(screen.getByTestId('stream-area')).toHaveTextContent('已生成 500 字');
    expect(screen.getByTestId('stream-area')).toHaveTextContent('模型 gpt-4o');
    expect(screen.getByTestId('stream-area')).toHaveTextContent('格式校验通过');
  });
});
