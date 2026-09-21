/** 上下文面板（spec §4.2.1 + f6-context/gui-panel.md #594）：静态占位 → 接 assemble API 渲染真实条目 + 三级大纲 + 角色/伏笔勾选 override */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { listProjectCharacters } from '../api/character';
import {
  assembleContext,
  fetchChapterInjections,
  listProjectForeshadowings,
  listProjectWorldSettings,
  type ChapterInjectionDto,
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
  /** #1017：项目级要求（「继承」判定 + placeholder 提示）；缺省视为空（既有 #594/#704/#743/#759 渲染点不传仍可编译） */
  projectWritingStyle?: string;
  /** #1017：章级覆盖原文（null/缺省 = 继承；用于栏内回显） */
  chapterWritingRequirements?: string | null;
  /** #1017：章级栏失焦保存（null = 清除覆盖回继承） */
  onWritingRequirementsChange?: (value: string | null) => void;
  /** #1342：勾选集合外传到父层（受控回调）；缺省 = 组件内部 state（既有行为不变） */
  onOverrideChange?: (override: ContextOverride) => void;
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

/**
 * #1349 章级回执面：三源渲染顺序 + 标题 i18n key。
 * 只含「面板可勾选」的三源 —— 大纲源无 override 面且非用户可选，不进回执面。
 */
const INJECTED_SECTIONS: Array<{ key: keyof ContextOverride; titleKey: string }> = [
  { key: 'character_ids', titleKey: 'write.context.characters' },
  { key: 'world_ids', titleKey: 'write.context.world' },
  { key: 'foreshadowing_ids', titleKey: 'write.context.foreshadow' },
];

/** 明细总条数（回执面徽章） */
function countInjected(detail: ContextOverride): number {
  return (
    detail.character_ids.length + detail.world_ids.length + detail.foreshadowing_ids.length
  );
}

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

/** #1017：分组头 + 「＋ 选择注入」按钮（正常分支内嵌 / 空态·错误态精简复用的同一渲染块） */
function GroupHeader({
  title,
  source,
  onPick,
}: {
  title: string;
  source: ContextSourceType;
  onPick: (source: ContextSourceType) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="min-w-0 truncate text-[13px] font-medium">{title}</span>
      {PICKER_SOURCES.has(source) && (
        <button
          type="button"
          data-testid={`context-pick-${source}`}
          aria-label={t('write.context.injectSelect')}
          className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => onPick(source)}
        >
          {t('write.context.injectSelect')}
        </button>
      )}
    </div>
  );
}

