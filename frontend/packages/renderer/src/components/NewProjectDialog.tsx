/** 新建项目对话框（spec §4.2.2）：书名必填 1-100 / Genre 11 枚举 / 语言 / 目标字数默认 800000 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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

  const handleCreate = async () => {
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
    await createProject({ name: trimmed, genre, language, target_words: targetWords });
    navigate('/writing');
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
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
