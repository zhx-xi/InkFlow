/**
 * #699 世界观分类工具栏（从 library.tsx 拆出以守 900 行护栏）：
 * 分类 chips（地理类显示 🗺 图标）+ 删除 + 新建分类/新建条目/地图视图 + 整体复制。
 * #1375：①A 按钮语义拆分（新建分类恒开分类框 / 新建条目独立钮）；
 *        ②A 分类栏并集（pending 虚线 chip +「待注册」注记 + 一键注册）；
 *        ④ × 移入 chip 框内（容器持边框）+ 未 hover 隐藏。
 * 地图视图入口门控：无选中分类或选中地理类 → 显示；选中抽象类 → 隐藏。
 */
import { Copy } from 'lucide-react';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { WorldCatActionButtons } from './WorldCatActionButtons';

export function WorldCategoryToolbar({
  categories,
  pendingCategories,
  activeWorldCat,
  onSelect,
  onDelete,
  onRegisterPending,
  onAddCategory,
  onOpenMapView,
  onCreateWorld,
  copyDisabled,
  copyNeedTwoTitle,
  onCopyAll,
}: {
  categories: WorldCategoryEntity[];
  /** #1375 ②A：条目使用但未注册的类别名——虚线 chip +「待注册」+ 一键注册 */
  pendingCategories: string[];
  activeWorldCat: string | null;
  onSelect: (name: string | null) => void;
  onDelete: (id: string | number) => void;
  /** #1375 ②A：一键注册 → POST world-categories（默认抽象类） */
  onRegisterPending: (name: string) => void;
  onAddCategory: () => void;
  onOpenMapView: () => void;
  /** #1375 ①A：「新建条目」点击 → 建条目对话框（未选中分类时禁用） */
  onCreateWorld?: () => void;
  copyDisabled: boolean;
  copyNeedTwoTitle?: string;
  onCopyAll: () => void;
}) {
  const { t } = useI18n();
  const activeCategoryKind = categories.find((c) => c.name === activeWorldCat)?.kind;
  const showMapEntry = activeWorldCat === null || activeCategoryKind === 'geo';
  /** #1375 ④：chip 容器样式——边框在容器上（× 在框内）；选中态高亮整框；pending 虚线 */
  const chipCls = (active: boolean, pending: boolean) =>
    cn(
      'group inline-flex items-center gap-0.5 rounded-full border py-0.5 pl-3 pr-1 text-[12px] transition duration-150',
      pending
        ? 'border-dashed border-ink-3 text-ink-2 hover:border-accent'
        : active
          ? 'border-accent bg-accent/10 text-accent'
          : 'border-line text-ink-2 hover:border-accent hover:text-accent',
    );
  const nameBtnCls =
    'inline-flex items-center gap-1 rounded-full text-[12px] text-inherit transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  return (
    <>
      {/* F43 P1（§5.4）：世界观分类筛选工具栏——默认分组 + 数据自定义 chips（无「全部」，未选 = 展示所有，再点同 chip 取消）；右上角顶部整体复制（E21） */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-ink-2">{t('lib.worldCat.label')}</span>
        {categories.map((catEntity) => {
          const active = activeWorldCat === catEntity.name;
          return (
            <span
              key={catEntity.name}
              data-testid={`world-cat-chip-${catEntity.name}`}
              className={chipCls(active, false)}
            >
              <button
                type="button"
                data-testid={`world-cat-filter-${catEntity.name}`}
                aria-pressed={active}
                className={cn(nameBtnCls, 'group-hover:text-accent')}
                onClick={() => onSelect(active ? null : catEntity.name)}
              >
                {catEntity.kind === 'geo' && <span aria-hidden="true">🗺 </span>}
                {catEntity.name}
              </button>
              <button
                type="button"
                data-testid={`world-cat-delete-${catEntity.name}`}
                aria-label={t('lib.delete')}
                className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[13px] leading-none text-ink-3 opacity-0 transition duration-150 hover:bg-surface-3 hover:text-err focus-visible:opacity-100 focus-visible:outline-none group-hover:opacity-100"
                onClick={() => onDelete(catEntity.id)}
              >
                ×
              </button>
            </span>
          );
        })}
        {pendingCategories.map((name) => {
          const active = activeWorldCat === name;
          return (
            <span key={name} data-testid={`world-cat-chip-${name}`} className={chipCls(active, true)}>
              <button
                type="button"
                data-testid={`world-cat-filter-${name}`}
                aria-pressed={active}
                className={nameBtnCls}
                onClick={() => onSelect(active ? null : name)}
              >
                {name}
              </button>
              <span className="mx-1 whitespace-nowrap text-[11px] text-ink-2">{t('lib.worldCat.pending')}</span>
              <button
                type="button"
                data-testid={`world-cat-register-${name}`}
                aria-label={t('lib.worldCat.register', { name })}
                title={t('lib.worldCat.register', { name })}
                className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[13px] leading-none text-accent transition duration-150 hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onRegisterPending(name)}
              >
                ＋
              </button>
            </span>
          );
        })}
        <WorldCatActionButtons
          onAddCategory={onAddCategory}
          onOpenMapView={onOpenMapView}
          showMapEntry={showMapEntry}
          onCreateWorld={onCreateWorld}
          activeWorldCat={activeWorldCat}
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
