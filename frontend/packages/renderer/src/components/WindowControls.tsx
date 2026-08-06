/**
 * 自绘窗口控制按钮（#106 用户拍板：放弃官方 titleBarOverlay，其颜色联动不可靠）。
 *
 * - 三个按钮：最小化（Minus）/ 最大化（Square）/ 关闭（X），lucide-react 图标；
 * - 颜色/大小完全用 CSS 变量（text-ink-2 / surface-3 / --err / --bg），
 *   随主题 + 背景变体（data-theme / data-bg）自然联动；
 * - 必须 [-webkit-app-region:no-drag]，否则点击会被顶栏 drag 区域吞掉；
 * - 无 INKFLOW_API（浏览器 dev）时可选链吞掉调用，按钮 no-op 但可见。
 */
import { Minus, Square, X } from 'lucide-react';
import { cn } from '../lib/cn';

/** 按钮通用尺寸/配色：宽 46px、顶栏 h-12 内撑满高度、flex 居中 */
const BASE_BUTTON_CLASS =
  'flex h-full w-[46px] items-center justify-center text-ink-2 transition-colors [-webkit-app-region:no-drag]';

export function WindowControls() {
  const controls = window.INKFLOW_API?.windowControls;
  return (
    <div className="flex h-full items-stretch">
      <button
        type="button"
        data-testid="header-wc-min"
        aria-label="Minimize"
        className={cn(BASE_BUTTON_CLASS, 'hover:bg-surface-3 hover:text-ink')}
        onClick={() => controls?.minimize()}
      >
        <Minus className="size-4" strokeWidth={1.5} />
      </button>
      <button
        type="button"
        data-testid="header-wc-max"
        aria-label="Maximize"
        className={cn(BASE_BUTTON_CLASS, 'hover:bg-surface-3 hover:text-ink')}
        onClick={() => controls?.toggleMaximize()}
      >
        <Square className="size-3.5" strokeWidth={1.5} />
      </button>
      <button
        type="button"
        data-testid="header-wc-close"
        aria-label="Close"
        className={cn(
          BASE_BUTTON_CLASS,
          'hover:bg-[color:var(--err)] hover:text-[color:var(--bg)]'
        )}
        onClick={() => controls?.close()}
      >
        <X className="size-4" strokeWidth={1.5} />
      </button>
    </div>
  );
}
