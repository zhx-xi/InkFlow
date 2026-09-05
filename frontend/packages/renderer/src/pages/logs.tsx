/** #496 统一日志页（contract-496 §6）：分类 tab / level / project / 筛选 / 分页 + message 三层回退 + 过期响应防护。 */
import { useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw, Search } from 'lucide-react';
import { fetchLogMessages, fetchLogs, type LogRecordDto, type LogsResponseDto } from '../api/logs';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { cn } from '../lib/cn';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

type TabKey = 'all' | 'kernel' | 'gui' | 'ai';
type LevelKey = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface QueryState {
  tab: TabKey;
  level: LevelKey;
  projectId: string | null; // null = 全部项目
  q: string;
  correlationId: string;
  from: string;
  to: string;
  page: number;
}

const PAGE_LIMIT = 50;
const ALL_PROJECTS = 'all';
/** level 选择 → API 参数（DEBUG = 不传 = 全量含 DEBUG；§6.2） */
const LEVEL_PARAM: Record<LevelKey, string | undefined> = {
  DEBUG: undefined,
  INFO: 'INFO,WARN,ERROR',
  WARN: 'WARN,ERROR',
  ERROR: 'ERROR',
};
/** 分类 tab → caller_type 逗号多值（all = 不传；§6.2） */
const TAB_CALLER: Record<TabKey, string | undefined> = {
  all: undefined,
  kernel: 'api,agent,tool,cli,mcp',
  gui: 'frontend',
  ai: 'llm',
};
const TABS: Array<{ key: TabKey; labelKey: string }> = [
  { key: 'all', labelKey: 'logs.tab.all' },
  { key: 'kernel', labelKey: 'logs.tab.kernel' },
  { key: 'gui', labelKey: 'logs.tab.gui' },
  { key: 'ai', labelKey: 'logs.tab.ai' },
];
const LEVELS: LevelKey[] = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
/** caller_type → 分类标签 key（未知类型直出原值） */
const CALLER_LABEL_KEY: Record<string, string> = {
  api: 'logs.caller.kernel',
  agent: 'logs.caller.kernel',
  tool: 'logs.caller.kernel',
  cli: 'logs.caller.kernel',
  mcp: 'logs.caller.kernel',
  frontend: 'logs.caller.gui',
  llm: 'logs.caller.ai',
};
const DEFAULT_QUERY: QueryState = {
  tab: 'all',
  level: 'INFO',
  projectId: null,
  q: '',
  correlationId: '',
  from: '',
  to: '',
  page: 0,
};

/** {key} 占位符插值（与 useI18n 同款规则；缺参保留占位符） */
function interpolateTemplate(template: string, params?: Record<string, unknown>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : `{${key}}`,
  );
}

/** timestamp 展示：ISO → 'YYYY-MM-DD HH:mm:ss'；解析失败原样直出 */
function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toISOString().slice(0, 19).replace('T', ' ');
}

/** 时长格式化：#930 卡片可读性 —— <1s 两位小数 ms、<60s 一位小数 s、≥60s m+s */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(2)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
}

function levelBadgeCls(level: string): string {
  if (level === 'ERROR') return 'bg-err/10 text-err';
  if (level === 'WARN') return 'bg-warn/10 text-warn';
  if (level === 'INFO') return 'bg-ok/10 text-ok';
  return 'bg-surface-3 text-ink-2';
}

function buildParams(query: QueryState): Parameters<typeof fetchLogs>[0] {
  const params: Parameters<typeof fetchLogs>[0] = { limit: PAGE_LIMIT, page: query.page };
  const level = LEVEL_PARAM[query.level];
  const caller = TAB_CALLER[query.tab];
  if (level) params.level = level;
  if (caller) params.caller_type = caller;
  if (query.projectId) params.project_id = query.projectId;
  if (query.q) params.q = query.q;
  if (query.correlationId) params.correlation_id = query.correlationId;
  if (query.from) params.from = query.from;
  if (query.to) params.to = query.to;
  return params;
}

