/**
 * F43 P3 大纲三级树（specs/f43-setting-library-crud/spec.md §5.14-5.15）：
 * 整体 → 卷 → 章 → 情节点（level/parent_id 前端建树；孤立章降级顶层；未知 level 按整体兜底）；
 * 三级展开收起（有子节点才渲染 toggle，叶子不渲染）；各层新增按钮（本批占位，创建入口后置）；
 * 章关联徽标（chapter_id 非空 → 📎 + 章节标题，title=lib.chapterRefTip；未关联 → 「关联章节」按钮，
 * 点击仅 toast lib.chapterLinkPick，不打开选择器 D9）；
 * 情节点首次展开按需拉取 GET /outlines/{id}/plot-points + 前端本地缓存（收起再展开不重拉）。
 *
 * #649 大纲子项写操作（specs/f11-outline-service/spec.md §3 + #649 拍板）：
 * - 情节节点：章行「＋情节点」→ 创建对话框（name 必填 gate；type/desc/arc 可选，arc 为原生 select）；
 *   行内 ✎ 编辑（预填现值 + PATCH 仅变化字段）/ 🗑 删除（ConfirmDialog 真删）；
 *   新增/编辑/删除成功后强制刷新该章情节点（fetchedRef 移除 key 再拉取）。
 * - 故事弧：大纲 tab 下方独立面板（outline-arcs）+ 创建/编辑/删除（真删 + ConfirmDialog）；
 *   弧列表按 projectId 拉取，CRUD 成功后本地回写（新弧/更新/移除即时可见）。
 * - AI 生成：library-ai-generate → outline-generate-dialog；POST /outlines/generate { save: true }，
 *   进行中 outline-generate-loading 反馈、完成 toast ok + onOutlineGenerated（父级插入树顶部）、失败 err toast。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ChevronRight, Loader2, Pencil, Trash2, Wand2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { ConfirmDialog } from './ConfirmDialog';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { useToastStore } from '../stores/toast';
import type { LibraryItemDTO } from './LibraryCreateDialog';

export type OutlineLevel = 'overall' | 'volume' | 'chapter';

const OUTLINE_LEVELS: readonly OutlineLevel[] = ['overall', 'volume', 'chapter'];

/** 大纲 DTO（spec §2.8：level/parent_id/chapter_id/point_count） */
export interface OutlineItemDTO extends LibraryItemDTO {
  level?: OutlineLevel | string;
  parent_id?: string | number | null;
  chapter_id?: string | number | null;
  point_count?: number;
}

/** 情节点 DTO（spec §2.8：GET /outlines/{id}/plot-points；arc_id/outline_id 供编辑/删除刷新） */
export interface PlotPointDTO {
  id: string | number;
  name?: string;
  type?: string;
  description?: string;
  position?: number;
  arc_id?: string | number | null;
  outline_id?: string | number | null;
}

/** 故事弧 DTO（#649：GET /projects/{pid}/story-arcs → { items, total }，point_count 后端聚合） */
export interface StoryArcDTO {
  id: string | number;
  name?: string;
  description?: string;
  point_count?: number;
}

/** 前端建树节点（parent_id 树，孤儿降级顶层） */
interface OutlineTreeNode {
  item: OutlineItemDTO;
  children: OutlineTreeNode[];
}

export interface OutlineTreeProps {
  outlines: OutlineItemDTO[];
  /** chapter_id → 章节标题（GET /projects/{pid}/chapters 映射，library.tsx 装配） */
  chapterTitles: Record<string, string>;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  /** 「＋卷」/「＋章」新增入口（打开父级创建对话框；「＋情节点」本轨改走情节节点对话框） */
  onAdd?: () => void;
  /** #649：故事弧列表（情节点对话框弧线下拉；不传时按 projectId 自行拉取） */
  arcs?: StoryArcDTO[];
  /** #649：当前项目 id（故事弧拉取 + AI 生成 project_id） */
  projectId?: string;
  /** #649：AI 生成成功回调（父级把新大纲插入树顶部） */
  onOutlineGenerated?: (outline: OutlineItemDTO) => void;
}

/** level 归一化：缺失/非法 level 按 overall 兜底（兼容旧数据，顶层渲染） */
function normalizeLevel(level: unknown): OutlineLevel {
  return OUTLINE_LEVELS.includes(level as OutlineLevel) ? (level as OutlineLevel) : 'overall';
}

