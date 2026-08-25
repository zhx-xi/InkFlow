/** 上下文面板（spec §4.2.1 + f6-context-service/gui-panel.md #594）：静态占位 → 接 assemble API 渲染真实条目 + 三级大纲 + 角色/伏笔勾选 override */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  assembleContext,
  type ContextAssemblyResult,
  type ContextBlock,
  type ContextOverride,
  type ContextSourceType,
} from '../api/context';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';

export interface ContextPanelProps {
  projectId: string | null;
  chapterId: string | null;
  model: string | null;
  writingRequirements: string;
}

/** source 分组渲染顺序（7 来源；preference 为后端保留来源） */
const SOURCE_ORDER: ContextSourceType[] = [
  'writing_requirements',
  'outline',
  'character_setting',
  'world_setting',
  'chapter_summary',
  'foreshadowing',
  'preference',
];

/** source → 卡片标题 i18n key；无专用 key 的来源回退条目自身 title */
const SOURCE_TITLE_KEYS: Partial<Record<ContextSourceType, string>> = {
  writing_requirements: 'write.context.required',
  outline: 'write.context.outline',
  character_setting: 'write.context.characters',
  world_setting: 'write.context.world',
  foreshadowing: 'write.context.foreshadow',
};

/** 按 source 分组 blocks（保持出现顺序） */
function groupBySource(blocks: ContextBlock[]): Map<ContextSourceType, ContextBlock[]> {
  const groups = new Map<ContextSourceType, ContextBlock[]>();
  for (const block of blocks) {
    const list = groups.get(block.item.source) ?? [];
    list.push(block);
    groups.set(block.item.source, list);
  }
  return groups;
}

/** 提取某来源条目 id（metadata[metaKey]），供勾选 override 使用 */
function collectIds(blocks: ContextBlock[], source: ContextSourceType, metaKey: string): string[] {
  return blocks
    .filter((block) => block.item.source === source)
    .map((block) => String(block.item.metadata?.[metaKey] ?? ''))
    .filter((id) => id !== '');
}