function LogRow({
  record,
  message,
  callerLabel,
}: {
  record: LogRecordDto;
  message: string;
  callerLabel: string;
}) {
  const { t } = useI18n();
  const [stackOpen, setStackOpen] = useState(false);
  const hasStack = record.level === 'ERROR' && Boolean(record.stack);
  const showParams =
    (record.level === 'WARN' || record.level === 'ERROR') &&
    record.params != null &&
    Object.keys(record.params).length > 0;
  return (
    <li data-testid="log-row" className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span data-testid="log-level-badge" className={cn('rounded px-2 py-0.5 text-[11px] font-medium', levelBadgeCls(record.level))}>
          {record.level}
        </span>
        <span data-testid="log-message" className="text-[13px] text-ink">{message}</span>
        <span data-testid="log-timestamp" className="ml-auto text-[12px] text-ink-3">{formatTimestamp(record.timestamp)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-3">
        <span data-testid="log-caller-type">{callerLabel}</span>
        <span data-testid="log-caller-name">{record.caller_name}</span>
        {record.duration_ms != null && (
          <span data-testid="log-duration">{formatDuration(record.duration_ms)}</span>
        )}
        {record.error_code && <span data-testid="log-error-code">{record.error_code}</span>}
        {record.correlation_id && <span data-testid="log-correlation">{record.correlation_id}</span>}
      </div>
      {showParams && (
        <div className="mt-1.5 text-[12px] text-ink-3">
          <span data-testid="log-params">
            {Object.entries(record.params)
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(' · ')}
          </span>
        </div>
      )}
      {hasStack && (
        <div className="mt-2">
          <button
            type="button"
            data-testid="log-stack-toggle"
            onClick={() => setStackOpen((open) => !open)}
            className="rounded border border-line bg-surface px-2 py-0.5 text-[12px] text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink"
          >
            {t('logs.stack.details')}
          </button>
          {stackOpen && (
            <pre
              data-testid="log-stack"
              className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded border border-line bg-surface-2 p-3 text-[11px] leading-relaxed text-ink-2"
            >
              {record.stack}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

export function LogsPage() {
  const { t } = useI18n();
  const lang = useThemeStore((s) => s.lang);
  const projects = useProjectStore((s) => s.projects);
  const [query, setQuery] = useState<QueryState>({ ...DEFAULT_QUERY });
  const [qDraft, setQDraft] = useState('');
  const [correlationDraft, setCorrelationDraft] = useState('');
  const [fromDraft, setFromDraft] = useState('');
  const [toDraft, setToDraft] = useState('');
  const [data, setData] = useState<LogsResponseDto | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remoteDir, setRemoteDir] = useState<Record<string, string>>({});
  const seqRef = useRef(0);

  // 查询状态机：query 对象身份变更即触发 fetchLogs（tab/level/project/search/reset/refresh/翻页）
  useEffect(() => {
    const seq = ++seqRef.current;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchLogs(buildParams(query))
      .then((result) => {
        if (!cancelled && seqRef.current === seq) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled && seqRef.current === seq) {
          setError(errorMessage(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  // 远端消息目录：挂载 + lang 变化拉取；失败静默（console.warn）回退本地字典
  useEffect(() => {
    let cancelled = false;
    setRemoteDir({});
    void fetchLogMessages(lang)
      .then((dir) => {
        if (!cancelled) setRemoteDir(dir);
      })
      .catch((err: unknown) => {
        console.warn('[logs] 远端消息目录拉取失败，回退本地字典:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [lang]);

  const changeQuery = (patch: Partial<QueryState>) => {
    setQuery((prev) => ({ ...prev, ...patch }));
  };
  const handleSearch = () => {
    changeQuery({
      q: qDraft.trim(),
      correlationId: correlationDraft.trim(),
      from: fromDraft,
      to: toDraft,
      page: 0,
    });
  };
  const handleReset = () => {
    setQDraft('');
    setCorrelationDraft('');
    setFromDraft('');
    setToDraft('');
    setQuery({ ...DEFAULT_QUERY });
  };
  const handleRefresh = () => {
    setQuery((prev) => ({ ...prev }));
  };
  /**
   * 行 message 四级回退 + 插值上下文合并：
   * 远端目录精确词条 → 本地字典 → log.call.* 通用词条 → 裸 key（现状保留）。
   * 插值上下文 = { caller_name, event, ...params }（params 同名键覆盖）。
   */
  const renderMessage = (rec: LogRecordDto): string => {
    const remoteTemplate = remoteDir[rec.message_key];
    let template: string;
    if (remoteTemplate !== undefined) {
      template = remoteTemplate;
    } else {
      const local = t(rec.message_key);
      if (local !== rec.message_key) {
        template = local;
      } else if (rec.message_key.startsWith('log.call.')) {
        template = t('log.call.generic');
      } else {
        template = rec.message_key;
      }
    }
    const ctx: Record<string, unknown> = {
      caller_name: rec.caller_name,
      event: rec.event,
      ...(rec.params ?? {}),
    };
    return interpolateTemplate(template, ctx);
  };

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
  const nextDisabled = !data || (query.page + 1) * PAGE_LIMIT >= total;
  return (
    <div data-testid="logs-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 data-testid="logs-title" className="font-serif text-[26px] font-semibold">{t('logs.title')}</h1>
      <p data-testid="logs-sub" className="mt-1 text-[13px] text-ink-2">{t('logs.sub')}</p>
      <div role="tablist" aria-label={t('logs.title')} className="mt-6 flex items-center gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            data-testid={`log-tab-${tab.key}`}
            aria-selected={query.tab === tab.key}
            onClick={() => changeQuery({ tab: tab.key, page: 0 })}
            className={cn(
              'rounded-md px-3 py-1.5 text-[13px] transition-colors',
              query.tab === tab.key
                ? 'bg-accent-weak font-medium text-accent'
                : 'text-ink-2 hover:bg-surface-3 hover:text-ink',
            )}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-ink-3">{t('logs.level.label')}</span>
          <Select value={query.level} onValueChange={(v) => changeQuery({ level: v as LevelKey, page: 0 })}>
            <SelectTrigger data-testid="log-level-select" aria-label={t('logs.level.label')} className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LEVELS.map((level) => (
                <SelectItem key={level} value={level}>{t(`logs.level.${level.toLowerCase()}`)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-ink-3">{t('logs.project.label')}</span>
          <Select
            value={query.projectId ?? ALL_PROJECTS}
            onValueChange={(v) => changeQuery({ projectId: v === ALL_PROJECTS ? null : v, page: 0 })}
          >
            <SelectTrigger data-testid="log-project-select" aria-label={t('logs.project.label')} className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_PROJECTS}>{t('logs.project.all')}</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>{project.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <input
          data-testid="log-q-input"
          type="text"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
          placeholder={t('logs.q.placeholder')}
          aria-label={t('logs.q.placeholder')}
          className="h-9 w-64 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-ring/60"
        />
        <input
          data-testid="log-correlation-input"
          type="text"
          value={correlationDraft}
          onChange={(e) => setCorrelationDraft(e.target.value)}
          placeholder={t('logs.correlation.placeholder')}
          aria-label={t('logs.correlation.placeholder')}
          className="h-9 w-44 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-ring/60"
        />
        <input
          data-testid="log-from-input"
          type="datetime-local"
          value={fromDraft}
          onChange={(e) => setFromDraft(e.target.value)}
          aria-label={t('logs.from.label')}
          className="h-9 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-ring/60"
        />
        <input
          data-testid="log-to-input"
          type="datetime-local"
          value={toDraft}
          onChange={(e) => setToDraft(e.target.value)}
          aria-label={t('logs.to.label')}
          className="h-9 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-ring/60"
        />
        <div className="flex items-end gap-2">
          <button
            type="button"
            data-testid="log-search-btn"
            className="flex h-9 items-center gap-1.5 rounded-md bg-accent px-4 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover"
            onClick={handleSearch}
          >
            <Search className="h-4 w-4" aria-hidden="true" />
            {t('logs.search')}
          </button>
          <button
            type="button"
            data-testid="log-reset-btn"
            className="h-9 rounded-md border border-line bg-surface px-3 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={handleReset}
          >
            {t('logs.reset')}
          </button>
          <button
            type="button"
            data-testid="log-refresh-btn"
            className="flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={handleRefresh}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t('logs.refresh')}
          </button>
        </div>
      </div>
      <section data-testid="log-list" className="mt-8">
        {loading && (
          <div data-testid="log-loading" className="flex items-center justify-center gap-3 rounded-lg border border-line bg-surface px-4 py-10 text-[13px] text-ink-2">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t('logs.loading')}
          </div>
        )}
        {!loading && error && (
          <div data-testid="log-error" className="rounded-lg border border-err/40 bg-err/10 px-4 py-10 text-center text-[13px] text-err">
            {t('logs.error')}：{error}
          </div>
        )}
        {!loading && !error && data && data.items.length === 0 && (
          <div data-testid="log-empty" className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center">
            <p className="font-serif text-[15px] font-semibold text-ink">{t('logs.empty')}</p>
          </div>
        )}
        {!loading && !error && data && data.items.length > 0 && (
          <ul className="space-y-2">
            {data.items.map((rec, index) => (
              <LogRow
                key={`${index}-${rec.timestamp}-${rec.event}`}
                record={rec}
                message={renderMessage(rec)}
                callerLabel={CALLER_LABEL_KEY[rec.caller_type] ? t(CALLER_LABEL_KEY[rec.caller_type]) : rec.caller_type}
              />
            ))}
          </ul>
        )}
      </section>
      <div className="mt-6 flex items-center gap-3">
        <button type="button" data-testid="log-page-prev" disabled={query.page === 0} className="rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50" onClick={() => changeQuery({ page: query.page - 1 })}>
          {t('logs.prev')}
        </button>
        <span data-testid="log-page-info" className="text-[13px] text-ink-2">
          {t('logs.page.info', { page: query.page + 1, pages, total })}
        </span>
        <button type="button" data-testid="log-page-next" disabled={nextDisabled} className="rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50" onClick={() => changeQuery({ page: query.page + 1 })}>
          {t('logs.next')}
        </button>
      </div>
    </div>
  );
}