/** §5.14：items → 树——overall 顶层；volume 挂 overall；chapter 挂 volume；孤儿（parent 缺失）降级顶层 */
function buildOutlineTree(items: OutlineItemDTO[]): OutlineTreeNode[] {
  const nodes = new Map<string, OutlineTreeNode>();
  for (const item of items) {
    nodes.set(String(item.id), { item, children: [] });
  }
  const roots: OutlineTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(String(item.id));
    if (!node) continue;
    const parentId = item.parent_id;
    if (parentId !== null && parentId !== undefined && nodes.has(String(parentId))) {
      nodes.get(String(parentId))!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

const INPUT_CLS =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent';
const BTN_SECONDARY =
  'rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3';
const BTN_PRIMARY =
  'rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50';

/** 情节点表单值（对话框内受控状态；arc_id 空串 = 不挂弧线） */
interface PlotPointFormValues {
  name: string;
  type: string;
  description: string;
  arc_id: string;
}

/** 字段行：label + 控件 */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px]">
      <span>{label}</span>
      {children}
    </label>
  );
}

/** 子实体对话框外壳（#649：三个对话框共用的遮罩/标题/主体/底部按钮布局） */
function DialogShell({
  title,
  testid,
  width,
  children,
  footer,
}: {
  title: string;
  testid: string;
  width: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div role="dialog" aria-modal="true" aria-label={title} data-testid={testid} className={`${width} rounded-lg border border-line bg-surface p-6 shadow-card`} onClick={(e) => e.stopPropagation()}>
        <h2 className="font-serif text-[18px] font-semibold">{title}</h2>
        <div className="mt-4 space-y-3">{children}</div>
        <div className="mt-6 flex justify-end gap-2">{footer}</div>
      </div>
    </div>
  );
}

