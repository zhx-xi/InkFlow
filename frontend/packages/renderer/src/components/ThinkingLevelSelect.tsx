/**
 * F59-M3 (#964)：chat 页思考级别选择器（spec §3.4 / §8.1 命名）。
 *
 * - 原生 select，testid：chat-reasoning-effort + chat-reasoning-effort-option-<value>（7 个）。
 * - 选项顺序 = REASONING_EFFORTS（none → default）；文案走 i18n reasoning.level.*。
 * - disabled + disabledTooltip → 外层 span（chat-reasoning-effort-tooltip，title=提示文案）
 *   包裹禁用 select，控件整体禁用并展示 tooltip；不禁用时无该元素。
 * - 样式对齐既有控件（rounded-md border-line bg-surface 等）。
 */
import { useI18n } from '../i18n/useI18n';
import { REASONING_EFFORTS } from '../lib/reasoningEffort';
import { cn } from '../lib/cn';

export interface ThinkingLevelSelectProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  disabledTooltip?: string;
  className?: string;
}

export function ThinkingLevelSelect({
  value,
  onChange,
  disabled,
  disabledTooltip,
  className,
}: ThinkingLevelSelectProps) {
  const { t } = useI18n();
  const select = (
    <select
      data-testid="chat-reasoning-effort"
      aria-label={t('reasoning.chat.label')}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={cn(
        'rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-2',
        disabled && 'cursor-not-allowed opacity-60',
        className,
      )}
    >
      {REASONING_EFFORTS.map((v) => (
        <option key={v} value={v} data-testid={`chat-reasoning-effort-option-${v}`}>
          {t(`reasoning.level.${v}`)}
        </option>
      ))}
    </select>
  );
  if (disabled && disabledTooltip) {
    return (
      <span data-testid="chat-reasoning-effort-tooltip" title={disabledTooltip}>
        {disabledTooltip}
        {select}
      </span>
    );
  }
  return select;
}
