/**
 * PipelineStatus HITL 确认卡片契约（#343 拍板 3A：内联卡片，spec §5.6）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 PipelineStatus 必须匹配：
 * - awaiting_human + hitlPending 非空 → 渲染内联确认卡片：
 *   - data-testid="hitl-confirm-card"
 *   - 文案含 hitlPending.question（如「确认执行下一角色 reviser？」）
 *   - 「继续执行」按钮 data-testid="hitl-confirm-approve"（aria-label=write.hitl.approve）
 *   - 「拒绝并回退」按钮 data-testid="hitl-confirm-reject"（aria-label=write.hitl.reject）
 * - 点继续 → onConfirm(true)；点拒绝 → onConfirm(false)
 * - confirming=true → 两个按钮 disabled
 * - 非 awaiting_human → 不渲染卡片（既有四态渲染保持）
 */
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { PipelineStatus } from './PipelineStatus';

describe('PipelineStatus — HITL 确认卡片（#343）', () => {
  it('awaiting_human + hitlPending → 渲染内联卡片（question + 继续/拒绝按钮）', () => {
    render(
      <PipelineStatus
        status="awaiting_human"
        error={null}
        hitlPending={{ question: '确认执行下一角色 reviser？', role: 'reviser' }}
        onConfirm={() => {}}
        confirming={false}
      />,
    );
    const card = screen.getByTestId('hitl-confirm-card');
    expect(card).toHaveTextContent('确认执行下一角色 reviser？');
    expect(screen.getByTestId('hitl-confirm-approve')).toBeInTheDocument();
    expect(screen.getByTestId('hitl-confirm-reject')).toBeInTheDocument();
  });

  it('点「继续执行」→ onConfirm(true)', () => {
    const onConfirm = vi.fn();
    render(
      <PipelineStatus
        status="awaiting_human"
        error={null}
        hitlPending={{ question: '确认执行下一角色 reviser？', role: 'reviser' }}
        onConfirm={onConfirm}
        confirming={false}
      />,
    );
    fireEvent.click(screen.getByTestId('hitl-confirm-approve'));
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it('点「拒绝并回退」→ onConfirm(false)', () => {
    const onConfirm = vi.fn();
    render(
      <PipelineStatus
        status="awaiting_human"
        error={null}
        hitlPending={{ question: '确认执行下一角色 reviser？', role: 'reviser' }}
        onConfirm={onConfirm}
        confirming={false}
      />,
    );
    fireEvent.click(screen.getByTestId('hitl-confirm-reject'));
    expect(onConfirm).toHaveBeenCalledWith(false);
  });

  it('confirming=true → 确认按钮 disabled（防重复提交）', () => {
    render(
      <PipelineStatus
        status="awaiting_human"
        error={null}
        hitlPending={{ question: '确认执行下一角色 reviser？', role: 'reviser' }}
        onConfirm={() => {}}
        confirming={true}
      />,
    );
    expect(screen.getByTestId('hitl-confirm-approve')).toBeDisabled();
    expect(screen.getByTestId('hitl-confirm-reject')).toBeDisabled();
  });

  it('running 态不渲染确认卡片（既有四态保持）', () => {
    render(
      <PipelineStatus
        status="running"
        error={null}
        hitlPending={null}
        onConfirm={() => {}}
        confirming={false}
      />,
    );
    expect(screen.queryByTestId('hitl-confirm-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('执行中');
  });
});

/**
 * #585 拍板：idle 态不渲染 pipeline-status 容器（修复写作页底部残留 84px 空框）
 * 继承 #580（删除 idle 空态文案「AI 已就绪，开始创作」），进一步删除整个空容器：
 * - status=idle → 不渲染 data-testid="pipeline-status"（queryByTestId → null）
 * - running/success/failed/awaiting_human → 既有各态内容照常渲染（回归不破）
 * ⚠️ 本块首用例即 RED：当前实现 idle 仍渲染 min-h-[84px] 空容器 → queryByTestId 非 null
 */
describe('PipelineStatus — idle 空容器删除（#585）', () => {
  it('status=idle → 不渲染 pipeline-status 容器（无 84px 空框）', () => {
    render(<PipelineStatus status="idle" error={null} />);
    // RED：当前实现 idle 分支渲染空容器 → 断言 FAIL
    expect(screen.queryByTestId('pipeline-status')).not.toBeInTheDocument();
    // #580 守卫：idle 也不得出现空态文案
    expect(screen.queryByText('AI 已就绪，开始创作')).not.toBeInTheDocument();
  });

  it('status=running → 渲染 pipeline-status 含「执行中」', () => {
    render(<PipelineStatus status="running" error={null} />);
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('执行中');
  });

  it('status=success → 渲染「生成完成」', () => {
    render(<PipelineStatus status="success" error={null} />);
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
  });

  it('status=failed + error → 渲染「生成失败: {message}」', () => {
    render(<PipelineStatus status="failed" error="内核超时" />);
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成失败: 内核超时');
  });

  it('status=awaiting_human + hitlPending → 容器与确认卡片照常渲染', () => {
    render(
      <PipelineStatus
        status="awaiting_human"
        error={null}
        hitlPending={{ question: '确认执行下一角色 reviser？', role: 'reviser' }}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByTestId('pipeline-status')).toBeInTheDocument();
    expect(screen.getByTestId('hitl-confirm-card')).toBeInTheDocument();
  });
});