/** 情节节点创建/编辑对话框（#649：编辑模式预填现值；名称必填 gate；保存中禁用防重复提交） */
function PlotPointDialog({ editing, arcs, saving, onSave, onCancel }: {
  editing: PlotPointDTO | null;
  arcs: StoryArcDTO[];
  saving: boolean;
  onSave: (values: PlotPointFormValues) => Promise<void> | void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(editing?.name ?? '');
  const [type, setType] = useState(editing?.type ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const [arcId, setArcId] = useState(editing?.arc_id !== null && editing?.arc_id !== undefined ? String(editing.arc_id) : '');
  const title = editing ? t('lib.point.editTitle') : t('lib.point.createTitle');
  const canSave = name.trim() !== '' && !saving;
  return (
    <DialogShell
      title={title}
      testid="outline-point-dialog"
      width="w-[460px]"
      footer={
        <>
          <button type="button" data-testid="outline-point-cancel" className={BTN_SECONDARY} onClick={onCancel}>
            {t('lib.point.cancel')}
          </button>
          <button
            type="button"
            data-testid="outline-point-save"
            disabled={!canSave}
            className={BTN_PRIMARY}
            onClick={() => void onSave({ name: name.trim(), type: type.trim(), description: description.trim(), arc_id: arcId })}
          >
            {saving ? t('lib.saving') : t('lib.point.save')}
          </button>
        </>
      }
    >
      <Field label={t('lib.point.name')}>
        <input data-testid="outline-point-name" aria-label={t('lib.point.name')} className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('lib.point.type')}>
        <input data-testid="outline-point-type" aria-label={t('lib.point.type')} className={INPUT_CLS} value={type} onChange={(e) => setType(e.target.value)} />
      </Field>
      <Field label={t('lib.point.desc')}>
        <textarea data-testid="outline-point-desc" aria-label={t('lib.point.desc')} rows={3} className={INPUT_CLS} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label={t('lib.point.arc')}>
        <select data-testid="outline-point-arc" aria-label={t('lib.point.arc')} className={INPUT_CLS} value={arcId} onChange={(e) => setArcId(e.target.value)}>
          <option value="">{t('lib.point.arcNone')}</option>
          {arcs.map((arc) => (
            <option key={String(arc.id)} value={String(arc.id)}>{arc.name ?? ''}</option>
          ))}
        </select>
      </Field>
    </DialogShell>
  );
}

/** 故事弧创建/编辑对话框（#649：名称必填 gate；编辑模式预填现值） */
function ArcDialog({ editing, saving, onSave, onCancel }: {
  editing: StoryArcDTO | null;
  saving: boolean;
  onSave: (values: { name: string; description: string }) => Promise<void> | void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(editing?.name ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const title = editing ? t('lib.arcs.editTitle') : t('lib.arcs.createTitle');
  const canSave = name.trim() !== '' && !saving;
  return (
    <DialogShell
      title={title}
      testid="outline-arc-dialog"
      width="w-[460px]"
      footer={
        <>
          <button type="button" data-testid="outline-arc-cancel" className={BTN_SECONDARY} onClick={onCancel}>
            {t('lib.arcs.cancel')}
          </button>
          <button
            type="button"
            data-testid="outline-arc-save"
            disabled={!canSave}
            className={BTN_PRIMARY}
            onClick={() => void onSave({ name: name.trim(), description: description.trim() })}
          >
            {saving ? t('lib.saving') : t('lib.arcs.save')}
          </button>
        </>
      }
    >
      <Field label={t('lib.arcs.name')}>
        <input data-testid="outline-arc-name" aria-label={t('lib.arcs.name')} className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('lib.arcs.desc')}>
        <textarea data-testid="outline-arc-desc" aria-label={t('lib.arcs.desc')} rows={3} className={INPUT_CLS} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
    </DialogShell>
  );
}

/** AI 生成大纲对话框（#649：name/prompt 均可选；进行中渲染 outline-generate-loading 反馈） */
function GenerateOutlineDialog({ saving, onSave, onCancel }: {
  saving: boolean;
  onSave: (values: { name: string; prompt: string }) => Promise<void> | void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  return (
    <DialogShell
      title={t('lib.generate.title')}
      testid="outline-generate-dialog"
      width="w-[520px]"
      footer={
        <>
          <button type="button" data-testid="outline-generate-cancel" className={BTN_SECONDARY} onClick={onCancel}>
            {t('lib.generate.cancel')}
          </button>
          <button
            type="button"
            data-testid="outline-generate-submit"
            disabled={saving}
            className={BTN_PRIMARY}
            onClick={() => void onSave({ name: name.trim(), prompt: prompt.trim() })}
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
            {saving ? t('lib.generate.loading') : t('lib.generate.submit')}
          </button>
        </>
      }
    >
      {saving && <div data-testid="outline-generate-loading" className="text-[12px] text-ink-2">{t('lib.generate.loading')}</div>}
      <Field label={t('lib.generate.name')}>
        <input data-testid="outline-generate-name" aria-label={t('lib.generate.name')} className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('lib.generate.prompt')}>
        <textarea data-testid="outline-generate-prompt" aria-label={t('lib.generate.prompt')} rows={4} className={INPUT_CLS} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
    </DialogShell>
  );
}

function OutlineNodeView({
  node,
  depth,
  collapsed,
  pointsByChapter,
  chapterTitles,
  onToggle,
  onEdit,
  onDelete,
  onAdd,
  onAddPoint,
  onEditPoint,
  onDeletePoint,
  onLinkChapter,
}: {
  node: OutlineTreeNode;
  depth: number;
  collapsed: Set<string | number>;
  pointsByChapter: Record<string, PlotPointDTO[]>;
  chapterTitles: Record<string, string>;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onAdd: () => void;
  onAddPoint: (outlineId: string | number) => void;
  onEditPoint: (point: PlotPointDTO) => void;
  onDeletePoint: (point: PlotPointDTO) => void;
  onLinkChapter: () => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  const level = normalizeLevel(item.level);
  const idStr = String(item.id);
  const isChapter = level === 'chapter';
  const points = isChapter ? (pointsByChapter[idStr] ?? []) : [];
  const hasChildren =
    children.length > 0 || (isChapter && ((item.point_count ?? 0) > 0 || points.length > 0));
  const isCollapsed = collapsed.has(item.id);
  const hasChapterRef = isChapter && item.chapter_id !== null && item.chapter_id !== undefined;
  const chapterTitle = hasChapterRef ? (chapterTitles[String(item.chapter_id)] ?? '') : '';
  return (
    <div data-testid={`outline-${level}-${item.id}`} className="tree-node">
      <div
        className="tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60"
        style={{ paddingLeft: depth * 18 + 12 }}
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`outline-toggle-${item.id}`}
            aria-label={isCollapsed ? t('nav.expand') : t('nav.collapse')}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onToggle(item.id)}
          >
            <ChevronRight
              className={cn('h-3.5 w-3.5 transition-transform duration-180', !isCollapsed && 'rotate-90')}
              aria-hidden="true"
            />
          </button>
        ) : (
          <span className="h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
          {t(`lib.level.${level}`)}
        </span>
        <span className="min-w-0 flex-1 truncate">{item.name ?? ''}</span>
        {isChapter &&
          (hasChapterRef ? (
            <span
              data-testid={`outline-chapter-ref-${item.id}`}
              title={t('lib.chapterRefTip')}
              className="inline-flex shrink-0 items-center gap-1 rounded-full border border-line bg-surface-3/60 px-2 py-0.5 text-[11px] text-ink-2"
            >
              <span aria-hidden="true">📎</span>
              {chapterTitle}
            </span>
          ) : (
            <button
              type="button"
              data-testid={`outline-chapter-link-${item.id}`}
              className="inline-flex shrink-0 items-center rounded-md border border-dashed border-accent/50 px-2 py-0.5 text-[11px] text-accent transition duration-150 hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={onLinkChapter}
            >
              {t('lib.chapterLink')}
            </button>
          ))}
        {level === 'overall' && (
          <button
            type="button"
            data-testid={`outline-add-volume-${item.id}`}
            aria-label={`${t('lib.addVolume')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAdd}
          >
            {t('lib.addVolume')}
          </button>
        )}
        {level === 'volume' && (
          <button
            type="button"
            data-testid={`outline-add-chapter-${item.id}`}
            aria-label={`${t('lib.addChapter')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAdd}
          >
            {t('lib.addChapter')}
          </button>
        )}
        {isChapter && (
          <button
            type="button"
            data-testid={`outline-add-point-${item.id}`}
            aria-label={`${t('lib.addPoint')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onAddPoint(item.id)}
          >
            {t('lib.addPoint')}
          </button>
        )}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            data-testid={`lib-edit-${item.id}`}
            aria-label={`${t('lib.edit')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onEdit(item)}
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`lib-delete-${item.id}`}
            aria-label={`${t('lib.delete')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onDelete(item)}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      {!isCollapsed &&
        children.map((child) => (
          <OutlineNodeView
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            collapsed={collapsed}
            pointsByChapter={pointsByChapter}
            chapterTitles={chapterTitles}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onAdd={onAdd}
            onAddPoint={onAddPoint}
            onEditPoint={onEditPoint}
            onDeletePoint={onDeletePoint}
            onLinkChapter={onLinkChapter}
          />
        ))}
      {isChapter && !isCollapsed && (
        <div style={{ paddingLeft: (depth + 1) * 18 + 12 }} className="py-1 pr-3">
          {points.length > 0 ? (
            <div className="space-y-1">
              {points.map((pt) => (
                <div
                  key={String(pt.id)}
                  data-testid={`outline-point-${pt.id}`}
                  className="group flex items-center gap-2 rounded-md bg-surface-2/50 px-2.5 py-1.5 text-[12px] text-ink"
                >
                  <span className="min-w-0 flex-1 truncate">{pt.name ?? ''}</span>
                  {pt.type ? (
                    <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-ink-2">
                      {pt.type}
                    </span>
                  ) : null}
                  <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      data-testid={`outline-point-edit-${pt.id}`}
                      aria-label={`${t('lib.edit')} ${pt.name ?? ''}`}
                      className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => onEditPoint(pt)}
                    >
                      <Pencil className="h-3 w-3" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      data-testid={`outline-point-del-${pt.id}`}
                      aria-label={`${t('lib.delete')} ${pt.name ?? ''}`}
                      className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => onDeletePoint(pt)}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md px-2.5 py-1.5 text-[12px] text-ink-3">{t('lib.empty.points')}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function OutlineTree({
  outlines,
  chapterTitles,
  onEdit,
  onDelete,
  onAdd,
  arcs,
  projectId,
  onOutlineGenerated,
}: OutlineTreeProps) {
  const { t } = useI18n();
  const roots = useMemo(() => buildOutlineTree(outlines), [outlines]);
  const [collapsed, setCollapsed] = useState<Set<string | number>>(new Set());
  const [pointsByChapter, setPointsByChapter] = useState<Record<string, PlotPointDTO[]>>({});
  const fetchedRef = useRef<Set<string>>(new Set());
  // #649：故事弧（情节点对话框弧线下拉 + 故事弧区）；优先外部 arcs prop，缺省按 projectId 拉取
  const [storyArcs, setStoryArcs] = useState<StoryArcDTO[]>(arcs ?? []);
  // #649：情节节点创建/编辑对话框（editing 非空 = 编辑模式预填）
  const [pointDialog, setPointDialog] = useState<{ outlineId: string | number; editing: PlotPointDTO | null } | null>(null);
  const [pointSaving, setPointSaving] = useState(false);
  const [pendingPointDelete, setPendingPointDelete] = useState<PlotPointDTO | null>(null);
  // #649：故事弧创建/编辑/删除
  const [arcDialog, setArcDialog] = useState<{ editing: StoryArcDTO | null } | null>(null);
  const [arcSaving, setArcSaving] = useState(false);
  const [pendingArcDelete, setPendingArcDelete] = useState<StoryArcDTO | null>(null);
  // #649：AI 生成
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generating, setGenerating] = useState(false);

  const fetchPlotPoints = useCallback(async (chapterId: string | number) => {
    const key = String(chapterId);
    if (fetchedRef.current.has(key)) return;
    fetchedRef.current.add(key);
    try {
      const data = await apiFetch<{ items?: PlotPointDTO[] }>(`/api/v1/outlines/${key}/plot-points`);
      setPointsByChapter((prev) => ({ ...prev, [key]: data.items ?? [] }));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
      setPointsByChapter((prev) => ({ ...prev, [key]: [] }));
    }
  }, []);

  // 情节点按需拉取：默认全展开 → 挂载即拉；收起再展开不重拉（本地缓存，O8 契约）
  useEffect(() => {
    const visit = (nodes: OutlineTreeNode[]) => {
      for (const node of nodes) {
        const level = normalizeLevel(node.item.level);
        const id = node.item.id;
        if (level === 'chapter' && (node.item.point_count ?? 0) > 0 && !collapsed.has(id)) {
          void fetchPlotPoints(id);
        }
        if (!collapsed.has(id)) visit(node.children);
      }
    };
    visit(roots);
  }, [roots, collapsed, fetchPlotPoints]);

  // #649：故事弧拉取（projectId 变化时刷新；CRUD 成功后本地回写，无需整表重拉）
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void apiFetch<{ items?: StoryArcDTO[] }>(`/api/v1/projects/${projectId}/story-arcs`)
      .then((data) => {
        if (!cancelled) setStoryArcs(data.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setStoryArcs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const toggleCollapsed = (id: string | number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleLinkChapter = () => {
    useToastStore.getState().pushToast('warn', t('lib.chapterLinkPick'));
  };

  const handleAdd = () => onAdd?.();

  // #649：情节节点保存——创建 POST /outlines/{id}/plot-points；编辑 PATCH 仅变化字段；成功后刷新该章情节点
  const handlePointSave = async (values: PlotPointFormValues) => {
    if (!pointDialog) return;
    const { outlineId, editing } = pointDialog;
    setPointSaving(true);
    try {
      if (editing) {
        const body: Record<string, unknown> = {};
        if (values.name !== (editing.name ?? '')) body.name = values.name;
        if (values.type !== (editing.type ?? '')) body.type = values.type;
        if (values.description !== (editing.description ?? '')) body.description = values.description;
        const prevArc =
          editing.arc_id === null || editing.arc_id === undefined ? '' : String(editing.arc_id);
        if (values.arc_id !== prevArc) body.arc_id = values.arc_id;
        if (Object.keys(body).length > 0) {
          await apiFetch(`/api/v1/plot-points/${editing.id}`, { method: 'PATCH', body });
        }
      } else {
        const body: Record<string, unknown> = { name: values.name };
        if (values.type) body.type = values.type;
        if (values.description) body.description = values.description;
        if (values.arc_id) body.arc_id = values.arc_id;
        await apiFetch(`/api/v1/outlines/${outlineId}/plot-points`, { method: 'POST', body });
      }
      setPointDialog(null);
      // 强制刷新该大纲情节点（fetchedRef 移除 key → 重新拉取，新点/编辑/删除出现在树内）
      fetchedRef.current.delete(String(outlineId));
      void fetchPlotPoints(outlineId);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    } finally {
      setPointSaving(false);
    }
  };

  // #649：情节节点删除（真删 → 刷新该大纲情节点，行消失）
  const handlePointDelete = async () => {
    if (!pendingPointDelete) return;
    const point = pendingPointDelete;
    try {
      await apiFetch(`/api/v1/plot-points/${point.id}`, { method: 'DELETE' });
      setPendingPointDelete(null);
      if (point.outline_id !== null && point.outline_id !== undefined) {
        fetchedRef.current.delete(String(point.outline_id));
        void fetchPlotPoints(point.outline_id);
      }
    } catch (err) {
      setPendingPointDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  // #649：故事弧保存——创建 POST /projects/{pid}/story-arcs；编辑 PATCH 仅变化字段；成功本地回写
  const handleArcSave = async (values: { name: string; description: string }) => {
    if (!projectId) return;
    setArcSaving(true);
    try {
      if (arcDialog?.editing) {
        const arc = arcDialog.editing;
        const body: Record<string, unknown> = {};
        if (values.name !== (arc.name ?? '')) body.name = values.name;
        if (values.description !== (arc.description ?? '')) body.description = values.description;
        if (Object.keys(body).length > 0) {
          const updated = await apiFetch<StoryArcDTO>(`/api/v1/story-arcs/${arc.id}`, {
            method: 'PATCH',
            body,
          });
          setStoryArcs((prev) =>
            prev.map((a) => (String(a.id) === String(arc.id) ? { ...a, ...updated } : a)),
          );
        }
      } else {
        const body: Record<string, unknown> = { name: values.name };
        if (values.description) body.description = values.description;
        const created = await apiFetch<StoryArcDTO>(`/api/v1/projects/${projectId}/story-arcs`, {
          method: 'POST',
          body,
        });
        // 幂等追加（dev 下 React 可能双次应用 updater；按 id 去重防重复行）
        setStoryArcs((prev) =>
          prev.some((a) => String(a.id) === String(created.id)) ? prev : [...prev, created],
        );
      }
      setArcDialog(null);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    } finally {
      setArcSaving(false);
    }
  };

  // #649：故事弧删除（真删 → 本地移除，行消失）
  const handleArcDelete = async () => {
    if (!pendingArcDelete) return;
    const arc = pendingArcDelete;
    try {
      await apiFetch(`/api/v1/story-arcs/${arc.id}`, { method: 'DELETE' });
      setPendingArcDelete(null);
      setStoryArcs((prev) => prev.filter((a) => String(a.id) !== String(arc.id)));
    } catch (err) {
      setPendingArcDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  // #649：AI 生成（A 方案：生成到新大纲，save:true；成功 toast + 回调父级插树顶；失败 err toast）
  const handleGenerate = async (values: { name: string; prompt: string }) => {
    if (!projectId) return;
    setGenerating(true);
    try {
      const body: Record<string, unknown> = { project_id: projectId, save: true };
      if (values.name) body.name = values.name;
      if (values.prompt) body.prompt = values.prompt;
      const result = await apiFetch<{ outline?: OutlineItemDTO }>('/api/v1/outlines/generate', {
        method: 'POST',
        body,
      });
      useToastStore.getState().pushToast('ok', t('lib.generate.done'));
      setGenerateOpen(false);
      if (result?.outline) onOutlineGenerated?.(result.outline);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <>
      <div
        data-testid="library-list"
        className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
      >
        {/* #649：大纲 tab 顶部工具栏——AI 生成（进行中禁用 + 转圈反馈） */}
        {projectId && (
          <div className="flex items-center justify-end gap-2 border-b border-line px-4 py-2.5">
            <button
              type="button"
              data-testid="library-ai-generate"
              disabled={generating}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => setGenerateOpen(true)}
            >
              {generating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Wand2 className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {t('lib.aiGenerate')}
            </button>
          </div>
        )}
        <div data-testid="outline-tree" className="divide-y divide-line">
          {roots.length === 0 ? (
            <div className="px-4 py-8 text-center text-[13px] text-ink-2">{t('common.empty')}</div>
          ) : (
            roots.map((node) => (
              <OutlineNodeView
                key={String(node.item.id)}
                node={node}
                depth={0}
                collapsed={collapsed}
                pointsByChapter={pointsByChapter}
                chapterTitles={chapterTitles}
                onToggle={toggleCollapsed}
                onEdit={onEdit}
                onDelete={onDelete}
                onAdd={handleAdd}
                onAddPoint={(outlineId) => setPointDialog({ outlineId, editing: null })}
                onEditPoint={(pt) => setPointDialog({ outlineId: pt.outline_id ?? '', editing: pt })}
                onDeletePoint={setPendingPointDelete}
                onLinkChapter={handleLinkChapter}
              />
            ))
          )}
        </div>
        {/* #649：故事弧区（独立面板；空态「暂无故事弧」） */}
        {projectId && (
          <div data-testid="outline-arcs" className="border-t border-line">
            <div className="flex items-center justify-between px-4 py-3">
              <h3 className="font-serif text-[15px] font-semibold">{t('lib.arcs.title')}</h3>
              <button
                type="button"
                data-testid="outline-arc-create"
                className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setArcDialog({ editing: null })}
              >
                {t('lib.arcs.create')}
              </button>
            </div>
            {storyArcs.length === 0 ? (
              <div className="border-t border-line px-4 py-8 text-center text-[13px] text-ink-2">
                {t('lib.arcs.empty')}
              </div>
            ) : (
              <div className="divide-y divide-line border-t border-line">
                {storyArcs.map((arc) => (
                  <div
                    key={String(arc.id)}
                    data-testid={`outline-arc-${arc.id}`}
                    className="group flex items-center gap-2 px-4 py-2.5 text-[13px] text-ink"
                  >
                    <span className="min-w-0 flex-1 truncate">{arc.name ?? ''}</span>
                    <span
                      data-testid={`outline-arc-count-${arc.id}`}
                      className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
                    >
                      {arc.point_count ?? 0}
                    </span>
                    <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                      <button
                        type="button"
                        data-testid={`outline-arc-edit-${arc.id}`}
                        aria-label={`${t('lib.edit')} ${arc.name ?? ''}`}
                        className="rounded p-1.5 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setArcDialog({ editing: arc })}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        data-testid={`outline-arc-del-${arc.id}`}
                        aria-label={`${t('lib.delete')} ${arc.name ?? ''}`}
                        className="rounded p-1.5 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setPendingArcDelete(arc)}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 情节节点创建/编辑对话框 + 删除确认 */}
      {pointDialog && (
        <PlotPointDialog
          editing={pointDialog.editing}
          arcs={storyArcs}
          saving={pointSaving}
          onSave={handlePointSave}
          onCancel={() => setPointDialog(null)}
        />
      )}
      {pendingPointDelete && (
        <ConfirmDialog
          open
          title={t('lib.point.deleteTitle')}
          message={t('lib.point.deleteConfirm', { name: pendingPointDelete.name ?? '' })}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="outline-point-confirm"
          onConfirm={() => void handlePointDelete()}
          onOpenChange={(open) => {
            if (!open) setPendingPointDelete(null);
          }}
        />
      )}

      {/* 故事弧创建/编辑对话框 + 删除确认 */}
      {arcDialog && (
        <ArcDialog
          editing={arcDialog.editing}
          saving={arcSaving}
          onSave={handleArcSave}
          onCancel={() => setArcDialog(null)}
        />
      )}
      {pendingArcDelete && (
        <ConfirmDialog
          open
          title={t('lib.arcs.deleteTitle')}
          message={t('lib.arcs.deleteConfirm', { name: pendingArcDelete.name ?? '' })}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="outline-arc-confirm"
          onConfirm={() => void handleArcDelete()}
          onOpenChange={(open) => {
            if (!open) setPendingArcDelete(null);
          }}
        />
      )}

      {/* AI 生成对话框 */}
      {generateOpen && (
        <GenerateOutlineDialog
          saving={generating}
          onSave={handleGenerate}
          onCancel={() => setGenerateOpen(false)}
        />
      )}
    </>
  );
}
