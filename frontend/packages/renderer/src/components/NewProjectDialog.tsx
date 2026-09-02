/** 新建项目对话框（spec §4.2.2）：书名必填 1-100 / tags 多选 + 自定义新增（#595 D7=A）/ 语言 / 目标字数默认 800000
 * #189：目标字数初始值读全局 default_words（方案 A 闭环）；#195：清空可重输 + 遮罩点击不关闭 */
import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage, fetchSettings } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { useTagsStore } from '../stores/tags';
import { useTemplatesStore } from '../stores/templates';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

/** S3e F3：框内可聚焦元素（初始焦点 + Tab 焦点陷阱共用；过滤 disabled / aria-hidden 元素） */
function getDialogFocusables(dialog: HTMLElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.getAttribute('aria-hidden') !== 'true');
}

const LANGUAGES = ['zh-CN', 'en'];

export interface NewProjectDialogProps {
  onClose: () => void;
}

export function NewProjectDialog({ onClose }: NewProjectDialogProps) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const createProject = useProjectStore((s) => s.createProject);
  const templates = useTemplatesStore((s) => s.templates);
  const loadTemplates = useTemplatesStore((s) => s.loadTemplates);
  const [name, setName] = useState('');
  // #595：tags 多选（自由多值；预设建议来自轻量注册表 stores/tags.ts）
  const tagSuggestions = useTagsStore((s) => s.suggestions);
  const [tags, setTags] = useState<string[]>([]);
  const [tagsInput, setTagsInput] = useState('');
  const [language, setLanguage] = useState('zh-CN');
  // #195：目标字数用字符串本地 state——type="number" + Number('')=0 会让清空瞬间变 '0'，
  // 无法重输（rc3 复验）；字符串态允许清空显示 ''，提交时再 Number 转换
  const [targetWordsInput, setTargetWordsInput] = useState('800000');
  // #189：fetchSettings 异步返回不得覆盖用户已输入值（仅在未改动时注入全局默认）
  const targetWordsEditedRef = useRef(false);
  // #107：Agent 模板选择（null = 默认模板，POST body 不含 template_id）
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // #105 修复批：submitting 防双重提交；in-flight 时 ESC 忽略关闭路径（防误关丢进度）
  const [submitting, setSubmitting] = useState(false);

  // §6.2③ 焦点归还：记录打开时 activeElement，任意关闭路径（ESC/取消/创建成功）卸载后归还触发按钮
  const returnFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      returnFocusRef.current?.focus();
    };
  }, []);

  // #107：挂载时拉取模板列表（测试内假 store loadTemplates no-op 兼容；幂等守卫允许）
  useEffect(() => {
    if (templates.length === 0) void loadTemplates();
  }, [loadTemplates, templates.length]);

  // #595：预设建议 = 轻量注册表（本项目已用 tags ∪ 旧 genre 枚举值；纯前端聚合，无网络）
  useEffect(() => {
    useTagsStore.getState().loadSuggestions(useProjectStore.getState().projects);
  }, []);

  // #189（方案 A 闭环）：挂载时读全局 default_words 作为目标字数初始值；
  // fetch 失败保持 800000 兜底（初始 state 即兜底值）；用户已输入 → 不覆盖
  useEffect(() => {
    let cancelled = false;
    void fetchSettings()
      .then((settings) => {
        if (cancelled || targetWordsEditedRef.current) return;
        const v = typeof settings.default_words === 'number' ? settings.default_words : 800000;
        setTargetWordsInput(String(v));
      })
      .catch(() => {
        /* #189：读取失败保持 800000 兜底 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // §6.2③ ESC 键关闭：document 级监听覆盖对话框内任意焦点；
  // 忽略 Radix Select 等已 preventDefault 的 Escape（如下拉面板开启时只关面板不关对话框）；
  // #105 修复批：in-flight（submitting）时按 ESC 保持打开
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && !submitting) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, submitting]);

  // S3e F3：打开（挂载）后初始焦点落入框内（书名输入为首个可聚焦控件）
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusables = getDialogFocusables(dialog);
    (focusables[0] ?? dialog).focus();
  }, []);

  /** S3e F3：Tab 焦点陷阱——焦点在首/尾元素（或逃出框内）时回绕，不逃出对话框 */
  const handleDialogKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusables = getDialogFocusables(dialog);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey) {
      if (active === first || !dialog.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else if (active === last || !dialog.contains(active)) {
      e.preventDefault();
      first.focus();
    }
  };

  const handleCreate = async () => {
    if (submitting) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t('dlg.nameRequired'));
      return;
    }
    if (trimmed.length > 100) {
      setError(t('dlg.nameTooLong'));
      return;
    }
    if (tags.length === 0) {
      setError(t('dlg.tagRequired'));
      return;
    }
    setError(null);
    setSubmitting(true);
    // #195：提交时字符串 → 数字——空串 → 0（Number('')=0）；非法（非数字）→ 800000 默认兜底
    const parsedTargetWords = Number(targetWordsInput);
    const targetWords = Number.isFinite(parsedTargetWords) ? parsedTargetWords : 800000;
    try {
      await createProject({
        name: trimmed,
        tags,
        language,
        target_words: targetWords,
        ...(templateId != null ? { template_id: templateId } : {}),
      });
      navigate('/writing');
    } catch (err) {
      // §6.3② 创建失败内联展示（复用既有 error 区域），对话框保持打开可修改重试
      setError(t('dlg.createFailed', { reason: errorMessage(err) }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('dlg.newTitle')}
        tabIndex={-1}
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleDialogKeyDown}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('dlg.newTitle')}</h2>
        <div className="mt-4 space-y-3">
          <label htmlFor="new-project-name" className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.name')}</span>
            <input
              id="new-project-name"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('dlg.namePlaceholder')}
            />
          </label>
          {error && <div className="text-[13px] text-err">{error}</div>}
          <div className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.tags')}</span>
            {/* 已选 tags chips（每 chip 可移除，#595） */}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    data-testid={`tags-chip-${tag}`}
                    className="inline-flex items-center gap-1 rounded-full bg-surface-3 px-2.5 py-0.5 text-[12px] text-ink"
                  >
                    {tag}
                    <button
                      type="button"
                      aria-label={tag}
                      className="flex h-4 w-4 items-center justify-center rounded-full text-ink-3 transition duration-150 hover:bg-surface hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => setTags((prev) => prev.filter((x) => x !== tag))}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            {/* 预设标签多选（Radix Select，点选切换选中态） */}
            <Select
              onValueChange={(v) =>
                setTags((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]))
              }
            >
              <SelectTrigger data-testid="tags-select" aria-label={t('dlg.tags')} className="w-full">
                <SelectValue placeholder={t('dlg.tagsPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {tagSuggestions.map((tag) => (
                  <SelectItem key={tag} value={tag}>
                    {tag}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* 自定义新增：输入 + Enter 确认（去重、非空） */}
            <input
              data-testid="tags-input"
              aria-label={t('dlg.addTag')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              placeholder={t('dlg.tagsPlaceholder')}
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter') return;
                e.preventDefault();
                const tag = tagsInput.trim();
                if (!tag || tags.includes(tag)) return;
                setTags((prev) => [...prev, tag]);
                setTagsInput('');
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.lang')}</span>
            <Select
              value={language}
              onValueChange={(v) => setLanguage(v)}
            >
              <SelectTrigger aria-label={t('dlg.lang')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGES.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.template')}</span>
            <Select
              value={templateId != null ? String(templateId) : 'default'}
              onValueChange={(v) => setTemplateId(v === 'default' ? null : Number(v))}
            >
              <SelectTrigger aria-label={t('dlg.template')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">{t('dlg.templateDefault')}</SelectItem>
                {templates.map((tp) => (
                  <SelectItem key={tp.id} value={String(tp.id)}>
                    {tp.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <label htmlFor="new-project-target" className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.targetWords')}</span>
            <input
              id="new-project-target"
              type="number"
              min={0}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none"
              value={targetWordsInput}
              onChange={(e) => {
                targetWordsEditedRef.current = true;
                setTargetWordsInput(e.target.value);
              }}
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={onClose}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            disabled={submitting}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => void handleCreate()}
          >
            {t('dlg.create')}
          </button>
        </div>
      </div>
    </div>
  );
}
