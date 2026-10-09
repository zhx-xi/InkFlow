/**
 * #652 / #1528 / #1544「AI 提取」GUI 通道（前端契约 GREEN）：
 * - 类型面：角色 / 世界观 / 时间线 / 伏笔 / 知识图谱（单选，默认「角色」）+ 通用（多选 5 类）
 * - 范围面：全文 / 按卷（多选卷）/ 按章（区间，多段并集）
 * - 提交：统一 `POST /api/v1/extract`，type 由所选类型决定；N 个类型 = N 次请求
 * - 范围 → `chapter_ids`：全文 = 项目全部章；按卷 = 选中卷的全部章；按章 = 各区间展开
 * - 单批 `chapter_ids` ≤ 100（后端 validator），超出自动分批（多请求）
 * - 逐类型 body 差异：`timeline` 带 `chapter_ids` + `auto_extract: true`（不带 text）；
 *   `knowledge_relation` 不带 `chapter_ids` / `text`（项目级提取）；其余带 `chapter_ids`
 * - 反馈三态（沿用 #652）：进行中（按钮 disabled + `ai-extract-running`）/ 完成 toast ok /
 *   失败 toast err（errorMessage，按钮恢复 enabled，不硬崩）
 */
import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import {
  fetchAllChapters,
  fetchVolumes,
  type ChapterListDto,
  type VolumeListDto,
} from '../../api/chapters';
import { apiFetch, errorMessage } from '../../api/client';
import { useI18n } from '../../i18n/useI18n';
import { useToastStore } from '../../stores/toast';

export interface AIExtractDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** 写作页默认当前章（保留接口兼容；#1544 起提交走范围面，不再依赖单章 text） */
  defaultChapterId?: string;
  /** 写作页默认当前章正文（保留接口兼容） */
  defaultText?: string;
}

/** 最近一次运行摘要（GET /projects/{pid}/extractions/runs 响应项） */
interface ExtractionRun {
  id: number;
  type: string;
  status: string;
  created_count: number;
  updated_count: number;
}

/** 提取类型（单选 6 项；`generic` 走多选面板） */
type ExtractKind =
  | 'character'
  | 'world'
  | 'timeline'
  | 'foreshadowing'
  | 'knowledgeGraph'
  | 'generic';

/** 提取范围（全文 / 按卷 / 按章） */
type ExtractScope = 'all' | 'volume' | 'chapter';

/** 类型表：UI 值 / i18n 键 / 后端 type（世界观 → setting、知识图谱 → knowledge_relation） */
const TYPE_OPTIONS: Array<{ value: ExtractKind; labelKey: string; backendType: string }> = [
  { value: 'character', labelKey: 'extract.character', backendType: 'character' },
  { value: 'world', labelKey: 'extract.world', backendType: 'setting' },
  { value: 'timeline', labelKey: 'extract.timeline', backendType: 'timeline' },
  { value: 'foreshadowing', labelKey: 'extract.foreshadowing', backendType: 'foreshadowing' },
  { value: 'knowledgeGraph', labelKey: 'extract.knowledgeGraph', backendType: 'knowledge_relation' },
  { value: 'generic', labelKey: 'extract.generic', backendType: '' },
];

/** 通用多选面板选项（5 类，不含「通用」本身） */
const GENERIC_OPTIONS = TYPE_OPTIONS.filter((opt) => opt.value !== 'generic');

/** 范围表（单选 3 项，默认「全文」） */
const SCOPE_OPTIONS: Array<{ value: ExtractScope; labelKey: string }> = [
  { value: 'all', labelKey: 'extract.scope.all' },
  { value: 'volume', labelKey: 'extract.scope.volume' },
  { value: 'chapter', labelKey: 'extract.scope.chapter' },
];

/** 单次请求 `chapter_ids` 上限（后端 ExtractionRequest validator：≤ 100） */
const CHAPTER_BATCH_LIMIT = 100;

/** 运行摘要类型标签（timeline → 时间线；其余键保留 #652 口径，未登记原值兜底） */
const RUN_TYPE_LABELS: Record<string, string> = {
  character: '角色',
  setting: '世界观',
  timeline: '时间线',
  foreshadowing: '伏笔',
  knowledge_relation: '知识关系',
};

/** 章节区间（1-based，含端点） */
interface ChapterRange {
  from: number;
  to: number;
}

/** 按 order_index 升序（章节列表响应可能乱序；区间展开依赖稳定顺序） */
function sortByOrderIndex(chapters: ChapterListDto[]): ChapterListDto[] {
  return [...chapters].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
}

