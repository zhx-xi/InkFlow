/**
 * F43 #649/#676/#677 大纲子项对话框集合（自 OutlineTree.tsx 拆分，满足 monster-file ≤900 行护栏）：
 * 情节点创建/编辑、故事弧创建/编辑、AI 生成大纲、章节关联选择器；
 * 仅被 OutlineTree.tsx 使用，不依赖 OutlineItemDTO（ChapterLinkDialog 走 titles/onPick 契约）。
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

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

export const INPUT_CLS =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent';
export const BTN_SECONDARY =
  'rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3';
export const BTN_PRIMARY =
  'rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50';

/** 情节点表单值（对话框内受控状态；arc_id 空串 = 不挂弧线） */
export interface PlotPointFormValues {
  name: string;
  type: string;
  description: string;
  arc_id: string;
}

/** 字段行：label + 控件 */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px]">
      <span>{label}</span>
      {children}
    </label>
  );
}

/** 子实体对话框外壳（#649：三个对话框共用的遮罩/标题/主体/底部按钮布局） */
export function DialogShell({
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
export function PlotPointDialog({ editing, arcs, saving, onSave, onCancel }: {
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
export function ArcDialog({ editing, saving, onSave, onCancel }: {
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
export function GenerateOutlineDialog({ saving, onSave, onCancel }: {
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
      {saving && (
        <div data-testid="outline-generate-progress" className="rounded-md border border-line bg-surface-2/50 px-3 py-2 text-[12px] text-ink-2">
          <div data-testid="outline-generate-stage">{t('lib.generate.progressStage')}</div>
          <div data-testid="outline-generate-count">{t('lib.generate.progressCount', { n: 0 })}</div>
        </div>
      )}
      <Field label={t('lib.generate.name')}>
        <input data-testid="outline-generate-name" aria-label={t('lib.generate.name')} className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={t('lib.generate.prompt')}>
        <textarea data-testid="outline-generate-prompt" aria-label={t('lib.generate.prompt')} rows={4} className={INPUT_CLS} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
    </DialogShell>
  );
}

/** 章节关联选择器（#676：解除 D9 占位——列出 chapterTitles，选择后 PATCH chapter_id） */
export function ChapterLinkDialog({ titles, saving, onPick, onCancel }: {
  titles: Record<string, string>;
  saving: boolean;
  onPick: (chapterId: string) => Promise<void> | void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  return (
    <DialogShell
      title={t('lib.chapterLinkPick')}
      testid="chapter-link-dialog"
      width="w-[420px]"
      footer={
        <button type="button" data-testid="chapter-link-cancel" className={BTN_SECONDARY} onClick={onCancel}>
          {t('dlg.cancel')}
        </button>
      }
    >
      <div className="max-h-[55vh] space-y-2 overflow-y-auto">
        {Object.entries(titles).map(([id, title]) => (
          <button
            key={id}
            type="button"
            data-testid={`chapter-link-option-${id}`}
            disabled={saving}
            className="w-full rounded-md border border-line bg-surface-2/50 px-3 py-2 text-left text-[13px] text-ink transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void onPick(id)}
          >
            {title}
          </button>
        ))}
      </div>
    </DialogShell>
  );
}
