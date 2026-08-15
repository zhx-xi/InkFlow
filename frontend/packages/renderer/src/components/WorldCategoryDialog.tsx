/**
 * #389 新建分类轻量对话框（2026-08-16，从 library.tsx 拆分——组件超 900 行护栏）。
 * 仅名称输入；保存由父级 POST /projects/{pid}/world-categories 并刷新分类列表。
 * 仿 MapCreateDialog 先例（#346）：遮罩不关闭，关闭路径 = 取消 / ESC / 保存成功。
 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';

export function WorldCategoryDialog({
  open,
  onSave,
  onOpenChange,
}: {
  open: boolean;
  onSave: (name: string) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState('');

  // 打开时重置表单（创建模式清空，避免残留上次输入）
  useEffect(() => {
    if (open) setName('');
  }, [open]);

  // ESC 关闭（与 PinDialog/ConfirmDialog 同款：尊重已 preventDefault 的 Escape）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const trimmed = name.trim();
  const canSave = trimmed.length > 0;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('lib.worldCat.add')}
        data-testid="world-cat-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('lib.worldCat.add')}</h2>
        <div className="mt-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('lib.worldCat.name')}</span>
            <input
              data-testid="world-cat-name"
              aria-label={t('lib.worldCat.name')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {!canSave && (
              <span className="text-[12px] text-err">{t('lib.worldCat.nameEmpty')}</span>
            )}
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="world-cat-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('lib.create.cancel')}
          </button>
          <button
            type="button"
            data-testid="world-cat-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSave}
            onClick={() => onSave(trimmed)}
          >
            {t('lib.create.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