export function ContextPanel({ projectId, chapterId, model, writingRequirements }: ContextPanelProps) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const [data, setData] = useState<ContextAssemblyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedCharacterIds, setCheckedCharacterIds] = useState<string[]>([]);
  const [checkedForeshadowingIds, setCheckedForeshadowingIds] = useState<string[]>([]);

  /** 调 assemble：override 由当前勾选集构建（全注入 = 空数组） */
  const runAssemble = useCallback(
    async (override: ContextOverride) => {
      if (!projectId || !chapterId || !model) return;
      setLoading(true);
      setError(null);
      try {
        const result = await assembleContext({
          project_id: projectId,
          chapter_id: chapterId,
          model,
          writing_requirements: writingRequirements,
          override,
        });
        setData(result);
        // 勾选状态 = 当前响应中已注入的角色/伏笔条目（初始全注入）
        setCheckedCharacterIds(collectIds(result.blocks, 'character_setting', 'character_id'));
        setCheckedForeshadowingIds(collectIds(result.blocks, 'foreshadowing', 'foreshadowing_id'));
      } catch (err) {
        setData(null);
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [projectId, chapterId, model, writingRequirements],
  );

  // 挂载 / projectId / chapterId 变化 → 自动注入；任缺 → 空态且不调用
  useEffect(() => {
    setCheckedCharacterIds([]);
    setCheckedForeshadowingIds([]);
    if (projectId && chapterId && model) {
      void runAssemble({ character_ids: [], foreshadowing_ids: [] });
    } else {
      setData(null);
      setError(null);
    }
  }, [runAssemble, projectId, chapterId, model]);

  const groups = useMemo(
    () => (data ? groupBySource(data.blocks) : new Map<ContextSourceType, ContextBlock[]>()),
    [data],
  );

  /** 勾选/取消 → 白名单 override 重新组装 */
  const handleToggle = (source: 'character_setting' | 'foreshadowing', id: string) => {
    if (source === 'character_setting') {
      const next = checkedCharacterIds.includes(id)
        ? checkedCharacterIds.filter((candidate) => candidate !== id)
        : [...checkedCharacterIds, id];
      setCheckedCharacterIds(next);
      void runAssemble({ character_ids: next, foreshadowing_ids: checkedForeshadowingIds });
    } else {
      const next = checkedForeshadowingIds.includes(id)
        ? checkedForeshadowingIds.filter((candidate) => candidate !== id)
        : [...checkedForeshadowingIds, id];
      setCheckedForeshadowingIds(next);
      void runAssemble({ character_ids: checkedCharacterIds, foreshadowing_ids: next });
    }
  };

  if (collapsed) {
    return (
      <aside
        data-testid="context-panel"
        className="flex w-[26px] shrink-0 flex-col"
      >
        <button
          type="button"
          data-testid="context-expand-bar"
          aria-label={t('write.context.expand')}
          className="flex w-[26px] items-center justify-center text-ink-3 hover:text-ink"
          onClick={() => setCollapsed(false)}
        >
          ›
        </button>
      </aside>
    );
  }

  return (
    <aside
      data-testid="context-panel"
      className="flex min-h-0 flex-col"
    >
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
      <div
        data-testid="context-panel-content"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3"
      >
        {error !== null ? (
          <div
            data-testid="context-error"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {error}
          </div>
        ) : data === null || data.blocks.length === 0 ? (
          <div
            data-testid="context-empty"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {loading ? t('common.loading') : t('common.empty')}
          </div>
        ) : (
          <>
            {SOURCE_ORDER.filter((source) => groups.has(source)).map((source) => {
              const blocks = groups.get(source) ?? [];
              const titleKey = SOURCE_TITLE_KEYS[source];
              const title = titleKey ? t(titleKey) : (blocks[0]?.item.title ?? source);
              return (
                <section
                  key={source}
                  data-testid={`context-block-${source}`}
                  className="rounded-md border border-line bg-surface p-3"
                >
                  <div className="text-[13px] font-medium">{title}</div>
                  {source === 'outline' ? (
                    <div
                      data-testid="context-outline"
                      className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-ink-2"
                    >
                      {blocks[0]?.item.content}
                    </div>
                  ) : source === 'character_setting' || source === 'foreshadowing' ? (
                    blocks.map((block, index) => {
                      const id = String(
                        source === 'character_setting'
                          ? block.item.metadata?.character_id ?? ''
                          : block.item.metadata?.foreshadowing_id ?? '',
                      );
                      const checked =
                        source === 'character_setting'
                          ? checkedCharacterIds.includes(id)
                          : checkedForeshadowingIds.includes(id);
                      const itemTestId =
                        source === 'character_setting'
                          ? `context-character-${index}`
                          : `context-foreshadow-${index}`;
                      return (
                        <label
                          key={`${source}-${index}`}
                          data-testid={itemTestId}
                          className="mt-2 flex cursor-pointer items-start gap-2"
                        >
                          <input
                            type="checkbox"
                            data-testid={`context-item-toggle-${index}`}
                            checked={checked}
                            aria-label={t('write.context.inject')}
                            onChange={() => handleToggle(source, id)}
                            className="mt-0.5"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[12px] font-medium text-ink-2">
                              {block.item.title}
                            </span>
                            <span className="mt-0.5 block text-[12px] leading-relaxed text-ink-3">
                              {block.item.content}
                            </span>
                          </span>
                        </label>
                      );
                    })
                  ) : (
                    blocks.map((block, index) => (
                      <div
                        key={`${source}-${index}`}
                        className="mt-1 text-[12px] leading-relaxed text-ink-3"
                      >
                        <span className="font-medium text-ink-2">{block.item.title}</span>
                        <div className="mt-0.5">{block.item.content}</div>
                      </div>
                    ))
                  )}
                </section>
              );
            })}
            {data.dropped.length > 0 && (
              <section
                data-testid="context-dropped"
                className="rounded-md border border-line bg-surface p-3"
              >
                <div className="text-[13px] font-medium">{t('write.context.dropped')}</div>
                {data.dropped.map((entry, index) => (
                  <div
                    key={`dropped-${index}`}
                    data-testid={`context-dropped-${index}`}
                    className="mt-1 text-[12px] leading-relaxed text-ink-3"
                  >
                    {entry.item.title}：{entry.reason}
                  </div>
                ))}
              </section>
            )}
            <div className="text-[11px] text-ink-3">
              {t('write.context.tokens', { total: data.total_tokens, budget: data.budget_tokens })}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
