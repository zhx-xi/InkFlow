/**
 * #932 调用链视图（GREEN 拆分组件，900 行护栏；logs-page-ux-932.test.tsx S4）。
 *
 * 契约要点：
 * - 面板 log-chain-view 由父级独立查询 {trace_id, limit: 200} 喂入（本组件零查询）；
 * - log-chain-node 按 timestamp 升序渲染（API 降序返回 → 组件内排序）；
 * - 节点含简式 UTC 时钟（formatClock 'HH:mm:ss'）+ 可选 log-chain-node-duration /
 *   log-chain-node-error-code（无 error_code 不渲染）；
 * - 节点可展开 LogDetail（链视图内隐藏只看此链/调用链按钮，防嵌套递归）；
 * - log-chain-back-btn 返回主列表。
 */
import { useMemo, useState } from 'react';
import { ArrowLeft, Loader2 } from 'lucide-react';
import type { LogRecordDto } from '../api/logs';
import { useI18n } from '../i18n/useI18n';
import { formatClock, formatDuration, levelBadgeCls } from '../lib/log-format';
import { LogDetail } from './LogDetail';

interface LogChainViewProps {
  records: LogRecordDto[];
  /** 节点 message（父级复用主列表 message 四层回退 + 插值管线） */
  messageFor: (record: LogRecordDto) => string;
  loading: boolean;
  error: string | null;
  onBack: () => void;
}

/** 单个链节点：点击/Enter/Space 展开内嵌 LogDetail。 */
function ChainNode({ record, message }: { record: LogRecordDto; message: string }) {
  const [open, setOpen] = useState(false);
  const toggle = () => setOpen((value) => !value);
  return (
    <li
      data-testid="log-chain-node"
      tabIndex={0}
      aria-expanded={open}
      onClick={toggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      }}
      className="cursor-pointer rounded-lg border border-line bg-surface p-4 transition-colors hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="w-[76px] shrink-0 font-mono text-[12px] text-ink-3">{formatClock(record.timestamp)}</span>
        <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{message}</span>
        {record.duration_ms != null && (
          <span data-testid="log-chain-node-duration" className="font-mono text-[12px] text-ink-2">
            {formatDuration(record.duration_ms)}
          </span>
        )}
        {record.error_code && (
          <span
            data-testid="log-chain-node-error-code"
            className={levelBadgeCls(record.level)}
          >
            {record.error_code}
          </span>
        )}
      </div>
      {open && (
        <div className="mt-3 border-t border-line pt-3">
          <LogDetail record={record} message={message} />
        </div>
      )}
    </li>
  );
}

export function LogChainView({ records, messageFor, loading, error, onBack }: LogChainViewProps) {
  const { t } = useI18n();
  const sorted = useMemo(
    () =>
      [...records].sort(
        (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp),
      ),
    [records],
  );
  return (
    <section data-testid="log-chain-view" className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-[17px] font-semibold text-ink">{t('logs.chain.view')}</h2>
        <button
          type="button"
          data-testid="log-chain-back-btn"
          onClick={onBack}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-[13px] text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t('logs.chain.back')}
        </button>
      </div>
      {loading && (
        <div
          data-testid="log-chain-loading"
          className="mt-4 flex items-center justify-center gap-3 rounded-lg border border-line bg-surface px-4 py-10 text-[13px] text-ink-2"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('logs.loading')}
        </div>
      )}
      {!loading && error && (
        <div
          data-testid="log-chain-error"
          className="mt-4 rounded-lg border border-err/40 bg-err/10 px-4 py-10 text-center text-[13px] text-err"
        >
          {t('logs.error')}：{error}
        </div>
      )}
      {!loading && !error && sorted.length === 0 && (
        <div
          data-testid="log-chain-empty"
          className="mt-4 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
        >
          <p className="font-serif text-[15px] font-semibold text-ink">{t('logs.empty')}</p>
        </div>
      )}
      {!loading && !error && sorted.length > 0 && (
        <ul className="mt-4 space-y-2">
          {sorted.map((rec, index) => (
            <ChainNode
              key={`${index}-${rec.timestamp}-${rec.event}`}
              record={rec}
              message={messageFor(rec)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
