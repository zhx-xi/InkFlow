/**
 * #389 世界观列表页操作按钮组（新建分类 + 新建条目 + 地图视图）：列表页工具栏与空态共用。
 * #1375 ①A：语义拆分——「新建分类」恒开分类对话框（#568 随选中态切换语义退役）；
 * 「新建条目」独立成钮（选中分类时启用、未选中禁用 + 提示）；#1321 恒开语义并入「新建分类」。
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
  showMapEntry = true,
  onCreateWorld,
  activeWorldCat,
}: {
  onAddCategory: () => void;
  onOpenMapView: () => void;
  showCreate?: boolean;
  /** #699：false 时不渲染地图视图入口（选中抽象类分类时由调用方门控） */
  showMapEntry?: boolean;
  /** #1375 ①A：提供时渲染「新建条目」钮（空态不传）；点击 = 打开建条目对话框 */
  onCreateWorld?: () => void;
  /** #1375 ①A：当前选中分类名——null/undefined = 未选中 → 「新建条目」禁用 + 提示「请先选择分类」 */
  activeWorldCat?: string | null;
}) {
  const { t } = useI18n();
  return (
    <>
      {/* #1375 ①A：「新建分类」恒开分类对话框（不随选中分类改变语义） */}
      {showCreate && (
        <button type="button" data-testid="world-cat-add" className={BTN_CLS} onClick={onAddCategory}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.worldCat.add')}
        </button>
      )}
      {/* #1375 ①A：「新建条目」——选中分类时启用；空态（未传 onCreateWorld）不渲染 */}
      {onCreateWorld && (
        <button
          type="button"
          data-testid="world-cat-add-entry"
          className={`${BTN_CLS} disabled:cursor-not-allowed disabled:opacity-50`}
          disabled={activeWorldCat == null}
          title={
            activeWorldCat != null
              ? t('lib.worldCat.addEntryTitle', { name: activeWorldCat })
              : t('lib.worldCat.selectFirst')
          }
          onClick={onCreateWorld}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.worldCat.addEntry')}
        </button>
      )}
      {showMapEntry && (
        <button type="button" data-testid="map-view-entry" className={BTN_CLS} onClick={onOpenMapView}>
          <Map className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.worldMap')}
        </button>
      )}
    </>
  );
}
