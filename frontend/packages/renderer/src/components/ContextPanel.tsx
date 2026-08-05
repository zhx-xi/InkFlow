/** 上下文面板（spec §4.2.1）：角色/世界观/大纲/伏笔 4 卡片 + 折叠 → 26px 展开条闭环 */
import { useState } from 'react';
import { useI18n } from '../i18n/useI18n';

const CONTEXT_CARDS = [
  { key: 'characters', titleKey: 'write.context.characters' },
  { key: 'world', titleKey: 'write.context.world' },
  { key: 'outline', titleKey: 'write.context.outline' },
  { key: 'foreshadow', titleKey: 'write.context.foreshadow' },
] as const;

export function ContextPanel() {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <aside
        data-testid="context-panel"
        className="flex w-[26px] shrink-0 border-l border-line bg-surface-2"
      >
        <button
          type="button"
          data-testid="context-expand-bar"
          aria-label={t('write.context.expand')}
          className="flex w-[26px] items-center justify-center text-ink-3 hover:text-ink"
          onClick={() => setCollapsed(false)}
        >
          ‹
        </button>
      </aside>
    );
  }

  return (
    <aside data-testid="context-panel" className="flex w-[240px] shrink-0 flex-col border-l border-line bg-surface-2">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-[13px] font-semibold">{t('write.context.title')}</span>
        <button
          type="button"
          data-testid="context-collapse"
          aria-label={t('write.context.collapse')}
          className="rounded px-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink"
          onClick={() => setCollapsed(true)}
        >
          ›
        </button>
      </div>
      <div data-testid="context-panel-content" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {CONTEXT_CARDS.map((card) => (
          <div key={card.key} className="rounded-md border border-line bg-surface p-3">
            <div className="text-[13px] font-medium">{t(card.titleKey)}</div>
            <div className="mt-1 text-[12px] leading-relaxed text-ink-3">{t('common.empty')}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
