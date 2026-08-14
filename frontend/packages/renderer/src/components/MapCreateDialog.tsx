/**
 * #346 创建地图轻量对话框（2026-08-14，从 MapWorkbench.tsx 拆分——组件超 900 行护栏）。
 * 仅名称输入，bg_source 固定 shape（无图可建）；root_location_id 由父级 createDialog
 * state 持有，保存时注入。仿 PinDialog 模式。
 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';

export function MapCreateDialog({
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

  // 打开时重置表单（root_location_id 由父级 createDialog state 持有，保存时注入）
  useEffect(() => {
    if (open) setName('');
  }, [open]);

  // ESC 关闭（尊重已 preventDefault 的 Escape，与 PinDialog/ConfirmDialog 同款）
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
  const canSave = trimmed.length > 0 && trimmed.length <= 100;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('lib.map.createTitle')}
        data-testid="map-create-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('lib.map.createTitle')}</h2>
        <div className="mt-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('lib.map.createPlaceholder')}</span>
            <input
              data-testid="map-create-name"
              aria-label={t('lib.map.createPlaceholder')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="map-create-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('lib.map.createCancel')}
          </button>
          <button
            type="button"
            data-testid="map-create-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSave}
            onClick={() => onSave(trimmed)}
          >
            {t('lib.map.createSave')}
          </button>
        </div>
      </div>
    </div>
  );
}
