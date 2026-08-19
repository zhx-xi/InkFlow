/**
 * #479 知识图谱定时提取设置卡片（specs/f48-knowledge-graph/spec.md §5.5.7）：
 * 挂载于设置页常规分类（GeneralPanel 内，只挂载不内联）。
 * - 启用开关 / 提取频率 Select（1/6/12/24/72/168 小时）/ 提取方式 Radio（rule/ai/both）
 * - 设置读取：GeneralPanel 既有 fetchSettings 全量快照经 settings prop 注入（单次拉取，
 *   防双 GET 抢 mockResolvedValueOnce）；写入复用 client.ts patchSettings（单键 PATCH）
 * - 未配 chat 模型（hasChatModel=false）→ ai/both disabled + needModel 提示（D3 门禁）
 * - 立即运行 → apiFetch POST /api/v1/knowledge/extract → 轮询 /status 直至 running=false
 * 注：挂载不自调 loadProviders（providers 由模型/Agent 分类面板挂载时加载，store 订阅随到随更新；
 *     卡片自调会在设置页常规模块引入首个 apiFetch，破坏既有测试的零调用/Once mock 断言）
 */
import { useEffect, useRef, useState } from 'react';
import { apiFetch, patchSettings, type AppSettings } from '../../api/client';
import { cn } from '../../lib/cn';
import { useI18n } from '../../i18n/useI18n';
import { hasChatModel, useModelsStore } from '../../stores/models';
import { useProjectStore } from '../../stores/project';
import { useToastStore } from '../../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Switch } from '../ui/switch';

/** 提取方式（spec §5.5.2：rule=仅规则 / ai=仅 AI / both=规则+AI） */
type ExtractMethod = 'rule' | 'ai' | 'both';

/** 频率选项（小时）：契约钉死 1/6/12/24/72/168 */
const INTERVAL_OPTIONS = [1, 6, 12, 24, 72, 168] as const;

/** 提取方式选项；ai/both 依赖 chat 模型（needsModel 门禁） */
const METHOD_OPTIONS: Array<{ value: ExtractMethod; needsModel: boolean }> = [
  { value: 'rule', needsModel: false },
  { value: 'ai', needsModel: true },
  { value: 'both', needsModel: true },
];

/** GET /api/v1/knowledge/extract/status 响应形态（spec §5.5.7） */
interface ExtractStatusDto {
  running?: boolean;
  last_run?: string | null;
}

/** 运行中状态轮询间隔（ms） */
const STATUS_POLL_MS = 1_000;

/** 默认提取频率（spec §5.5.2） */
const DEFAULT_INTERVAL_HOURS = 24;

