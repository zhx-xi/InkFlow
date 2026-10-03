import type { ContextBlock, ContextOverride, ContextSourceType } from '../api/context';
import { useI18n } from '../i18n/useI18n';

/** source 分组渲染顺序（7 来源；preference 为后端保留来源） */
export const SOURCE_ORDER: ContextSourceType[] = [
  'writing_requirements',
  'outline',
  'character_setting',
  'world_setting',
  'chapter_summary',
  'foreshadowing',
  'preference',
];

/** source → 卡片标题 i18n key；无专用 key 的来源回退条目自身 title */
export const SOURCE_TITLE_KEYS: Partial<Record<ContextSourceType, string>> = {
  writing_requirements: 'write.context.required',
  outline: 'write.context.outline',
  character_setting: 'write.context.characters',
  world_setting: 'write.context.world',
  foreshadowing: 'write.context.foreshadow',
};

/**
 * #1349 章级回执面：三源渲染顺序 + 标题 i18n key。
 * 只含「面板可勾选」的三源 —— 大纲源无 override 面且非用户可选，不进回执面。
 */
export const INJECTED_SECTIONS: Array<{ key: keyof ContextOverride; titleKey: string }> = [
  { key: 'character_ids', titleKey: 'write.context.characters' },
  { key: 'world_ids', titleKey: 'write.context.world' },
  { key: 'foreshadowing_ids', titleKey: 'write.context.foreshadow' },
];

/** 明细总条数（回执面徽章） */
export function countInjected(detail: ContextOverride): number {
  return (
    detail.character_ids.length + detail.world_ids.length + detail.foreshadowing_ids.length
  );
}

/** 按 source 分组 blocks（保持出现顺序） */
export function groupBySource(blocks: ContextBlock[]): Map<ContextSourceType, ContextBlock[]> {
  const groups = new Map<ContextSourceType, ContextBlock[]>();
  for (const block of blocks) {
    const list = groups.get(block.item.source) ?? [];
    list.push(block);
    groups.set(block.item.source, list);
  }
  return groups;
}

/** 提取某来源条目 id（metadata[metaKey]），供勾选 override 使用 */
export function collectIds(blocks: ContextBlock[], source: ContextSourceType, metaKey: string): string[] {
  return blocks
    .filter((block) => block.item.source === source)
    .map((block) => String(block.item.metadata?.[metaKey] ?? ''))
    .filter((id) => id !== '');
}

/** #704：搜索选择器本地选项行 */
export interface PickerOption {
  id: string;
  label: string;
}

/** #704：带「＋ 选择注入」按钮的分组（仅 character_setting / world_setting / foreshadowing） */
export const PICKER_SOURCES: ReadonlySet<ContextSourceType> = new Set([
  'character_setting',
  'world_setting',
  'foreshadowing',
]);

/** #1017：分组头 + 「＋ 选择注入」按钮（正常分支内嵌 / 空态·错误态精简复用的同一渲染块） */
export function GroupHeader({
  title,
  source,
  onPick,
  checkedCount = 0,
  onClear,
}: {
  title: string;
  source: ContextSourceType;
  onPick: (source: ContextSourceType) => void;
  checkedCount?: number;
  onClear?: (source: ContextSourceType) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="min-w-0 truncate text-[13px] font-medium">{title}</span>
      {PICKER_SOURCES.has(source) && (
        <div className="flex shrink-0 items-center gap-1.5">
          {onClear && (
            <button
              type="button"
              data-testid={`context-clear-${source}`}
              aria-label={`${t('write.context.clearCategory')} ${title}`}
              disabled={checkedCount === 0}
              className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => onClear(source)}
            >
              {t('write.context.clearCategory')}
            </button>
          )}
          <button
            type="button"
            data-testid={`context-pick-${source}`}
            aria-label={t('write.context.injectSelect')}
            className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => onPick(source)}
          >
            {t('write.context.injectSelect')}
          </button>
        </div>
      )}
    </div>
  );
}
