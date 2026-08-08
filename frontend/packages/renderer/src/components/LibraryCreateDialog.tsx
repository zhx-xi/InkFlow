/**
 * 设定库分类实体手动创建对话框（#196，specs/f36-library-manual-create/spec.md §2.2/§2.3）：
 * 受控表单对话框，字段按分类渲染（后端 DTO 字段名对齐 spec §2.1 表）；
 * 名称/标题必填（strip 后非空 → 保存按钮 enabled）；保存中禁用防重复提交；
 * 关闭路径 = 取消 / ESC / 成功后父级关闭（#195 拍板：遮罩点击不关闭）。
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';

export type LibraryCreateCat = 'characters' | 'world' | 'outline' | 'timeline' | 'foreshadow';

export interface LibraryCreateDialogProps {
  open: boolean;
  cat: LibraryCreateCat;
  onCreate: (input: Record<string, unknown>) => Promise<void>;
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

export function LibraryCreateDialog({ open, cat, onCreate, onOpenChange }: LibraryCreateDialogProps) {
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
  const [saving, setSaving] = useState(false);

  // 打开时重置表单（分类切换重开场景；保存失败时不清空已填内容，可修改重试）
  useEffect(() => {
    if (!open) return;
    setName('');
    setTitle('');
    setDescription('');
    setPersonality('');
    setBackground('');
    setGoals('');
    setCategory('');
    setContent('');
    setTimeDisplay('');
    setPriority(50);
    setLocation('');
    setSaving(false);
  }, [open, cat]);

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
  const canSave = requiredValue !== '' && !saving;

  const buildBody = (): Record<string, unknown> => {
    switch (cat) {
      case 'characters':
        return { name: name.trim(), personality, background, goals };
      case 'world':
        return { name: name.trim(), category, content };
      case 'outline':
        return { name: name.trim(), description };
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
      await onCreate(buildBody());
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
        aria-label={t(`lib.create.title.${cat}`)}
        data-testid="library-create-dialog"
        className="max-h-[85vh] w-[520px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t(`lib.create.title.${cat}`)}</h2>
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
              <Field label={t('lib.create.category')}>
                <input
                  aria-label={t('lib.create.category')}
                  className={INPUT_CLS}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                />
              </Field>
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
            {t('lib.create.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
