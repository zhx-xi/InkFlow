/** 上下文面板（spec §4.2.1 + f6-context-service/gui-panel.md #594）：静态占位 → 接 assemble API 渲染真实条目 + 三级大纲 + 角色/伏笔勾选 override */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { listProjectCharacters } from '../api/character';
import {
  assembleContext,
  listProjectForeshadowings,
  listProjectWorldSettings,
  type ContextAssemblyResult,
  type ContextBlock,
  type ContextOverride,
  type ContextSourceType,
} from '../api/context';
import { ApiError, errorMessage } from '../api/client';
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

/** #704：搜索选择器本地选项行 */
interface PickerOption {
  id: string;
  label: string;
}

/** #704：带「＋ 选择注入」按钮的分组（仅 character_setting / world_setting / foreshadowing） */
const PICKER_SOURCES: ReadonlySet<ContextSourceType> = new Set([
  'character_setting',
  'world_setting',
  'foreshadowing',
]);

export function ContextPanel({ projectId, chapterId, model, writingRequirements }: ContextPanelProps) {
  const { t } = useI18n();
  const [data, setData] = useState<ContextAssemblyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedCharacterIds, setCheckedCharacterIds] = useState<string[]>([]);
  const [checkedForeshadowingIds, setCheckedForeshadowingIds] = useState<string[]>([]);
  const [checkedWorldIds, setCheckedWorldIds] = useState<string[]>([]);
  // #704：分组「选择注入」搜索选择器状态
  const [pickerSource, setPickerSource] = useState<ContextSourceType | null>(null);
  const [pickerOptions, setPickerOptions] = useState<PickerOption[] | null>(null);
  const [pickerSelection, setPickerSelection] = useState<string[]>([]);
  const [pickerSearch, setPickerSearch] = useState('');
  const [pickerError, setPickerError] = useState<string | null>(null);

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
        setCheckedWorldIds(collectIds(result.blocks, 'world_setting', 'world_setting_id'));
      } catch (err) {
        setData(null);
        // #759：空写作要求被后端 min_length 拒（422 string_too_short）→ 优雅占位，不渲染原始 JSON
        const msg = errorMessage(err);
        if ((err instanceof ApiError && err.status === 422) || msg.includes('string_too_short')) {
          setError(t('write.context.emptyRequired'));
        } else {
          setError(msg);
        }
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
    setCheckedWorldIds([]);
    if (projectId && chapterId && model) {
      if (!writingRequirements.trim()) {
        // #759：写作要求为空 → 不发 assemble，直接显示「未填写写作要求」占位
        setData(null);
        setError(t('write.context.emptyRequired'));
      } else {
        void runAssemble({ character_ids: [], foreshadowing_ids: [], world_ids: [] });
      }
    } else {
      setData(null);
      setError(null);
    }
  }, [runAssemble, projectId, chapterId, model, writingRequirements]);

  const groups = useMemo(
    () => (data ? groupBySource(data.blocks) : new Map<ContextSourceType, ContextBlock[]>()),
    [data],
  );

  /** 勾选/取消 → 白名单 override 重新组装 */
  const handleToggle = (
    source: 'character_setting' | 'world_setting' | 'foreshadowing',
    id: string,
  ) => {
    if (source === 'character_setting') {
      const next = checkedCharacterIds.includes(id)
        ? checkedCharacterIds.filter((candidate) => candidate !== id)
        : [...checkedCharacterIds, id];
      setCheckedCharacterIds(next);
      void runAssemble({
        character_ids: next,
        foreshadowing_ids: checkedForeshadowingIds,
        world_ids: checkedWorldIds,
      });
    } else if (source === 'foreshadowing') {
      const next = checkedForeshadowingIds.includes(id)
        ? checkedForeshadowingIds.filter((candidate) => candidate !== id)
        : [...checkedForeshadowingIds, id];
      setCheckedForeshadowingIds(next);
      void runAssemble({
        character_ids: checkedCharacterIds,
        foreshadowing_ids: next,
        world_ids: checkedWorldIds,
      });
    } else {
      const next = checkedWorldIds.includes(id)
        ? checkedWorldIds.filter((candidate) => candidate !== id)
        : [...checkedWorldIds, id];
      setCheckedWorldIds(next);
      void runAssemble({
        character_ids: checkedCharacterIds,
        foreshadowing_ids: checkedForeshadowingIds,
        world_ids: next,
      });
    }
  };

  /** #704：打开分组搜索选择器 — 加载该组全量列表，本地选择以当前注入集合为预勾选 */
  const openPicker = async (source: ContextSourceType) => {
    if (!projectId) return;
    const prechecked =
      source === 'character_setting'
        ? checkedCharacterIds
        : source === 'foreshadowing'
          ? checkedForeshadowingIds
          : checkedWorldIds;
    setPickerSource(source);
    setPickerSearch('');
    setPickerSelection(prechecked);
    setPickerOptions(null);
    setPickerError(null);
    try {
      let options: PickerOption[] = [];
      if (source === 'character_setting') {
        const res = await listProjectCharacters(projectId);
        options = res.items.map((c) => ({ id: String(c.id), label: c.name }));
      } else if (source === 'world_setting') {
        const res = await listProjectWorldSettings(projectId);
        options = res.items.map((w) => ({ id: String(w.id), label: w.name }));
      } else {
        const res = await listProjectForeshadowings(projectId);
        options = res.items.map((f) => ({ id: String(f.id), label: f.title }));
      }
      setPickerOptions(options);
    } catch (err) {
      setPickerError(errorMessage(err));
    }
  };

  /** 勾选/取消本地选择 */
  const togglePickerOption = (id: string) => {
    setPickerSelection((prev) =>
      prev.includes(id) ? prev.filter((candidate) => candidate !== id) : [...prev, id],
    );
  };

  /** 关闭选择器（不提交） */
  const closePicker = () => {
    setPickerSource(null);
    setPickerOptions(null);
    setPickerSelection([]);
    setPickerSearch('');
    setPickerError(null);
  };

  /** #704：确认 → 覆盖对应 override 白名单并重新 assemble（token 数 / 分组条目随之刷新） */
  const confirmPicker = () => {
    if (pickerSource === 'character_setting') {
      setCheckedCharacterIds(pickerSelection);
      void runAssemble({
        character_ids: pickerSelection,
        foreshadowing_ids: checkedForeshadowingIds,
        world_ids: checkedWorldIds,
      });
    } else if (pickerSource === 'foreshadowing') {
      setCheckedForeshadowingIds(pickerSelection);
      void runAssemble({
        character_ids: checkedCharacterIds,
        foreshadowing_ids: pickerSelection,
        world_ids: checkedWorldIds,
      });
    } else if (pickerSource === 'world_setting') {
      setCheckedWorldIds(pickerSelection);
      void runAssemble({
        character_ids: checkedCharacterIds,
        foreshadowing_ids: checkedForeshadowingIds,
        world_ids: pickerSelection,
      });
    }
    closePicker();
  };

  /** 搜索过滤（按名称/标题，大小写不敏感） */
  const filteredPickerOptions = useMemo(() => {
    if (!pickerOptions) return [];
    const query = pickerSearch.trim().toLowerCase();
    if (!query) return pickerOptions;
    return pickerOptions.filter((opt) => opt.label.toLowerCase().includes(query));
  }, [pickerOptions, pickerSearch]);

  return (
    <aside
      data-testid="context-panel"
      className="relative flex min-h-0 flex-1 flex-col"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-[13px] font-semibold">{t('write.context.title')}</span>
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
        ) : data === null ? (
          <div
            data-testid="context-empty"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {loading ? t('common.loading') : t('common.empty')}
          </div>
        ) : (
          <>
            {SOURCE_ORDER.map((source) => {
              const blocks = groups.get(source) ?? [];
              const titleKey = SOURCE_TITLE_KEYS[source];
              const title = titleKey ? t(titleKey) : (blocks[0]?.item.title ?? source);
              const isCheckable =
                source === 'character_setting' ||
                source === 'world_setting' ||
                source === 'foreshadowing';
              return (
                <section
                  key={source}
                  data-testid={`context-block-${source}`}
                  className="rounded-md border border-line bg-surface p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-[13px] font-medium">{title}</span>
                    {PICKER_SOURCES.has(source) && (
                      <button
                        type="button"
                        data-testid={`context-pick-${source}`}
                        aria-label={t('write.context.injectSelect')}
                        className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                        onClick={() => void openPicker(source)}
                      >
                        {t('write.context.injectSelect')}
                      </button>
                    )}
                  </div>
                  {blocks.length === 0 ? (
                    <div className="mt-2 text-[12px] leading-relaxed text-ink-3">
                      {t('common.empty')}
                    </div>
                  ) : source === 'outline' ? (
                    blocks.map((block, index) => (
                      <div
                        key={`outline-${index}`}
                        data-testid={`context-item-outline-${index}`}
                      >
                        <div
                          data-testid="context-outline"
                          className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-ink-2"
                        >
                          {block.item.content}
                        </div>
                      </div>
                    ))
                  ) : isCheckable ? (
                    blocks.map((block, index) => {
                      const metaKey =
                        source === 'character_setting'
                          ? 'character_id'
                          : source === 'world_setting'
                            ? 'world_setting_id'
                            : 'foreshadowing_id';
                      const id = String(block.item.metadata?.[metaKey] ?? '');
                      const checked =
                        source === 'character_setting'
                          ? checkedCharacterIds.includes(id)
                          : source === 'world_setting'
                            ? checkedWorldIds.includes(id)
                            : checkedForeshadowingIds.includes(id);
                      const legacyTestId =
                        source === 'character_setting'
                          ? `context-character-${index}`
                          : source === 'foreshadowing'
                            ? `context-foreshadow-${index}`
                            : undefined;
                      return (
                        <div
                          key={`${source}-${index}`}
                          data-testid={`context-item-${source}-${index}`}
                        >
                          <label
                            data-testid={legacyTestId}
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
                        </div>
                      );
                    })
                  ) : (
                    blocks.map((block, index) => (
                      <div
                        key={`${source}-${index}`}
                        data-testid={`context-item-${source}-${index}`}
                        className="mt-2 text-[12px] leading-relaxed text-ink-3"
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
      {pickerSource !== null && pickerOptions !== null ? (
        <div
          data-testid="context-picker"
          className="absolute inset-x-2 top-12 z-40 flex max-h-[calc(100%-4rem)] flex-col rounded-lg border border-line bg-surface shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="text-[13px] font-semibold">
              {pickerSource === 'character_setting'
                ? t('write.context.characters')
                : pickerSource === 'world_setting'
                  ? t('write.context.world')
                  : t('write.context.foreshadow')}
            </span>
          </div>
          <div className="p-2">
            <input
              data-testid="context-picker-search"
              placeholder={t('write.context.pickerSearch')}
              value={pickerSearch}
              onChange={(e) => setPickerSearch(e.target.value)}
              autoFocus
              className="w-full rounded border border-line bg-surface px-2 py-1 text-[12px] outline-none"
            />
          </div>
          <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
            {pickerError !== null ? (
              <div className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3">
                {pickerError}
              </div>
            ) : filteredPickerOptions.length === 0 ? (
              <div className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3">
                {t('common.empty')}
              </div>
            ) : (
              filteredPickerOptions.map((opt) => (
                <label
                  key={opt.id}
                  data-testid={`context-picker-opt-${opt.id}`}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-[12px] text-ink-2 hover:bg-surface-3"
                >
                  <input
                    type="checkbox"
                    className="shrink-0"
                    checked={pickerSelection.includes(opt.id)}
                    onChange={() => togglePickerOption(opt.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">{opt.label}</span>
                </label>
              ))
            )}
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-line p-2">
            <button
              type="button"
              data-testid="context-picker-cancel"
              className="rounded border border-line px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={closePicker}
            >
              {t('dlg.cancel')}
            </button>
            <button
              type="button"
              data-testid="context-picker-confirm"
              className="rounded bg-accent px-2 py-1 text-[12px] text-accent-ink hover:bg-accent/90"
              onClick={confirmPicker}
            >
              {t('write.context.pickerAppend')}
            </button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