export function KnowledgeExtractCard({ settings }: { settings?: AppSettings | null }) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const providers = useModelsStore((s) => s.providers);
  const hasChat = hasChatModel(providers ?? []);

  const [enabled, setEnabled] = useState(false);
  const [intervalHours, setIntervalHours] = useState(DEFAULT_INTERVAL_HOURS);
  const [method, setMethod] = useState<ExtractMethod>('rule');
  const [running, setRunning] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 回显：settings 全量快照到达 → 三键驱动控件初值（未到达/无项目级 fetch → 保默认）
  useEffect(() => {
    if (!settings) return;
    setEnabled(Boolean(settings.kg_extract_enabled));
    if (Number.isFinite(settings.kg_extract_interval_hours)) {
      setIntervalHours(settings.kg_extract_interval_hours);
    }
    if (
      settings.kg_extract_method === 'rule' ||
      settings.kg_extract_method === 'ai' ||
      settings.kg_extract_method === 'both'
    ) {
      setMethod(settings.kg_extract_method);
    }
  }, [settings]);

  // 卸载清理轮询定时器（防卸载后 setState / 内存泄漏）
  useEffect(
    () => () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    },
    [],
  );

  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  /** 轮询提取状态：running=false → 恢复按钮 + 停止轮询；失败静默下一轮重试 */
  const pollStatus = () => {
    void apiFetch<ExtractStatusDto>('/api/v1/knowledge/extract/status')
      .then((data) => {
        if (data.running !== true) {
          setRunning(false);
          stopPolling();
        }
      })
      .catch(() => {});
  };

  /** 立即运行：POST /extract（无项目 → 跑全部项目，body 不含 project_id）→ 轮询 status */
  const handleRunNow = () => {
    if (running) return;
    setRunning(true);
    const body: { method: ExtractMethod; project_id?: string } = { method };
    if (currentProjectId) body.project_id = currentProjectId;
    void apiFetch('/api/v1/knowledge/extract', { method: 'POST', body })
      .then(() => {
        pollTimerRef.current = setInterval(pollStatus, STATUS_POLL_MS);
        pollStatus();
      })
      .catch(() => {
        setRunning(false);
        pushToast('err', t('toast.saveFailed'));
      });
  };

  const handleEnabledChange = (checked: boolean) => {
    setEnabled(checked);
    void patchSettings({ kg_extract_enabled: checked }).catch(() => pushToast('err', t('toast.saveFailed')));
  };

  const handleIntervalChange = (value: string) => {
    const n = Number(value);
    setIntervalHours(n);
    void patchSettings({ kg_extract_interval_hours: n }).catch(() => pushToast('err', t('toast.saveFailed')));
  };

  const handleMethodChange = (value: ExtractMethod) => {
    setMethod(value);
    void patchSettings({ kg_extract_method: value }).catch(() => pushToast('err', t('toast.saveFailed')));
  };

  return (
    <section data-testid="kg-extract-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('settings.kgExtract.title')}</h2>
      <div className="mt-4 space-y-4">
        {/* 启用开关 */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-ink-2">{t('settings.kgExtract.enabled')}</span>
          </div>
          <Switch
            data-testid="kg-extract-enabled"
            checked={enabled}
            onCheckedChange={handleEnabledChange}
            aria-label={t('settings.kgExtract.enabled')}
          />
        </div>

        {/* 提取频率 */}
        <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('settings.kgExtract.interval')}</span>
          <Select value={String(intervalHours)} onValueChange={handleIntervalChange}>
            <SelectTrigger data-testid="kg-extract-interval" aria-label={t('settings.kgExtract.interval')} className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INTERVAL_OPTIONS.map((h) => (
                <SelectItem key={h} value={String(h)}>
                  {h} 小时
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* 提取方式（D3 门禁：未配 chat 模型 → ai/both disabled + 提示） */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-ink-2">{t('settings.kgExtract.method')}</span>
          <div
            data-testid="kg-extract-method"
            role="radiogroup"
            aria-label={t('settings.kgExtract.method')}
            className="flex gap-3"
          >
            {METHOD_OPTIONS.map((opt) => {
              const disabled = opt.needsModel && !hasChat;
              const selected = method === opt.value;
              return (
                <label
                  key={opt.value}
                  className={cn(
                    'flex cursor-pointer items-center gap-2 rounded-md border bg-surface px-4 py-1.5 text-[13px] transition duration-180',
                    selected ? 'border-accent text-accent ring-2 ring-ring/50' : 'border-line text-ink-2 hover:border-accent/50',
                    disabled && 'cursor-not-allowed opacity-50',
                  )}
                >
                  <input
                    type="radio"
                    name="kg-extract-method"
                    value={opt.value}
                    checked={selected}
                    disabled={disabled}
                    onChange={() => handleMethodChange(opt.value)}
                    className="h-3.5 w-3.5 accent-accent"
                  />
                  <span>{t(`settings.kgExtract.${opt.value}`)}</span>
                </label>
              );
            })}
          </div>
          {!hasChat && (
            <p data-testid="kg-extract-need-model" className="text-[12px] text-warn">
              {t('settings.kgExtract.needModel')}
            </p>
          )}
        </div>

        {/* 立即运行 */}
        <button
          type="button"
          data-testid="kg-extract-run-now"
          disabled={running}
          onClick={handleRunNow}
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {running ? t('settings.kgExtract.running') : t('settings.kgExtract.runNow')}
        </button>
      </div>
    </section>
  );
}
