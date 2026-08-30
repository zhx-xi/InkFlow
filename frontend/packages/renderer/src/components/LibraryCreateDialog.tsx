/**
 * 设定库分类实体创建/编辑对话框（#196 + F43 双模式扩展，
 * specs/f36-library-manual-create/spec.md §2.2/§2.3 + specs/f43-setting-library-gui/spec.md §2.2）：
 * 受控表单对话框，字段按分类渲染（后端 DTO 字段名对齐 spec §2.1 表）；
 * editing 非空 = 编辑模式（打开预填现值），空 = 创建模式（空表单重置，#196）；
 * 名称/标题必填（strip 后非空 → 保存按钮 enabled）；保存中禁用防重复提交；
 * 关闭路径 = 取消 / ESC / 成功后父级关闭（#195 拍板：遮罩点击不关闭）。
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { TagEditor } from './TagEditor';

export type LibraryCreateCat = 'characters' | 'world' | 'outline' | 'timeline' | 'foreshadow';

/** 五分类列表项完整 DTO（F43 §2.1：后端领域模型字段对齐，缺失字段兜底 ''） */
export interface LibraryItemDTO {
  id: string | number;
  name?: string; // characters/world/outline
  title?: string; // timeline/foreshadow
  personality?: string; // characters
  background?: string; // characters
  goals?: string; // characters
  category?: string; // world
  content?: string; // world
  description?: string; // outline/timeline/foreshadow
  time_display?: string; // timeline
  priority?: number; // foreshadow
  location?: string; // foreshadow
  // ── F43 P1 新增 ──
  parent_id?: string | number | null; // world：F35 父节点（null=顶层）
  extra?: Record<string, unknown>; // characters：role_rank / groups 承载（spec §2.1）
}

export interface LibraryCreateDialogProps {
  open: boolean;
  cat: LibraryCreateCat;
  /** #722: root world create - hide the category input (roots should have no category) */
  isRoot?: boolean;
  /** F43：非空 = 编辑模式（预填现值），空 = 创建模式（#196 行为） */
  editing?: LibraryItemDTO | null;
  /** F43 P1：建议标签 = 当前项目角色 extra.groups 并集（父级聚合，D-13 数据驱动） */
  tagSuggestions?: string[];
  /** #568：world 选中分类时预填类别（创建子条目）；编辑模式优先 editing.category */
  initialCategory?: string;
  /** #675：outline 创建上下文——层级预填（overall/volume/chapter） */
  initialLevel?: 'overall' | 'volume' | 'chapter';
  /** #675：outline 创建上下文——父级 id（＋卷 → parent=overall；＋章细纲 → parent=volume；＋整本 → null） */
  initialParentId?: string | number | null;
  /** F43：onCreate 改名 onSave——语义 = 保存回调，父级分支 PATCH/POST */
  onSave: (input: Record<string, unknown>) => Promise<void>;
  onOpenChange: (open: boolean) => void;
}

/** 字段行：label 文案 + 控件（label/aria-label 双关联，测试 getByLabelText 契约） */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px]">
      <span>{label}</span>
      {children}
    </label>
  );
}

const INPUT_CLS =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent';

/** 五档角色等级（D1 拍板；存 extra.role_rank，spec §2.2） */
const ROLE_RANKS = [
  { key: 'protagonist', labelKey: 'lib.rank.protagonist' },
  { key: 'major', labelKey: 'lib.rank.major' },
  { key: 'minor', labelKey: 'lib.rank.minor' },
  { key: 'scene', labelKey: 'lib.rank.scene' },
  { key: 'walkon', labelKey: 'lib.rank.walkon' },
] as const;

