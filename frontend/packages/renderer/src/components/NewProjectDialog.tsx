/** 新建项目对话框（spec §4.2.2）：书名必填 1-100 / Genre 11 枚举 / 语言 / 目标字数默认 800000 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

const GENRES = ['玄幻', '科幻', '言情', '仙侠', '武侠', '都市', '历史', '游戏', '悬疑', '奇幻', '其他'];
const LANGUAGES = ['zh-CN', 'en'];

export interface NewProjectDialogProps {
  onClose: () => void;
}

export function NewProjectDialog({ onClose }: NewProjectDialogProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const createProject = useProjectStore((s) => s.createProject);
  const [name, setName] = useState('');
  const [genre, setGenre] = useState(GENRES[0]);
  const [language, setLanguage] = useState('zh-CN');
  const [targetWords, setTargetWords] = useState(800000);
  const [error, setError] = useState<string | null>(null);
  // #105 修复批：submitting 防双重提交；in-flight 时 ESC/遮罩忽略关闭路径（防误关丢进度）
  const [submitting, setSubmitting] = useState(false);

  // §6.2③ 焦点归还：记录打开时 activeElement，任意关闭路径（ESC/遮罩/取消）卸载后归还触发按钮
  const returnFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      returnFocusRef.current?.focus();
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
    setError(null);
    setSubmitting(true);
    try {
      await createProject({ name: trimmed, genre, language, target_words: targetWords });
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
      onClick={() => {
        if (!submitting) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('dlg.newTitle')}
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
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
            <span>{t('dlg.genre')}</span>
            <Select
              value={genre}
              onValueChange={(v) => setGenre(v)}
            >
              <SelectTrigger aria-label={t('dlg.genre')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GENRES.map((g) => (
                  <SelectItem key={g} value={g}>
                    {g}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
          <label htmlFor="new-project-target" className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('dlg.targetWords')}</span>
            <input
              id="new-project-target"
              type="number"
              min={0}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none"
              value={targetWords}
              onChange={(e) => setTargetWords(Number(e.target.value))}
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
