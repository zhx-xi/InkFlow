/**
 * #389 世界观列表页操作按钮组（新建分类 + 地图视图）：列表页工具栏与空态共用，
 * 从 library.tsx 拆分以守 900 行护栏。
 */
import { Map, Plus } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

const BTN_CLS =
  'inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function WorldCatActionButtons({
  onAddCategory,
  onOpenMapView,
  showCreate = true,
}: {
  onAddCategory: () => void;
  onOpenMapView: () => void;
  showCreate?: boolean;
}) {
  const { t } = useI18n();
  return (
    <>
      {/* #567：已有根世界观条目时隐藏「新建分类」入口（保留地图视图） */}
      {showCreate && (
        <button type="button" data-testid="world-cat-add" className={BTN_CLS} onClick={onAddCategory}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.worldCat.add')}
        </button>
      )}
      <button type="button" data-testid="map-view-entry" className={BTN_CLS} onClick={onOpenMapView}>
        <Map className="h-3.5 w-3.5" aria-hidden="true" />
        {t('lib.worldMap')}
      </button>
    </>
  );
}