export function LibraryCreateDialog({
  open,
  cat,
  editing = null,
  tagSuggestions = [],
  initialCategory,
  initialLevel,
  initialParentId,
  isRoot,
  onSave,
  onOpenChange,
}: LibraryCreateDialogProps) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [personality, setPersonality] = useState('');
  const [background, setBackground] = useState('');
  const [goals, setGoals] = useState('');
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [timeDisplay, setTimeDisplay] = useState('');
  const [priority, setPriority] = useState(50);
  const [location, setLocation] = useState('');
  // #675：outline 层级（overall/volume/chapter，创建对话框内可切换；初始值来自父级上下文）
  const [level, setLevel] = useState<'overall' | 'volume' | 'chapter'>('overall');
  const levelOptions: ('overall' | 'volume' | 'chapter')[] =
    initialLevel === 'overall'
      ? ['overall']
      : initialLevel === 'volume' || initialLevel === 'chapter'
        ? ['volume', 'chapter']
        : ['overall', 'volume', 'chapter'];
  // F43 P1：角色等级（D1 必填无默认，初始 '' → 保存 gate 拦截）+ 分组标签（D2）
  const [rank, setRank] = useState('');
  const [rankTags, setRankTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // 打开时初始化表单：editing 非空 → 预填现值（?? '' 兜底，spec E5）；
  // editing 为空 → 重置空表单（保持 #196 行为）；保存失败时不清空已填内容，可修改重试
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? '');
    setTitle(editing?.title ?? '');
    setDescription(editing?.description ?? '');
    setPersonality(editing?.personality ?? '');
    setBackground(editing?.background ?? '');
    setGoals(editing?.goals ?? '');
    setCategory(editing?.category ?? initialCategory ?? '');
    setContent(editing?.content ?? '');
    setTimeDisplay(editing?.time_display ?? '');
    setPriority(editing?.priority ?? 50);
    setLocation(editing?.location ?? '');
    setLevel(initialLevel ?? 'overall');
    // F43 P1：等级预填 editing.extra.role_rank ?? ''（旧数据无等级 → 占位重选，E14）；
    // 标签预填 extra.groups（非数组兜底 []，E26），去重保序
    setRank(String(editing?.extra?.role_rank ?? ''));
    const groups = editing?.extra?.groups;
    setRankTags(
      Array.isArray(groups)
        ? [...new Set(groups.filter((g): g is string => typeof g === 'string').map((g) => g.trim()).filter(Boolean))]
        : [],
    );
    setSaving(false);
  }, [open, cat, editing, initialCategory, initialLevel]);

  // ESC 关闭（尊重 Radix Select 等已 preventDefault 的 Escape；参照 TemplateDialog 既有交互）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const requiredValue = cat === 'timeline' || cat === 'foreshadow' ? title.trim() : name.trim();
  // F43 P1（D1）：角色分类等级必填无默认——名称/标题 + 等级双必填才 enabled（E13）
  const canSave = requiredValue !== '' && !saving && (cat !== 'characters' || rank !== '');

  // #568：world 新建模式下选中分类时用「创建分类」标题（语义 = 在选中分类下创建子条目）
  const titleKey = editing
    ? `lib.edit.title.${cat}`
    : cat === 'world' && initialCategory
      ? 'lib.create.title.worldCategory'
      : `lib.create.title.${cat}`;

  const buildBody = (): Record<string, unknown> => {
    switch (cat) {
      case 'characters':
        // F43 P1（spec §3.2）：创建/编辑均发送完整 extra { role_rank, groups }（整体替换语义防丢字段）
        return {
          name: name.trim(),
          personality,
          background,
          goals,
          extra: { role_rank: rank, groups: rankTags },
        };
      case 'world':
        return { name: name.trim(), category, content };
      case 'outline':
        return { name: name.trim(), description, level, parent_id: initialParentId ?? null };
      case 'timeline':
        return { title: title.trim(), time_display: timeDisplay, description };
      case 'foreshadow':
        return { title: title.trim(), priority, location, description };
    }
  };

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await onSave(buildBody());
      // 成功后由父级关闭对话框 + 刷新列表
    } catch {
      // 保存失败：按钮恢复 + 对话框保持（错误提示由父级 toast 处理）
    } finally {
      setSaving(false);
    }
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t(titleKey)}
        data-testid="library-create-dialog"
        className="max-h-[85vh] w-[520px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {t(titleKey)}
        </h2>
        <div className="mt-4 space-y-4">
          {cat === 'characters' && (
            <>
              <Field label={t('lib.create.name')}>
                <input
                  data-testid="library-create-name"
                  aria-label={t('lib.create.name')}
                  className={INPUT_CLS}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.personality')}>
                <textarea
                  aria-label={t('lib.create.personality')}
                  rows={3}
                  className={INPUT_CLS}
                  value={personality}
                  onChange={(e) => setPersonality(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.background')}>
                <textarea
                  aria-label={t('lib.create.background')}
                  rows={3}
                  className={INPUT_CLS}
                  value={background}
                  onChange={(e) => setBackground(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.goals')}>
                <textarea
                  aria-label={t('lib.create.goals')}
                  rows={3}
                  className={INPUT_CLS}
                  value={goals}
                  onChange={(e) => setGoals(e.target.value)}
                />
              </Field>
              {/* F43 P1：角色等级下拉（shadcn Select，D1 必填无默认）+ 分组标签编辑器（D2） */}
              <Field label={t('lib.rank.label')}>
                <Select
                  value={rank}
                  onValueChange={(v) => setRank(v)}
                >
                  <SelectTrigger data-testid="library-create-rank" aria-label={t('lib.rank.label')}>
                    <SelectValue placeholder={t('lib.rank.placeholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_RANKS.map((r) => (
                      <SelectItem key={r.key} value={r.key}>
                        {t(r.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <TagEditor selected={rankTags} suggestions={tagSuggestions} onChange={setRankTags} />
            </>
          )}

          {cat === 'world' && (
            <>
              <Field label={t('lib.create.name')}>
                <input
                  data-testid="library-create-name"
                  aria-label={t('lib.create.name')}
                  className={INPUT_CLS}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              {!isRoot && (
                <Field label={t('lib.create.category')}>
                  <input
                    aria-label={t('lib.create.category')}
                    className={INPUT_CLS}
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  />
                </Field>
              )}
              <Field label={t('lib.create.content')}>
                <textarea
                  aria-label={t('lib.create.content')}
                  rows={3}
                  className={INPUT_CLS}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                />
              </Field>
            </>
          )}

          {cat === 'outline' && (
            <>
              <Field label={t('lib.create.level')}>
                <select
                  data-testid="library-create-level"
                  aria-label={t('lib.create.level')}
                  className={INPUT_CLS}
                  value={level}
                  onChange={(e) => setLevel(e.target.value as 'overall' | 'volume' | 'chapter')}
                >
                  {levelOptions.map((v) => (
                    <option key={v} value={v}>
                      {t(`lib.level.${v}`)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('lib.create.name')}>
                <input
                  data-testid="library-create-name"
                  aria-label={t('lib.create.name')}
                  className={INPUT_CLS}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.description')}>
                <textarea
                  aria-label={t('lib.create.description')}
                  rows={3}
                  className={INPUT_CLS}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </>
          )}

          {cat === 'timeline' && (
            <>
              <Field label={t('lib.create.titleField')}>
                <input
                  data-testid="library-create-name"
                  aria-label={t('lib.create.titleField')}
                  className={INPUT_CLS}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.timeDisplay')}>
                <input
                  aria-label={t('lib.create.timeDisplay')}
                  className={INPUT_CLS}
                  value={timeDisplay}
                  onChange={(e) => setTimeDisplay(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.description')}>
                <textarea
                  aria-label={t('lib.create.description')}
                  rows={3}
                  className={INPUT_CLS}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </>
          )}

          {cat === 'foreshadow' && (
            <>
              <Field label={t('lib.create.titleField')}>
                <input
                  data-testid="library-create-name"
                  aria-label={t('lib.create.titleField')}
                  className={INPUT_CLS}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.priority')}>
                <input
                  type="number"
                  min={0}
                  max={100}
                  aria-label={t('lib.create.priority')}
                  className={INPUT_CLS}
                  value={priority}
                  onChange={(e) => setPriority(Number(e.target.value))}
                />
              </Field>
              <Field label={t('lib.create.location')}>
                <input
                  aria-label={t('lib.create.location')}
                  className={INPUT_CLS}
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </Field>
              <Field label={t('lib.create.description')}>
                <textarea
                  aria-label={t('lib.create.description')}
                  rows={3}
                  className={INPUT_CLS}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="library-create-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('lib.create.cancel')}
          </button>
          <button
            type="button"
            data-testid="library-create-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSave}
            onClick={() => void handleSave()}
          >
            {editing ? t('lib.edit.save') : t('lib.create.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
