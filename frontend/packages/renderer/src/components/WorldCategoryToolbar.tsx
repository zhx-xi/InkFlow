/**
 * #699 世界观分类工具栏（从 library.tsx 拆出以守 900 行护栏）：
 * 分类 chips（地理类显示 🗺 图标）+ 删除 + 新建分类/地图视图 + 整体复制。
 * 地图视图入口门控：无选中分类或选中地理类 → 显示；选中抽象类 → 隐藏。
 */
import { Copy } from 'lucide-react';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { WorldCatActionButtons } from './WorldCatActionButtons';

export function WorldCategoryToolbar({
  categories,
  activeWorldCat,
  onSelect,
  onDelete,
  onAddCategory,
  onOpenMapView,
  onCreateWorld,
  copyDisabled,
  copyNeedTwoTitle,
  onCopyAll,
}: {
  categories: WorldCategoryEntity[];
  activeWorldCat: string | null;
  onSelect: (name: string | null) => void;
  onDelete: (id: string | number) => void;
  onAddCategory: () => void;
  onOpenMapView: () => void;
  onCreateWorld?: () => void;
  copyDisabled: boolean;
  copyNeedTwoTitle?: string;
  onCopyAll: () => void;
}) {
  const { t } = useI18n();
  const activeCategoryKind = categories.find((c) => c.name === activeWorldCat)?.kind;
  const showMapEntry = activeWorldCat === null || activeCategoryKind === 'geo';
  return (
    <>
      {/* F43 P1（§5.4）：世界观分类筛选工具栏——默认分组 + 数据自定义 chips（无「全部」，未选 = 展示所有，再点同 chip 取消）；右上角顶部整体复制（E21） */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-ink-2">{t('lib.worldCat.label')}</span>
        {categories.map((catEntity) => (
          <span key={catEntity.name} className="inline-flex items-center gap-1">
            <button
              type="button"
              data-testid={`world-cat-filter-${catEntity.name}`}
              aria-pressed={activeWorldCat === catEntity.name}
              className={cn(
                'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                activeWorldCat === catEntity.name
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-line text-ink-2 hover:border-accent hover:text-accent',
              )}
              onClick={() => onSelect(activeWorldCat === catEntity.name ? null : catEntity.name)}
            >
              {catEntity.kind === 'geo' && <span aria-hidden="true">🗺 </span>}
              {catEntity.name}
            </button>
            <button
              type="button"
              data-testid={`world-cat-delete-${catEntity.name}`}
              aria-label={t('lib.delete')}
              className="rounded-full px-1.5 py-1 text-[12px] text-ink-3 transition duration-150 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onDelete(catEntity.id)}
            >
              ×
            </button>
          </span>
        ))}
        <WorldCatActionButtons
          onAddCategory={onAddCategory}
          onOpenMapView={onOpenMapView}
          showMapEntry={showMapEntry}
          onCreateWorld={onCreateWorld}
        />
        <button
          type="button"
          data-testid="world-copy-all"
          title={copyNeedTwoTitle}
          disabled={copyDisabled}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          onClick={onCopyAll}
        >
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.copy.all')}
        </button>
      </div>
    </>
  );
}