/** 章节 id 分批（每批 ≤ 100；空列表也发一次空批，保持「单选 = 1 次」语义） */
function chunkChapterIds(ids: string[]): string[][] {
  if (ids.length === 0) return [[]];
  const batches: string[][] = [];
  for (let i = 0; i < ids.length; i += CHAPTER_BATCH_LIMIT) {
    batches.push(ids.slice(i, i + CHAPTER_BATCH_LIMIT));
  }
  return batches;
}

/** 范围 → chapter_ids（保持 order_index 升序；按章区间取并集去重） */
function resolveChapterIds(
  ordered: ChapterListDto[],
  scope: ExtractScope,
  selectedVolumeIds: string[],
  ranges: ChapterRange[],
): string[] {
  if (scope === 'volume') {
    return ordered
      .filter((ch) => ch.volume_id !== null && selectedVolumeIds.includes(ch.volume_id))
      .map((ch) => ch.id);
  }
  if (scope === 'chapter') {
    const picked = new Set<number>();
    for (const { from, to } of ranges) {
      const lo = Math.max(1, Math.min(from, to));
      const hi = Math.min(ordered.length, Math.max(from, to));
      for (let i = lo; i <= hi; i += 1) picked.add(i);
    }
    return ordered.filter((_, idx) => picked.has(idx + 1)).map((ch) => ch.id);
  }
  return ordered.map((ch) => ch.id);
}

/** 单个提取结果信封（POST /api/v1/extract 响应；计数为数字口径） */
interface ExtractEnvelope {
  created?: number;
  updated?: number;
}

