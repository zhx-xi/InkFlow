/**
 * #652「AI 提取」GUI 通道（前端契约 GREEN）：
 * - 触发 = A 整章一键：弹窗选章节，前端取该章内容作 text 提交
 * - 提取类型 = 角色 / 世界观 / 通用（通用带上伏笔/知识关系，为导入书籍功能铺路）
 * - 反馈三态 = 进行中 spinner + 按钮 disabled / 完成 toast / 失败 err toast（未配模型优雅降级不硬崩）
 * - 三端点均同步返回（无 status 轮询）：POST /characters/extract、/world-settings/extract 只收
 *   {project_id, text}；POST /extract 收 {project_id, type, text}
 */
import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { apiFetch, errorMessage } from '../../api/client';
import { useI18n } from '../../i18n/useI18n';
import { useToastStore } from '../../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';

export interface AIExtractDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** 写作页默认当前章（缺省则用章节列表第一项） */
  defaultChapterId?: string;
  /** 写作页默认当前章正文（避免重复拉取） */
  defaultText?: string;
}

/** 章节列表项（镜像 useChapterStore ChapterMeta） */
interface ChapterMeta {
  id: string;
  title: string;
}

/** 最近一次运行摘要（GET /projects/{pid}/extractions/runs 响应项） */
interface ExtractionRun {
  id: number;
  type: string;
  status: string;
  created_count: number;
  updated_count: number;
}

/** 提取类型（角色 / 世界观 / 通用） */
type ExtractKind = 'character' | 'world' | 'generic';

/** 通用提取子类型（伏笔 / 知识关系） */
const GENERIC_TYPES: Array<{ value: string; labelKey: string }> = [
  { value: 'foreshadowing', labelKey: 'extract.foreshadowing' },
  { value: 'knowledge_relation', labelKey: 'extract.knowledgeRelation' },
];

/** 运行摘要类型标签（character→角色、setting→世界观、foreshadowing→伏笔、knowledge_relation→知识关系、其他→原值） */
const RUN_TYPE_LABELS: Record<string, string> = {
  character: '角色',
  setting: '世界观',
  foreshadowing: '伏笔',
  knowledge_relation: '知识关系',
};

const RADIO_OPTIONS: Array<{ value: ExtractKind; labelKey: string }> = [
  { value: 'character', labelKey: 'extract.character' },
  { value: 'world', labelKey: 'extract.world' },
  { value: 'generic', labelKey: 'extract.generic' },
];