export function ContextPanel({
  projectId,
  chapterId,
  model,
  writingRequirements,
  projectWritingStyle = '',
  chapterWritingRequirements,
  onWritingRequirementsChange,
  onOverrideChange,
}: ContextPanelProps) {
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
  // #1349：章级注入记录（回执面取数源）；null = 无记录/未取到 → 回退态
  const [injectionRecord, setInjectionRecord] = useState<ChapterInjectionDto | null>(null);
  // #1017：章级写作要求本地草稿（初始值 = 章级覆盖原文，null=继承 → 空）
  const [requirementsDraft, setRequirementsDraft] = useState(() => chapterWritingRequirements ?? '');
  /** 上次同步的章级覆盖值（用于切章时重播草稿，避免用户输入中被回写打断） */
  const syncedRequirementsRef = useRef(chapterWritingRequirements ?? '');

  // #1017：切章（章级覆盖 prop 变化）→ 重播草稿；同值回写不打断当前输入
  useEffect(() => {
    const next = chapterWritingRequirements ?? '';
    if (syncedRequirementsRef.current === next) return;
    syncedRequirementsRef.current = next;
    setRequirementsDraft(next);
  }, [chapterWritingRequirements]);

  /** 调 assemble：override 由当前勾选集构建（#1235：缺省 undefined = 全注入；显式数组含空 = 白名单，空 = 删空） */
  const runAssemble = useCallback(
    async (override: ContextOverride | undefined) => {
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

  /**
   * #1349：章级注入记录（回执面）——「上一章生成时**实际**注入了什么」。
   * 只读观测面，不参与勾选控制面。失败静默降级为回退态（不阻塞预览主路径）。
   */
  useEffect(() => {
    if (!chapterId) {
      setInjectionRecord(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const record = await fetchChapterInjections(chapterId);
        if (!cancelled) setInjectionRecord(record);
      } catch {
        if (!cancelled) setInjectionRecord(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chapterId]);

  // 挂载 / projectId / chapterId 变化 → 自动注入；任缺 → 空态且不调用
  useEffect(() => {
    setCheckedCharacterIds([]);
    setCheckedForeshadowingIds([]);
    setCheckedWorldIds([]);
    // #1342：切章同时清 data —— 三个 checked 清空但 data 仍是上一章的值时，
    // onOverrideChange 的 effect 会放行并通过「三字段全空」=「该章不注入」（错误语义）。
    // data 与 checked 必须同帧失效，等新组装结果回来再一起生效。
    setData(null);
    if (projectId && chapterId && model) {
      if (!writingRequirements.trim()) {
        // #759：写作要求为空 → 不发 assemble，直接显示「未填写写作要求」占位
        setData(null);
        setError(t('write.context.emptyRequired'));
      } else {
        // #1235：初始不传 override（缺省 = 全注入）；显式空数组在新语义下 = 全不注入
        void runAssemble(undefined);
      }
    } else {
      setData(null);
      setError(null);
    }
  }, [runAssemble, projectId, chapterId, model, writingRequirements]);

  const injectedDetail = injectionRecord?.injected_context ?? null;
  const injectedCount = injectedDetail === null ? 0 : countInjected(injectedDetail);

  const groups = useMemo(
    () => (data ? groupBySource(data.blocks) : new Map<ContextSourceType, ContextBlock[]>()),
    [data],
  );

  /**
   * #1342：勾选集合外传到父层（生成链路 override 真源）。
   * 一处覆盖所有入口（勾选/取消 / 选择器确认 / 初始自动注入）——避免在每个 setChecked* 调用点加回调。
   * 仅在有数据（已完成一次组装）时上报，避免空态/切章瞬间用空数组覆盖父层（会把「全注入」误判为「不注入」）。
   */
  useEffect(() => {
    if (!onOverrideChange || !data) return;
    onOverrideChange({
      character_ids: checkedCharacterIds,
      foreshadowing_ids: checkedForeshadowingIds,
      world_ids: checkedWorldIds,
    });
  }, [
    onOverrideChange,
    data,
    checkedCharacterIds,
    checkedForeshadowingIds,
    checkedWorldIds,
  ]);

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

  /** #1017：章级写作要求 blur 提交 —— 未变更不发；trim 后等于项目级（且非空）→ 收敛继承(null) */
  const commitRequirements = () => {
    const committed = chapterWritingRequirements ?? '';
    if (requirementsDraft === committed) return;
    const trimmed = requirementsDraft.trim();
    if (trimmed !== '' && trimmed === projectWritingStyle.trim()) {
      onWritingRequirementsChange?.(null);
    } else {
      onWritingRequirementsChange?.(requirementsDraft);
    }
  };

  /** #1017：「恢复继承」一键清除覆盖（传 null + 清空输入框） */
  const inheritRequirements = () => {
    setRequirementsDraft('');
    onWritingRequirementsChange?.(null);
  };

  return (
    <aside
      data-testid="context-panel"
      className="relative flex min-h-0 flex-1 flex-col"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-[13px] font-semibold">{t('write.context.title')}</span>
      </div>
      {/* #1017：章级写作要求栏（项目级 ∥ 章级 三层；blur 提交，null=继承） */}
      <div className="flex items-start gap-2 border-b border-line px-3 py-2">
        <textarea
          data-testid="context-writing-requirements"
          aria-label={t('write.context.chapterHint')}
          title={t('write.context.chapterHint')}
          placeholder={
            projectWritingStyle.trim() ? projectWritingStyle : t('write.context.requiredInherit')
          }
          value={requirementsDraft}
          disabled={!chapterId}
          rows={2}
          onChange={(e) => setRequirementsDraft(e.target.value)}
          onBlur={commitRequirements}
          className="min-h-0 flex-1 resize-none rounded border border-line bg-surface px-2 py-1 text-[12px] text-ink outline-none focus:border-accent disabled:opacity-60"
        />
        <button
          type="button"
          data-testid="context-writing-requirements-inherit"
          className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={inheritRequirements}
        >
          {t('write.context.requiredInheritBtn')}
        </button>
      </div>
      <div
        data-testid="context-panel-content"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3"
      >
        {/* #1017 入口常驻（D5）：空态/错误态仍无条件渲染三组「＋ 选择注入」入口（不依赖 assemble）；
            正常分支复用同一 GroupHeader 内嵌于 context-block-<source>，避免重复渲染两组按钮 */}
        {(error !== null || data === null) && projectId
          ? [...PICKER_SOURCES].map((source) => (
              <GroupHeader
                key={source}
                source={source}
                title={t(SOURCE_TITLE_KEYS[source] ?? source)}
                onPick={(s) => void openPicker(s)}
              />
            ))
          : null}
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
                  <GroupHeader title={title} source={source} onPick={(s) => void openPicker(s)} />
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
            {/* #1349 回执面：本章**实际**已注入（与上方预览态并列且可区分）。
                有记录但三源全空 = 「确实没注入任何条目」的事实回执，仍渲染 0 计数；
                无记录 = 回退提示，两者不混淆。明细只读，勾选框只在预览区块。 */}
            <section
              data-testid="context-injected-echo"
              className="rounded-md border border-line bg-surface p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{t('write.context.injected')}</span>
                {injectedDetail !== null && (
                  <span
                    data-testid="context-injected-count"
                    className="shrink-0 rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-2"
                  >
                    {t('write.context.injectedCount', { n: injectedCount })}
                  </span>
                )}
              </div>
              {injectedDetail === null ? (
                <div
                  data-testid="context-injected-empty"
                  className="mt-2 text-[12px] leading-relaxed text-ink-3"
                >
                  {t('write.context.injectedEmpty')}
                </div>
              ) : (
                <>
                  <div
                    data-testid="context-injected-execution"
                    className="mt-1 text-[11px] text-ink-3"
                  >
                    {t('write.context.injectedFrom', {
                      id: injectionRecord?.execution_id ?? '',
                    })}
                  </div>
                  {INJECTED_SECTIONS.map(({ key, titleKey }) =>
                    injectedDetail[key].length === 0 ? null : (
                      <div key={key} data-testid={`context-injected-${key}`} className="mt-2">
                        <div className="text-[12px] font-medium text-ink-2">{t(titleKey)}</div>
                        {injectedDetail[key].map((id) => (
                          <div
                            key={id}
                            data-testid={`context-injected-item-${id}`}
                            className="mt-0.5 truncate text-[12px] leading-relaxed text-ink-3"
                          >
                            {id}
                          </div>
                        ))}
                      </div>
                    ),
                  )}
                </>
              )}
            </section>
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
