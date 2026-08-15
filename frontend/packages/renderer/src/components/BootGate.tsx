/** 启动门控封面（Issue #384 层 1）：booting 加载态 / failed 错误+重试；AppLayout 在 !booted 时渲染 */
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';
import { useKernelStore } from '../stores/kernel';
import type { ThemeName } from '../theme';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';

const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

export function BootGate() {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const status = useKernelStore((s) => s.status);
  const retry = useKernelStore((s) => s.retry);
  return (
    <div data-testid="boot-gate" className="flex h-dvh items-center justify-center bg-surface">
      <div className="flex flex-col items-center gap-4">
        <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-10 w-10" />
        {status === 'booting' ? (
          <>
            <div
              data-testid="boot-gate-spinner"
              className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-ink"
            />
            <span className="text-[13px] text-ink-2">{t('gate.booting')}</span>
          </>
        ) : (
          <>
            <span className="text-[13px] text-ink-2">{t('gate.failed')}</span>
            <button
              type="button"
              onClick={() => retry()}
              className="rounded-md border border-line bg-surface-2 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-3"
            >
              {t('lib.retry')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