export function AIExtractDialog({
  open,
  onClose,
  projectId,
  defaultChapterId,
  defaultText,
}: AIExtractDialogProps) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);

  const [chapters, setChapters] = useState<ChapterMeta[]>([]);
  const [selectedChapterId, setSelectedChapterId] = useState('');
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [extractKind, setExtractKind] = useState<ExtractKind>('character');
  const [genericType, setGenericType] = useState('foreshadowing');
  const [running, setRunning] = useState(false);

  // open 变 true：拉取章节列表 + 最近一次运行摘要（defaultChapterId 命中则默认选中）
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setRunsLoaded(false);
    void (async () => {
      try {
        const chapterData = await apiFetch<{ items: ChapterMeta[] }>(
          `/api/v1/projects/${projectId}/chapters`,
        );
        if (cancelled) return;
        const list = chapterData.items ?? [];
        setChapters(list);
        setSelectedChapterId((prev) => {
          if (defaultChapterId !== undefined && list.some((c) => c.id === defaultChapterId)) {
            return defaultChapterId;
          }
          if (prev !== '' && list.some((c) => c.id === prev)) return prev;
          return list[0]?.id ?? '';
        });
      } catch {
        if (!cancelled) setChapters([]);
      }
      try {
        const runData = await apiFetch<{ items: ExtractionRun[] }>(
          `/api/v1/projects/${projectId}/extractions/runs`,
        );
        if (!cancelled) {
          setRuns(runData.items ?? []);
          setRunsLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setRuns([]);
          setRunsLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId, defaultChapterId]);

  /** 提交：解析 text → 按类型 POST → 成功 toast + 重拉 runs；失败 err toast（按钮恢复 enabled） */
  const handleRun = async () => {
    if (running || selectedChapterId === '') return;
    setRunning(true);
    try {
      // 若已选章节命中写作页默认当前章且 defaultText 非空 → 直接用正文，避免重复拉取
      let text: string;
      if (selectedChapterId === defaultChapterId && defaultText) {
        text = defaultText;
      } else {
        const chapter = await apiFetch<{ content?: string }>(`/api/v1/chapters/${selectedChapterId}`);
        text = chapter.content ?? '';
      }
      let created: number;
      let updated: number;
      if (extractKind === 'character') {
        const result = await apiFetch<{ created: unknown[]; updated: unknown[] }>(
          '/api/v1/characters/extract',
          { method: 'POST', body: { project_id: projectId, text } },
        );
        created = result.created.length;
        updated = result.updated.length;
      } else if (extractKind === 'world') {
        const result = await apiFetch<{ created: unknown[]; updated: unknown[] }>(
          '/api/v1/world-settings/extract',
          { method: 'POST', body: { project_id: projectId, text } },
        );
        created = result.created.length;
        updated = result.updated.length;
      } else {
        const result = await apiFetch<{ created: number; updated: number }>('/api/v1/extract', {
          method: 'POST',
          body: { project_id: projectId, type: genericType, text },
        });
        created = result.created;
        updated = result.updated;
      }
      pushToast('ok', `${t('extract.done')} · 新增 ${created} · 更新 ${updated} · 已落地设定库`);
      // 重拉最近一次运行摘要
      const runData = await apiFetch<{ items: ExtractionRun[] }>(
        `/api/v1/projects/${projectId}/extractions/runs`,
      );
      setRuns(runData.items ?? []);
    } catch (err) {
      pushToast('err', errorMessage(err));
    } finally {
      setRunning(false);
    }
  };

  if (!open) return null;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        data-testid="ai-extract-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('extract.title')}
        className="max-h-[80vh] w-[560px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-[18px] font-semibold">{t('extract.title')}</h2>
          <button
            type="button"
            aria-label={t('audit.close')}
            className="rounded p-1 text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={onClose}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        {/* 提取类型 radio 组（默认选中「角色」） */}
        <div
          data-testid="ai-extract-type"
          role="radiogroup"
          aria-label={t('extract.typeGeneric')}
          className="mt-4 flex gap-3"
        >
          {RADIO_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex cursor-pointer items-center gap-2 rounded-md border bg-surface px-4 py-1.5 text-[13px] transition duration-180"
            >
              <input
                type="radio"
                name="ai-extract-type"
                value={opt.value}
                checked={extractKind === opt.value}
                onChange={() => setExtractKind(opt.value)}
                className="h-3.5 w-3.5 accent-accent"
              />
              <span>{t(opt.labelKey)}</span>
            </label>
          ))}
        </div>

        {/* 通用类型 Select（仅选中「通用」时渲染） */}
        {extractKind === 'generic' && (
          <div className="mt-4 flex flex-col gap-1.5 text-[12px] text-ink-2">
            <span>{t('extract.typeGeneric')}</span>
            <Select value={genericType} onValueChange={setGenericType}>
              <SelectTrigger data-testid="ai-extract-type-generic" className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GENERIC_TYPES.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* 章节 Select（整章一键，源 = 所选章节） */}
        <div className="mt-4 flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('extract.chapter')}</span>
          <Select value={selectedChapterId} onValueChange={setSelectedChapterId}>
            <SelectTrigger data-testid="ai-extract-chapter" className="w-72">
              <SelectValue placeholder={t('extract.chapter')} />
            </SelectTrigger>
            <SelectContent>
              {chapters.map((ch) => (
                <SelectItem key={ch.id} value={ch.id}>
                  {ch.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* 提交按钮 + 运行中指示 */}
        <div className="mt-6 flex items-center gap-3">
          <button
            type="button"
            data-testid="ai-extract-run"
            disabled={running}
            onClick={() => void handleRun()}
            className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t('extract.run')}
          </button>
          {running && (
            <span
              data-testid="ai-extract-running"
              className="inline-flex items-center gap-1.5 text-[13px] text-ink-2"
            >
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('extract.running')}
            </span>
          )}
        </div>

        {/* 最近一次运行摘要卡 */}
        <div className="mt-5">
          <h3 className="text-[13px] font-medium text-ink-2">{t('extract.lastRun')}</h3>
          {runsLoaded ? (
            runs.length === 0 ? (
              <p data-testid="ai-extract-last-run" className="mt-2 text-[12px] text-ink-3">
                {t('extract.noRun')}
              </p>
            ) : (
              <div className="mt-2 space-y-1.5">
                {runs.map((run) => (
                  <div
                    key={run.id}
                    data-testid="ai-extract-last-run"
                    className="rounded-md border border-line bg-surface-2 px-3 py-2 text-[12px] text-ink"
                  >
                    {RUN_TYPE_LABELS[run.type] ?? run.type} · {run.status} · 新增 {run.created_count} · 更新{' '}
                    {run.updated_count}
                  </div>
                ))}
              </div>
            )
          ) : null}
        </div>
      </div>
    </div>
  );
}
