/**
 * #932 日志详情面板（行展开 / 调用链节点共用；GREEN 拆分组件，900 行护栏）。
 *
 * 契约要点（logs-page-ux-932.test.tsx S2-S4）：
 * - log-detail-timestamp = 原始 ISO 串直出（含时区偏移，勿格式化）；
 * - params 用 JSON.stringify(params, null, 2) 进 <pre>（非 k=v 摘要）；
 * - duration 复用 #930 formatDuration；stack 仅 ERROR 展示；
 * - log-copy-trace-btn / log-copy-correlation-btn → navigator.clipboard.writeText
 *   （防御式：jsdom 无 clipboard 静默；aria-label 含「复制」）；
 * - log-chain-only-btn：trace 优先，缺 trace 用 correlation_id；两者皆空 disabled + title；
 * - log-chain-view-btn：查看完整调用链（需要 trace_id）。
 *
 * 详情内所有交互按钮 stopPropagation：不得冒泡触发行级展开/收起。
 */
import { Copy } from 'lucide-react';
import type { ReactNode } from 'react';
import type { LogRecordDto } from '../api/logs';
import { useI18n } from '../i18n/useI18n';
import { formatDuration } from '../lib/log-format';
import { useToastStore } from '../stores/toast';

interface LogDetailProps {
  record: LogRecordDto;
  /** 已插值 message（父级完成 message_key 四层回退 + {key} 插值） */
  message: string;
  /** 只看此链（父级注入；缺省 = 链视图节点详情，隐藏链操作防嵌套） */
  onChainOnly?: (record: LogRecordDto) => void;
  /** 查看完整调用链（父级注入） */
  onChainView?: (record: LogRecordDto) => void;
}

/** 详情字段行：左侧 caption，右侧内容（full 跨两列放 pre） */
function Field({ label, children, full = false }: { label: string; children: ReactNode; full?: boolean }) {
  return (
    <div className={full ? 'md:col-span-2' : undefined}>
      <div className="flex flex-col gap-1">
        <span className="text-[12px] text-ink-3">{label}</span>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

const BUTTON_CLS =
  'inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2.5 py-1 text-[12px] ' +
  'text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50';

export function LogDetail({ record, message, onChainOnly, onChainView }: LogDetailProps) {
  const { t } = useI18n();
  const canChainOnly = Boolean(record.trace_id) || Boolean(record.correlation_id);
  const hasTrace = Boolean(record.trace_id);
  const showChainActions = onChainOnly != null && onChainView != null;

  /** 复制：镜像 McpSettingsCard/ChatPanel 先例，clipboard 缺失/拒绝静默或 err toast。 */
  const copyText = async (text: string) => {
    try {
      await navigator.clipboard?.writeText(text);
      useToastStore.getState().pushToast('ok', t('logs.copied'));
    } catch {
      useToastStore.getState().pushToast('err', t('logs.copyFailed'));
    }
  };

  return (
    <div data-testid="log-detail" className="rounded-lg border border-line/70 bg-surface-2/50 p-4">
      <div className="grid grid-cols-1 gap-x-5 gap-y-2.5 md:grid-cols-[150px_minmax(0,1fr)]">
        <Field label={t('logs.detail.timestamp')}>
          <span data-testid="log-detail-timestamp" className="break-all font-mono text-[12px] text-ink">
            {record.timestamp}
          </span>
        </Field>
        <Field label={t('logs.detail.messageKey')}>
          <span data-testid="log-detail-message-key" className="break-all font-mono text-[12px] text-ink">
            {record.message_key}
          </span>
        </Field>
        <Field label={t('logs.detail.message')}>
          <span data-testid="log-detail-message" className="text-[13px] text-ink">
            {message}
          </span>
        </Field>
        <Field label={t('logs.detail.params')} full>
          <pre
            data-testid="log-detail-params"
            className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md border border-line bg-surface p-3 font-mono text-[11px] leading-relaxed text-ink-2"
          >
            {JSON.stringify(record.params, null, 2)}
          </pre>
        </Field>
        {record.error_code && (
          <Field label={t('logs.detail.errorCode')}>
            <span data-testid="log-detail-error-code" className="rounded bg-err/10 px-1.5 py-0.5 text-[12px] font-medium text-err">
              {record.error_code}
            </span>
          </Field>
        )}
        {record.trace_id && (
          <Field label={t('logs.detail.trace')}>
            <span className="flex flex-wrap items-center gap-2">
              <span data-testid="log-detail-trace" className="break-all font-mono text-[12px] text-ink">
                {record.trace_id}
              </span>
              <button
                type="button"
                data-testid="log-copy-trace-btn"
                aria-label={t('logs.detail.copyTrace')}
                title={t('logs.detail.copyTrace')}
                className={BUTTON_CLS}
                onClick={(e) => {
                  e.stopPropagation();
                  void copyText(record.trace_id ?? '');
                }}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </span>
          </Field>
        )}
        {record.correlation_id && (
          <Field label={t('logs.detail.correlation')}>
            <span className="flex flex-wrap items-center gap-2">
              <span data-testid="log-detail-correlation" className="break-all font-mono text-[12px] text-ink">
                {record.correlation_id}
              </span>
              <button
                type="button"
                data-testid="log-copy-correlation-btn"
                aria-label={t('logs.detail.copyCorrelation')}
                title={t('logs.detail.copyCorrelation')}
                className={BUTTON_CLS}
                onClick={(e) => {
                  e.stopPropagation();
                  void copyText(record.correlation_id ?? '');
                }}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </span>
          </Field>
        )}
        {record.duration_ms != null && (
          <Field label={t('logs.detail.duration')}>
            <span data-testid="log-detail-duration" className="font-mono text-[12px] text-ink">
              {formatDuration(record.duration_ms)}
            </span>
          </Field>
        )}
      </div>
      {record.level === 'ERROR' && record.stack && (
        <div className="mt-3 flex flex-col gap-1">
          <span className="text-[12px] text-ink-3">{t('logs.detail.stack')}</span>
          <pre
            data-testid="log-detail-stack"
            className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md border border-err/20 bg-err/5 p-3 font-mono text-[11px] leading-relaxed text-ink-2"
          >
            {record.stack}
          </pre>
        </div>
      )}
      {showChainActions && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
          <button
            type="button"
            data-testid="log-chain-only-btn"
            disabled={!canChainOnly}
            title={canChainOnly ? undefined : t('logs.chain.onlyDisabled')}
            className={BUTTON_CLS}
            onClick={(e) => {
              e.stopPropagation();
              onChainOnly?.(record);
            }}
          >
            {t('logs.chain.only')}
          </button>
          <button
            type="button"
            data-testid="log-chain-view-btn"
            disabled={!hasTrace}
            title={hasTrace ? undefined : t('logs.chain.viewDisabled')}
            className={BUTTON_CLS}
            onClick={(e) => {
              e.stopPropagation();
              onChainView?.(record);
            }}
          >
            {t('logs.chain.view')}
          </button>
        </div>
      )}
    </div>
  );
}
