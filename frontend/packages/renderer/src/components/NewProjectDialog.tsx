/** 新建项目对话框（spec §4.2.2）：书名必填 1-100 / Genre 11 枚举 / 语言 / 目标字数默认 800000 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';

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
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('dlg.newTitle')}</h2>
        <div className="mt-4 space-y-3">
          <label htmlFor="new-project-name" className="block text-[13px]">
            <span className="mb-1 block">{t('dlg.name')}</span>
            <input
              id="new-project-name"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('dlg.namePlaceholder')}
            />
          </label>
          {error && <div className="text-[13px] text-err">{error}</div>}
          <label htmlFor="new-project-genre" className="block text-[13px]">
            <span className="mb-1 block">{t('dlg.genre')}</span>
            <select
              id="new-project-genre"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none"
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
            >
              {GENRES.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="new-project-lang" className="block text-[13px]">
            <span className="mb-1 block">{t('dlg.lang')}</span>
            <select
              id="new-project-lang"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="new-project-target" className="block text-[13px]">
            <span className="mb-1 block">{t('dlg.targetWords')}</span>
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
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 hover:bg-surface-2"
            onClick={onClose}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink"
            onClick={() => void handleCreate()}
          >
            {t('dlg.create')}
          </button>
        </div>
      </div>
    </div>
  );
}