export function AIExtractDialog({ open, onClose, projectId }: AIExtractDialogProps) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);

  const [chapters, setChapters] = useState<ChapterListDto[]>([]);
  const [volumes, setVolumes] = useState<VolumeListDto[]>([]);
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [extractKind, setExtractKind] = useState<ExtractKind>('character');
  const [genericSelected, setGenericSelected] = useState<ExtractKind[]>([]);
  const [scope, setScope] = useState<ExtractScope>('all');
  const [selectedVolumeIds, setSelectedVolumeIds] = useState<string[]>([]);
  const [rangeFrom, setRangeFrom] = useState('');
  const [rangeTo, setRangeTo] = useState('');
  const [ranges, setRanges] = useState<ChapterRange[]>([]);
  const [running, setRunning] = useState(false);

  // open 变 true：拉取章节列表（全量翻页，#1407）+ 卷列表（#1544）+ 最近一次运行摘要
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setRunsLoaded(false);
    void (async () => {
      try {
        const { items } = await fetchAllChapters(projectId);
        if (!cancelled) setChapters(items);
      } catch {
        if (!cancelled) setChapters([]);
      }
      try {
        const { items } = await fetchVolumes(projectId);
        if (!cancelled) setVolumes(items ?? []);
      } catch {
        if (!cancelled) setVolumes([]);
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
  }, [open, projectId]);

  const toggleGeneric = (value: ExtractKind) => {
    setGenericSelected((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  const toggleVolume = (volumeId: string) => {
    setSelectedVolumeIds((prev) =>
      prev.includes(volumeId) ? prev.filter((v) => v !== volumeId) : [...prev, volumeId],
    );
  };

  const addRange = () => {
    const from = Number.parseInt(rangeFrom, 10);
    const to = Number.parseInt(rangeTo, 10);
    if (!Number.isFinite(from) || !Number.isFinite(to) || from < 1 || to < 1) return;
    setRanges((prev) => [...prev, { from, to }]);
    setRangeFrom('');
    setRangeTo('');
  };

  /**
   * 提交：解析所选类型 → 逐类型 POST /api/v1/extract → 成功 toast + 重拉 runs；
   * 失败 err toast（errorMessage）+ 按钮恢复 enabled。
   */
  const handleRun = async () => {
    if (running) return;
    const backendTypes =
      extractKind === 'generic'
        ? GENERIC_OPTIONS.filter((opt) => genericSelected.includes(opt.value)).map(
            (opt) => opt.backendType,
          )
        : [TYPE_OPTIONS.find((opt) => opt.value === extractKind)?.backendType ?? ''].filter(
            (v) => v !== '',
          );
    if (backendTypes.length === 0) return;

    const ordered = sortByOrderIndex(chapters);
    const chapterIds = resolveChapterIds(ordered, scope, selectedVolumeIds, ranges);

    setRunning(true);
    try {
      let created = 0;
      let updated = 0;
      for (const type of backendTypes) {
        // knowledge_relation = 项目级提取：不带 chapter_ids / text
        const carriesChapters = type !== 'knowledge_relation';
        const batches = carriesChapters ? chunkChapterIds(chapterIds) : [[]];
        for (const batch of batches) {
          const body: Record<string, unknown> = { project_id: projectId, type };
          if (carriesChapters) body.chapter_ids = batch;
          if (type === 'timeline') body.auto_extract = true;
          const result = await apiFetch<ExtractEnvelope>('/api/v1/extract', {
            method: 'POST',
            body,
          });
          created += result.created ?? 0;
          updated += result.updated ?? 0;
        }
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

        {/* 类型面：6 单选（默认「角色」） */}
        <fieldset className="mt-4">
          <legend className="text-[12px] text-ink-2">{t('extract.typeGeneric')}</legend>
          <div
            data-testid="ai-extract-type"
            role="radiogroup"
            aria-label={t('extract.typeGeneric')}
            className="mt-2 flex flex-wrap gap-3"
          >
            {TYPE_OPTIONS.map((opt) => (
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
        </fieldset>

        {/* 通用多选面板（仅「通用」选中时渲染，默认全不选） */}
        {extractKind === 'generic' && (
          <div className="mt-4 flex flex-col gap-1.5 text-[12px] text-ink-2">
            <span>{t('extract.genericHint')}</span>
            <div data-testid="ai-extract-generic" className="flex flex-wrap gap-3">
              {GENERIC_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className="flex cursor-pointer items-center gap-2 rounded-md border bg-surface px-3 py-1.5 text-[13px] transition duration-180"
                >
                  <input
                    type="checkbox"
                    checked={genericSelected.includes(opt.value)}
                    onChange={() => toggleGeneric(opt.value)}
                    className="h-3.5 w-3.5 accent-accent"
                  />
                  <span>{t(opt.labelKey)}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* 范围面：3 单选（默认「全文」） */}
        <fieldset className="mt-4">
          <legend className="text-[12px] text-ink-2">{t('extract.scope')}</legend>
          <div
            data-testid="ai-extract-scope"
            role="radiogroup"
            aria-label={t('extract.scope')}
            className="mt-2 flex gap-3"
          >
            {SCOPE_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-center gap-2 rounded-md border bg-surface px-4 py-1.5 text-[13px] transition duration-180"
              >
                <input
                  type="radio"
                  name="ai-extract-scope"
                  value={opt.value}
                  checked={scope === opt.value}
                  onChange={() => setScope(opt.value)}
                  className="h-3.5 w-3.5 accent-accent"
                />
                <span>{t(opt.labelKey)}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {/* 按卷：卷多选（可访问名 = 卷标题） */}
        {scope === 'volume' && (
          <div
            data-testid="ai-extract-volume-list"
            className="mt-3 flex flex-wrap gap-3 text-[12px] text-ink-2"
          >
            {volumes.map((vol) => (
              <label
                key={vol.id}
                className="flex cursor-pointer items-center gap-2 rounded-md border bg-surface px-3 py-1.5 text-[13px] transition duration-180"
              >
                <input
                  type="checkbox"
                  checked={selectedVolumeIds.includes(vol.id)}
                  onChange={() => toggleVolume(vol.id)}
                  className="h-3.5 w-3.5 accent-accent"
                />
                <span>{vol.title}</span>
              </label>
            ))}
          </div>
        )}

        {/* 按章：区间输入 + 添加范围 */}
        {scope === 'chapter' && (
          <div className="mt-3 flex flex-col gap-2 text-[12px] text-ink-2">
            <div className="flex items-center gap-2">
              <input
                data-testid="ai-extract-range-from"
                type="number"
                min={1}
                value={rangeFrom}
                onChange={(e) => setRangeFrom(e.target.value)}
                className="w-20 rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              />
              <span aria-hidden="true">–</span>
              <input
                data-testid="ai-extract-range-to"
                type="number"
                min={1}
                value={rangeTo}
                onChange={(e) => setRangeTo(e.target.value)}
                className="w-20 rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              />
              <button
                type="button"
                data-testid="ai-extract-range-add"
                onClick={addRange}
                className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                {t('extract.addRange')}
              </button>
            </div>
            <span>{t('extract.rangeHint')}</span>
          </div>
        )}

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
