/**
 * WindowControls 契约（#106 自绘窗口控制按钮；#98 api-ready 补订）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 components/WindowControls.tsx 必须匹配：
 *
 * - 三个按钮：header-wc-min（aria-label Minimize）/ header-wc-max（isMaximized 时
 *   aria-label Restore + Copy 图标，否则 Maximize + Square）/ header-wc-close（Close）
 * - 点击时读取 window.INKFLOW_API?.windowControls 调用 minimize()/toggleMaximize()/close()
 *   （点击时读取非快照）——无 INKFLOW_API（浏览器 dev）可选链 no-op，按钮不崩
 * - useEffect 订阅 onMaximizedChange(setIsMaximized)；preload 注入晚于挂载时监听
 *   'inkflow:api-ready' 补订（重复事件先取消旧订阅防重复）；cleanup 移除监听 + 取消订阅
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WindowControls } from './WindowControls';

/** 窗口控制 mock：minimize/toggleMaximize/close 三个 IPC 通道 + onMaximizedChange 订阅（返回取消函数） */
function createWindowControlsMock() {
  const unsubscribe = vi.fn();
  const onMaximizedChange = vi.fn<(callback: (maximized: boolean) => void) => () => void>(
    () => unsubscribe
  );
  return {
    minimize: vi.fn(),
    toggleMaximize: vi.fn(),
    close: vi.fn(),
    onMaximizedChange,
    unsubscribe,
  };
}

function setInjected(api: unknown): void {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: api,
  });
}

beforeEach(() => {
  // 清掉可能残留的 INKFLOW_API（ensureApiReady.test.ts 先例）
  setInjected(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WindowControls — 渲染与点击（#106 自绘窗口控制）', () => {
  it('渲染三个按钮（testid 契约 + aria-label）', () => {
    render(<WindowControls />);
    expect(screen.getByTestId('header-wc-min')).toHaveAttribute('aria-label', 'Minimize');
    // 初始非最大化：Maximize（Square 图标）
    expect(screen.getByTestId('header-wc-max')).toHaveAttribute('aria-label', 'Maximize');
    expect(screen.getByTestId('header-wc-close')).toHaveAttribute('aria-label', 'Close');
  });

  it('点击 min → window.INKFLOW_API.windowControls.minimize 被调用', async () => {
    const wc = createWindowControlsMock();
    setInjected({ windowControls: wc });
    const user = userEvent.setup();
    render(<WindowControls />);
    await user.click(screen.getByTestId('header-wc-min'));
    expect(wc.minimize).toHaveBeenCalledTimes(1);
  });

  it('点击 max → toggleMaximize 被调用', async () => {
    const wc = createWindowControlsMock();
    setInjected({ windowControls: wc });
    const user = userEvent.setup();
    render(<WindowControls />);
    await user.click(screen.getByTestId('header-wc-max'));
    expect(wc.toggleMaximize).toHaveBeenCalledTimes(1);
  });

  it('点击 close → close 被调用', async () => {
    const wc = createWindowControlsMock();
    setInjected({ windowControls: wc });
    const user = userEvent.setup();
    render(<WindowControls />);
    await user.click(screen.getByTestId('header-wc-close'));
    expect(wc.close).toHaveBeenCalledTimes(1);
  });

  it('无 INKFLOW_API（浏览器 dev）时点击 no-op，不崩溃', async () => {
    setInjected(undefined);
    const user = userEvent.setup();
    render(<WindowControls />);
    await user.click(screen.getByTestId('header-wc-min'));
    await user.click(screen.getByTestId('header-wc-max'));
    await user.click(screen.getByTestId('header-wc-close'));
    // 可选链吞掉调用，按钮仍可用
    expect(screen.getByTestId('header-wc-close')).toBeInTheDocument();
  });
});

describe('WindowControls — 最大化订阅 / api-ready 补订 / cleanup（#98/#106）', () => {
  it('订阅 onMaximizedChange：回调(true) → Restore，回调(false) → Maximize', () => {
    const wc = createWindowControlsMock();
    setInjected({ windowControls: wc });
    render(<WindowControls />);
    // 挂载即订阅（回调 = setIsMaximized）
    expect(wc.onMaximizedChange).toHaveBeenCalledTimes(1);
    const notify = wc.onMaximizedChange.mock.calls[0][0];

    act(() => {
      notify(true);
    });
    expect(screen.getByTestId('header-wc-max')).toHaveAttribute('aria-label', 'Restore');

    act(() => {
      notify(false);
    });
    expect(screen.getByTestId('header-wc-max')).toHaveAttribute('aria-label', 'Maximize');
  });

  it('初始无 API 跳过订阅 → dispatch inkflow:api-ready 补订成功（重复事件先取消旧订阅）', () => {
    // beforeEach 已清 INKFLOW_API → 挂载时订阅被跳过
    const wc = createWindowControlsMock();
    render(<WindowControls />);
    expect(wc.onMaximizedChange).not.toHaveBeenCalled();

    // preload 注入晚于挂载 → api-ready 补订
    setInjected({ windowControls: wc });
    act(() => {
      window.dispatchEvent(new Event('inkflow:api-ready'));
    });
    expect(wc.onMaximizedChange).toHaveBeenCalledTimes(1);

    // 补订后订阅生效：回调驱动 aria-label 切换
    const notify = wc.onMaximizedChange.mock.calls[0][0];
    act(() => {
      notify(true);
    });
    expect(screen.getByTestId('header-wc-max')).toHaveAttribute('aria-label', 'Restore');

    // 重复 api-ready：先取消旧订阅再补订（防重复订阅）
    act(() => {
      window.dispatchEvent(new Event('inkflow:api-ready'));
    });
    expect(wc.onMaximizedChange).toHaveBeenCalledTimes(2);
    expect(wc.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('cleanup：移除 inkflow:api-ready 监听 + 调用订阅取消函数', () => {
    const wc = createWindowControlsMock();
    setInjected({ windowControls: wc });
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const { unmount } = render(<WindowControls />);
    expect(addSpy).toHaveBeenCalledWith('inkflow:api-ready', expect.any(Function));

    unmount();
    expect(removeSpy).toHaveBeenCalledWith('inkflow:api-ready', expect.any(Function));
    expect(wc.unsubscribe).toHaveBeenCalledTimes(1);
  });
});
