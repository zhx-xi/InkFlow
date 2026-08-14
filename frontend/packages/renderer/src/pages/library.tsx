/** 设定库页（spec §7.3：项目上下文 + 面包屑 + 六分类 tab + 空态引导；F43：行编辑/删除 + 保存指示） */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronRight, Copy, Library, Pencil, Trash2 } from 'lucide-react';
import { apiFetch, ensureApiReady, errorMessage } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CopyDialog } from '../components/CopyDialog';
import { LibraryCreateDialog, type LibraryItemDTO } from '../components/LibraryCreateDialog';
import { MapWorkbench, type WorldMapDTO } from '../components/MapWorkbench';
import { OutlineTree } from '../components/OutlineTree';
import { TimelineView, type TimelineEventDTO, type TimelineViewData } from '../components/TimelineView';
import { Skeleton } from '../components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';
import { cn } from '../lib/cn';

type CatKey = 'characters' | 'world' | 'outline' | 'timeline' | 'foreshadow' | 'rag';

interface ListResponse {
  items: LibraryItemDTO[];
  total: number;
  offset: number;
  limit: number;
}

/** F43 P2：地图列表响应（GET /projects/{pid}/maps） */
interface MapListResponse {
  items: WorldMapDTO[];
  total: number;
  offset: number;
  limit: number;
}

type CatResponse = ListResponse;

const CATS: Array<{
  key: CatKey;
  labelKey: string;
  endpoint: (projectId: string) => string;
}> = [
  { key: 'characters', labelKey: 'nav.lib.characters', endpoint: (id) => `/api/v1/projects/${id}/characters` },
  { key: 'world', labelKey: 'nav.lib.world', endpoint: (id) => `/api/v1/projects/${id}/world-settings` },
  { key: 'outline', labelKey: 'nav.lib.outline', endpoint: (id) => `/api/v1/projects/${id}/outlines` },
  { key: 'timeline', labelKey: 'nav.lib.timeline', endpoint: (id) => `/api/v1/projects/${id}/timeline` },
  { key: 'foreshadow', labelKey: 'nav.lib.foreshadow', endpoint: (id) => `/api/v1/projects/${id}/foreshadowings` },
  { key: 'rag', labelKey: 'nav.lib.rag', endpoint: (id) => `/api/v1/projects/${id}/extractions/runs` },
];

const CAT_KEYS = CATS.map((c) => c.key);

/** F43 §3.1：编辑保存 PATCH 扁平端点（按 activeCat，已核实 backend/api/routers） */
const PATCH_ENDPOINTS: Record<Exclude<CatKey, 'rag'>, (id: string | number) => string> = {
  characters: (id) => `/api/v1/characters/${id}`,
  world: (id) => `/api/v1/world-settings/${id}`,
  outline: (id) => `/api/v1/outlines/${id}`,
  timeline: (id) => `/api/v1/timeline/events/${id}`,
  foreshadow: (id) => `/api/v1/foreshadowings/${id}`,
};

/** F43 §3.1：删除端点（世界观统一 ?cascade=true，D11 拍板） */
const DELETE_ENDPOINTS: Record<Exclude<CatKey, 'rag'>, (id: string | number) => string> = {
  characters: (id) => `/api/v1/characters/${id}`,
  world: (id) => `/api/v1/world-settings/${id}?cascade=true`,
  outline: (id) => `/api/v1/outlines/${id}`,
  timeline: (id) => `/api/v1/timeline/events/${id}`,
  foreshadow: (id) => `/api/v1/foreshadowings/${id}`,
};

/** #189 模式：「已保存」指示自动隐藏间隔（ms） */
const SAVE_INDICATOR_HIDE_MS = 2_000;

/** #189 模式：页面顶部保存指示状态（idle 不渲染 / saving / saved） */
type SaveState = 'idle' | 'saving' | 'saved';

/** F43 P1（§3.3）：世界观复制结果（F37 既有响应，前端消费 created/skipped/warnings） */
interface WorldCopyResult {
  created: Array<Record<string, unknown>>;
  skipped: string[];
  maps_created: Array<Record<string, unknown>>;
  pins_created: number;
  warnings: string[];
}

/** F43 P1（§5.5）：复制对话框状态（行内 subtree 带 rootId；顶部整体 all 无 rootId） */
interface CopyState {
  open: boolean;
  mode: 'subtree' | 'all';
  rootId?: string | number;
}

/** F43 P1（§5.3）：前端建树节点（parent_id 树） */
interface WorldTreeNode {
  item: LibraryItemDTO;
  children: WorldTreeNode[];
}

/** F43 P1（D3）：世界观分类默认分组（#352 拍板仅地图；数据自定义自动进 chips，无「全部」选项） */
const DEFAULT_WORLD_CATS = ['地图'];

/**
 * F43 P1（§5.3）：items → 树——顶层 = parent_id null/缺失；按 items 顺序保序；
 * 孤儿（parent_id 指向不存在节点）降级为顶层（E18 防御）。
 */
function buildWorldTree(items: LibraryItemDTO[]): WorldTreeNode[] {
  const nodes = new Map<string | number, WorldTreeNode>();
  for (const item of items) {
    nodes.set(item.id, { item, children: [] });
  }
  const roots: WorldTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(item.id);
    if (!node) continue;
    const parentId = item.parent_id;
    if (parentId !== null && parentId !== undefined && nodes.has(parentId)) {
      nodes.get(parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

/** F43 P1（§5.3）：递归树节点视图——toggle 仅渲染在有子节点行；操作按钮随 D12 悬停显示 */
function WorldNodeView({
  node,
  depth,
  collapsed,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
}: {
  node: WorldTreeNode;
  depth: number;
  collapsed: Set<string | number>;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onCopy: (item: LibraryItemDTO) => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  const hasChildren = children.length > 0;
  const isCollapsed = collapsed.has(item.id);
  return (
    <div className="tree-node">
      <div
        className="tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60"
        style={{ paddingLeft: depth * 18 + 12 }}
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`world-tree-toggle-${item.id}`}
            aria-label={isCollapsed ? t('nav.expand') : t('nav.collapse')}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onToggle(item.id)}
          >
            <ChevronRight
              className={cn('h-3.5 w-3.5 transition-transform duration-180', !isCollapsed && 'rotate-90')}
              aria-hidden="true"
            />
          </button>
        ) : (
          <span className="h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1 truncate">{item.name ?? ''}</span>
        {item.category ? (
          <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
            {item.category}
          </span>
        ) : null}
        {/* F43 P1：行内操作按钮（D12 悬停显示；P0 编辑/删除 testid 不变 + 复制 world-copy-<id>） */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            data-testid={`lib-edit-${item.id}`}
            aria-label={`${t('lib.edit')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onEdit(item)}
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`lib-delete-${item.id}`}
            aria-label={`${t('lib.delete')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onDelete(item)}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`world-copy-${item.id}`}
            aria-label={`${t('lib.copy.title')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onCopy(item)}
          >
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      {!isCollapsed &&
        children.map((child) => (
          <WorldNodeView
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            collapsed={collapsed}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onCopy={onCopy}
          />
        ))}
    </div>
  );
}

function isCatKey(v: string | null): v is CatKey {
  return v !== null && (CAT_KEYS as string[]).includes(v);
}

export function LibraryPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const loadProjects = useProjectStore((s) => s.loadProjects);
  const selectProject = useProjectStore((s) => s.selectProject);

  // URL cat 查询参数作为初始 tab（侧边导航 /library?cat=<key> 直达联动）
  const catParam = searchParams.get('cat');
  const [activeCat, setActiveCat] = useState<CatKey>(() =>
    isCatKey(catParam) ? catParam : 'characters',
  );
  const [items, setItems] = useState<ListResponse['items']>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // #196：分类实体手动创建对话框开关（仅非 RAG 分类空态 CTA 打开）
  const [createOpen, setCreateOpen] = useState(false);
  // F43：行编辑对象（非空 = 编辑模式预填；随对话框关闭重置）
  const [editing, setEditing] = useState<LibraryItemDTO | null>(null);
  // F43：行删除确认对象（非空 = ConfirmDialog 打开）
  const [pendingDelete, setPendingDelete] = useState<LibraryItemDTO | null>(null);
  // #189 模式：顶部保存指示状态 + 自动隐藏计时器 ref（clearTimeout 防重叠）
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const saveHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // F43 P1：世界观分类筛选（null = 未选 → 展示所有，D3 无「全部」选项）
  const [activeWorldCat, setActiveWorldCat] = useState<string | null>(null);
  // F43 P1：世界观树收起集合（默认全部展开；点击 toggle 收起/展开）
  const [collapsedIds, setCollapsedIds] = useState<Set<string | number>>(new Set());
  // F43 P1：复制对话框状态（行内 subtree / 顶部整体 all）
  const [copyState, setCopyState] = useState<CopyState | null>(null);
  // F43 P2：地图列表（挂载时拉取）+ 当前选中地图 + 工作台态（世界观 tab 默认进入）
  const [maps, setMaps] = useState<WorldMapDTO[]>([]);
  const [activeMapId, setActiveMapId] = useState<string | null>(null);
  const [workbenchActive, setWorkbenchActive] = useState(false);
  // F43 P4（§5.16）：时间线完整双视图——event_timeline 存 items（列表/空态），narrative_order 单独存
  const [timelineNarrative, setTimelineNarrative] = useState<TimelineEventDTO[]>([]);
  // F43 P3（§5.15）：章节标题映射（chapter_id → title，大纲 tab 加载时拉取）
  const [chapterTitles, setChapterTitles] = useState<Record<string, string>>({});

  const cat = CATS.find((c) => c.key === activeCat) ?? CATS[0];
  // rag 无创建端点（CTA 已走跳转分支），对话框仅在五个可创建分类下渲染
  const createCat = activeCat === 'rag' ? null : activeCat;
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? null;

  // F43 P1（D-11）：世界观分类 chips = 默认分组 + 数据中自定义 category（去重，无「全部」）
  const worldCategories = useMemo(() => {
    if (activeCat !== 'world') return [];
    const cats = new Set<string>(DEFAULT_WORLD_CATS);
    for (const item of items) {
      const cat = (item.category ?? '').trim();
      if (cat) cats.add(cat);
    }
    return [...cats];
  }, [activeCat, items]);

  // F43 P1（§5.3）：世界观树（parent_id 前端建树，顶层保序 + 孤儿降级）
  const worldRoots = useMemo(
    () => (activeCat === 'world' ? buildWorldTree(items) : []),
    [activeCat, items],
  );
  // §5.4：分类筛选作用于顶层节点（含其子树整体显隐，树不拆散）
  const filteredWorldRoots = useMemo(
    () =>
      activeWorldCat === null
        ? worldRoots
        : worldRoots.filter((node) => node.item.category === activeWorldCat),
    [activeWorldCat, worldRoots],
  );

  // F43 P1（D-13）：建议标签 = 当前项目角色 extra.groups 并集（数据驱动，供创建/编辑对话框）
  const tagSuggestions = useMemo(() => {
    if (activeCat !== 'characters') return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of items) {
      const groups = item.extra?.groups;
      if (!Array.isArray(groups)) continue;
      for (const g of groups) {
        if (typeof g !== 'string') continue;
        const tag = g.trim();
        if (tag && !seen.has(tag)) {
          seen.add(tag);
          out.push(tag);
        }
      }
    }
    return out;
  }, [activeCat, items]);

  // F43 P1（§5.5/E20）：复制目标项目 = projects 排除当前项目；空数组 → 复制按钮 disabled（E21）
  const copyTargetOptions = useMemo(
    () =>
      projects
        .filter((p) => p.id !== currentProjectId)
        .map((p) => ({ id: p.id, name: p.name })),
    [projects, currentProjectId],
  );

  // 挂载加载项目列表（Electron 下等待 preload 注入，与项目页同源防 401 竞态）
  useEffect(() => {
    void (async () => {
      await ensureApiReady();
      void loadProjects();
    })();
  }, [loadProjects]);

  // F43 P2：挂载/项目切换时拉取地图列表（世界观点亮徽标的数据源；失败静默空列表）
  useEffect(() => {
    if (!currentProjectId) {
      setMaps([]);
      return;
    }
    let cancelled = false;
    void apiFetch<MapListResponse>(`/api/v1/projects/${currentProjectId}/maps`)
      .then((data) => {
        if (!cancelled) setMaps(data.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setMaps([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId]);

  // F43 P3：章节标题映射（章关联徽标）
  useEffect(() => {
    if (!currentProjectId || activeCat !== 'outline') {
      setChapterTitles({});
      return;
    }
    let cancelled = false;
    void apiFetch<{ items?: Array<{ id: string | number; title?: string }> }>(
      `/api/v1/projects/${currentProjectId}/chapters`,
    )
      .then((data) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const ch of data.items ?? []) {
          const title = ch.title?.trim();
          if (title) map[String(ch.id)] = title;
        }
        setChapterTitles(map);
      })
      .catch(() => {
        if (!cancelled) setChapterTitles({});
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat]);

  // URL cat 变化（AppNav 直达）→ 同步激活 tab
  useEffect(() => {
    const p = searchParams.get('cat');
    if (isCatKey(p) && p !== activeCat) setActiveCat(p);
    // F43 P2：直达世界观 tab → 默认进入地图工作台
    if (p === 'world') setWorkbenchActive(true);
  }, [searchParams, activeCat]);

  // 拉取分类端点（timeline 特例 TimelineView 双数组；失败 → error 态可重试）
  useEffect(() => {
    if (!currentProjectId) {
      setItems([]);
      setTimelineNarrative([]);
      setLoading(false);
      setLoadFailed(false);
      return;
    }
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    void apiFetch<CatResponse>(current.endpoint(currentProjectId))
      .then((data) => {
        if (cancelled) return;
        if (current.key === 'timeline') {
          const view = data as unknown as TimelineViewData;
          setItems((view.event_timeline ?? []) as unknown as LibraryItemDTO[]);
          setTimelineNarrative(view.narrative_order ?? []);
        } else {
          setItems(data.items ?? []);
          setTimelineNarrative([]);
        }
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTimelineNarrative([]);
        setLoading(false);
        setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey]);

  // 卸载清理「已保存」自动隐藏计时器（防卸载后 timer 回调 setState）
  useEffect(
    () => () => {
      if (saveHideTimerRef.current) clearTimeout(saveHideTimerRef.current);
    },
    [],
  );

  const handleTabChange = (key: CatKey) => {
    setActiveCat(key);
    setSearchParams({ cat: key });
    // F43 P2：进入世界观 tab 默认地图工作台态（退出后重进恢复）
    if (key === 'world') setWorkbenchActive(true);
  };

  const handleProjectChange = (id: string) => {
    selectProject(id);
  };

  // #196 + F43：保存回调——editing 非空 → PATCH 扁平端点；为空 → POST 创建端点（#196 现状保留）
  const handleSave = async (input: Record<string, unknown>) => {
    if (!currentProjectId) return;
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    // rag 不适用（无创建/编辑端点；CTA 已走跳转分支，此处防御性早退）
    if (current.key === 'rag') return;
    try {
      if (editing) {
        // F43 §5.2：编辑保存 → PATCH 扁平端点（spec §3.1 表）→ 关闭 + 刷新 + 顶部「已保存」指示
        setSaveState('saving');
        await apiFetch(PATCH_ENDPOINTS[current.key as Exclude<CatKey, 'rag'>](editing.id), {
          method: 'PATCH',
          body: input,
        });
      } else {
        // 关键：timeline 分类的创建端点是 /timeline/events（不是 /timeline 列表端点）
        const createEndpoint =
          current.key === 'timeline'
            ? `/api/v1/projects/${currentProjectId}/timeline/events`
            : current.endpoint(currentProjectId);
        await apiFetch(createEndpoint, { method: 'POST', body: input });
      }
      setCreateOpen(false);
      setEditing(null);
      setReloadKey((k) => k + 1); // 列表实时刷新（复用既有 reloadKey 机制）
      if (editing) {
        // #189 模式：仅编辑保存路径驱动顶部指示（D-5；创建/删除保持既有 toast/刷新语义）
        setSaveState('saved');
        if (saveHideTimerRef.current) clearTimeout(saveHideTimerRef.current);
        saveHideTimerRef.current = setTimeout(() => setSaveState('idle'), SAVE_INDICATOR_HIDE_MS);
      }
    } catch (err) {
      if (editing) setSaveState('idle');
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  // F43 §5.3：删除确认 → DELETE（世界观 ?cascade=true）→ 关闭 + 刷新 + ok toast；
  // 失败同样关闭确认框（E2：失败后不再重复确认），err toast
  const handleDelete = async () => {
    if (!pendingDelete || !currentProjectId) return;
    const target = pendingDelete;
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    if (current.key === 'rag') return;
    try {
      await apiFetch(DELETE_ENDPOINTS[current.key as Exclude<CatKey, 'rag'>](target.id), {
        method: 'DELETE',
      });
      setPendingDelete(null);
      setReloadKey((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setPendingDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  // F43 P1（§5.5/§3.3）：复制确认 → POST F37 copy 端点 → 结果 toast；
  // 成功关框；失败 err toast + 对话框保持打开可重试（E24）
  const handleCopy = async (targetId: string, selfOnly: boolean, state: CopyState) => {
    if (!currentProjectId) return;
    const targetProject = projects.find((p) => p.id === targetId);
    try {
      const body =
        state.mode === 'all'
          ? { source_project_id: currentProjectId }
          : {
              source_project_id: currentProjectId,
              root_setting_id: String(state.rootId),
              ...(selfOnly ? { self_only: true } : {}),
            };
      const result = await apiFetch<WorldCopyResult>(
        `/api/v1/projects/${targetId}/world-settings/copy`,
        { method: 'POST', body },
      );
      useToastStore
        .getState()
        .pushToast('ok', t('lib.copy.result', { n: result.created.length, name: targetProject?.name ?? targetId }));
      // E23：warnings 非空 → 追加 warn toast（第一条 warning，不刷屏）；无 warnings 但 skipped 非空 → 跳过数
      if (result.warnings.length > 0) {
        useToastStore.getState().pushToast('warn', result.warnings[0]);
      } else if (result.skipped.length > 0) {
        useToastStore.getState().pushToast('warn', t('lib.copy.skipped', { n: result.skipped.length }));
      }
      setCopyState(null);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const toggleCollapsed = (id: string | number) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div data-testid="library-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('lib.title')}</h1>

      {/* 项目上下文：选择器 + 面包屑（入口语义 = 当前项目的设定库） */}
      <div className="mt-5 flex flex-wrap items-center gap-4">
        <Select value={currentProjectId ?? undefined} onValueChange={handleProjectChange}>
          <SelectTrigger data-testid="library-project-select" aria-label={t('lib.projectSelect')} className="w-56">
            <SelectValue placeholder={t('lib.projectSelect')} />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div data-testid="library-breadcrumb" className="text-[13px] text-ink-2">
          {t('lib.title')}
          {currentProject ? ` · ${currentProject.name}` : ''} <span className="mx-1 text-ink-3">/</span>
          <span className="text-ink">{t(cat.labelKey)}</span>
        </div>
        {/* F43 §5.4：顶部保存指示（#189 模式；仅编辑保存路径驱动，saved 2s 自动隐藏） */}
        {saveState !== 'idle' && (
          <span data-testid="lib-save-indicator" className="ml-auto text-[12px] text-ok">
            {saveState === 'saving' ? t('lib.saving') : t('lib.saved')}
          </span>
        )}
      </div>

      {currentProjectId === null ? (
        <div
          data-testid="library-empty"
          className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <Library className="h-10 w-10 text-ink-3" aria-hidden="true" />
          <p className="mt-3 font-serif text-[17px] font-semibold text-ink">{t('lib.empty.noProject')}</p>
          <button
            type="button"
            data-testid="library-go-projects"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => navigate('/projects')}
          >
            {t('lib.empty.goProjects')}
          </button>
        </div>
      ) : (
        <>
          {/* 六分类 tab（角色/世界观/大纲/时间线/伏笔/知识库 RAG） */}
          <div
            data-testid="library-tabs"
            role="tablist"
            aria-label={t('lib.title')}
            className="mt-6 flex flex-wrap gap-1 border-b border-line"
          >
            {CATS.map((c) => (
              <button
                key={c.key}
                type="button"
                role="tab"
                aria-selected={c.key === activeCat}
                className={cn(
                  'rounded-t-md border-b-2 px-3.5 py-2 text-[13px] transition-colors duration-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  c.key === activeCat
                    ? 'border-accent font-medium text-accent'
                    : 'border-transparent text-ink-2 hover:text-ink',
                )}
                onClick={() => handleTabChange(c.key)}
              >
                {t(c.labelKey)}
              </button>
            ))}
          </div>

          <div className="mt-5">
            {loading ? (
              <div data-testid="library-list" className="space-y-2">
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
              </div>
            ) : loadFailed ? (
              <div
                data-testid="library-error"
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.loadFailed')}</p>
                <button
                  type="button"
                  data-testid="library-retry"
                  className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => setReloadKey((k) => k + 1)}
                >
                  {t('lib.retry')}
                </button>
              </div>
            ) : items.length === 0 ? (
              <div
                data-testid="library-tab-empty"
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.empty.tab', { name: t(cat.labelKey) })}</p>
                <button
                  type="button"
                  data-testid="library-tab-empty-cta"
                  className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => (cat.key === 'rag' ? navigate('/writing') : setCreateOpen(true))}
                >
                  {t('lib.empty.create')}
                </button>
              </div>
            ) : activeCat === 'world' && workbenchActive ? (
              /* F43 P2（§5.8）：地图工作台——左树（P1 复用 + 🗺 徽标）+ 右画布/pin 列表 */
              <MapWorkbench
                projectId={currentProjectId}
                worldItems={items}
                maps={maps}
                activeMapId={activeMapId}
                onSelectMap={(mapId) => setActiveMapId(mapId)}
                onExitWorkbench={() => setWorkbenchActive(false)}
                onClearMap={() => setActiveMapId(null)}
                worldCategories={worldCategories}
                activeWorldCat={activeWorldCat}
                onWorldCatChange={setActiveWorldCat}
                collapsedIds={collapsedIds}
                onToggle={toggleCollapsed}
                onEdit={(item) => {
                  setEditing(item);
                  setCreateOpen(true);
                }}
                onDelete={(item) => setPendingDelete(item)}
                onCopy={(item) => setCopyState({ open: true, mode: 'subtree', rootId: item.id })}
                onCopyAll={() => setCopyState({ open: true, mode: 'all' })}
                copyTargetOptions={copyTargetOptions}
              />
            ) : activeCat === 'world' ? (
              <>
                {/* F43 P1（§5.4）：世界观分类筛选工具栏——默认分组 + 数据自定义 chips（无「全部」，
                    未选 = 展示所有，再点同 chip 取消）；右上角顶部整体复制（E21 单项目 disabled） */}
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="text-[12px] text-ink-2">{t('lib.worldCat.label')}</span>
                  {worldCategories.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      data-testid={`world-cat-filter-${cat}`}
                      aria-pressed={activeWorldCat === cat}
                      className={cn(
                        'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        activeWorldCat === cat
                          ? 'border-accent bg-accent/10 text-accent'
                          : 'border-line text-ink-2 hover:border-accent hover:text-accent',
                      )}
                      onClick={() => setActiveWorldCat(activeWorldCat === cat ? null : cat)}
                    >
                      {cat}
                    </button>
                  ))}
                  <button
                    type="button"
                    data-testid="world-copy-all"
                    title={copyTargetOptions.length === 0 ? t('lib.copy.needTwo') : undefined}
                    disabled={copyTargetOptions.length === 0}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => setCopyState({ open: true, mode: 'all' })}
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('lib.copy.all')}
                  </button>
                </div>
                {/* F43 P1（§5.3）：世界观树视图（library-list testid 不变；筛选无匹配 → 轻空态 E19） */}
                <div
                  data-testid="library-list"
                  className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
                >
                  {filteredWorldRoots.length === 0 ? (
                    <div className="px-4 py-8 text-center text-[13px] text-ink-2">
                      {t('common.empty')}
                    </div>
                  ) : (
                    filteredWorldRoots.map((node) => (
                      <WorldNodeView
                        key={String(node.item.id)}
                        node={node}
                        depth={0}
                        collapsed={collapsedIds}
                        onToggle={toggleCollapsed}
                        onEdit={(item) => {
                          setEditing(item);
                          setCreateOpen(true);
                        }}
                        onDelete={(item) => setPendingDelete(item)}
                        onCopy={(item) => setCopyState({ open: true, mode: 'subtree', rootId: item.id })}
                      />
                    ))
                  )}
                </div>
              </>
            ) : activeCat === 'outline' ? (
              <OutlineTree
                outlines={items}
                chapterTitles={chapterTitles}
                onEdit={(item) => {
                  setEditing(item);
                  setCreateOpen(true);
                }}
                onDelete={(item) => setPendingDelete(item)}
                onAdd={() => {
                  setEditing(null);
                  setCreateOpen(true);
                }}
              />
            ) : activeCat === 'timeline' ? (
              <TimelineView
                projectId={currentProjectId}
                eventTimeline={items}
                narrativeOrder={timelineNarrative}
              />
            ) : (
              <ul
                data-testid="library-list"
                className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
              >
                {items.map((item) => {
                  // F43 P1（§5.1/§5.2）：角色行等级徽标 + 标签 chips（缺省不渲染）
                  const isCharacters = activeCat === 'characters';
                  const rank = isCharacters ? String(item.extra?.role_rank ?? '') : '';
                  const groups =
                    isCharacters && Array.isArray(item.extra?.groups)
                      ? (item.extra!.groups as unknown[]).filter(
                          (g): g is string => typeof g === 'string',
                        )
                      : [];
                  return (
                    <li
                      key={String(item.id)}
                      className="group lib-item flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink"
                    >
                      <span className="min-w-0 flex-1 truncate">{item.title ?? item.name ?? ''}</span>
                      {rank !== '' && (
                        <span
                          data-testid={`lib-rank-${item.id}`}
                          className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent"
                        >
                          {t(`lib.rank.${rank}`)}
                        </span>
                      )}
                      {groups.length > 0 && (
                        <div data-testid={`lib-tags-${item.id}`} className="flex shrink-0 items-center gap-1">
                          {groups.map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      {/* F43 §5.1（D12）：悬停显示操作按钮；focus-within 保证键盘可达可见 */}
                      {activeCat !== 'rag' && (
                        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                          <button
                            type="button"
                            data-testid={`lib-edit-${item.id}`}
                            aria-label={`${t('lib.edit')} ${item.title ?? item.name ?? ''}`}
                            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => {
                              setEditing(item);
                              setCreateOpen(true);
                            }}
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            data-testid={`lib-delete-${item.id}`}
                            aria-label={`${t('lib.delete')} ${item.title ?? item.name ?? ''}`}
                            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => setPendingDelete(item)}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}

      {/* #196 + F43：创建/编辑双模式对话框（挂在页面根部，open 受控；RAG 分类不渲染） */}
      {createCat !== null && (
        <LibraryCreateDialog
          open={createOpen}
          cat={createCat}
          editing={editing}
          tagSuggestions={tagSuggestions}
          onSave={handleSave}
          onOpenChange={(open) => {
            setCreateOpen(open);
            if (!open) setEditing(null); // 关闭即清空编辑态（重开创建对话框不残留预填）
          }}
        />
      )}

      {/* F43 P1（§5.5）：世界观复制对话框（行内 subtree + 顶部整体 all 共用；#195 遮罩不关闭） */}
      {copyState && (
        <CopyDialog
          open={copyState.open}
          mode={copyState.mode}
          targetOptions={copyTargetOptions}
          onCopy={(targetId, selfOnly) => handleCopy(targetId, selfOnly, copyState)}
          onOpenChange={(open) => {
            if (!open) setCopyState(null);
          }}
        />
      )}

      {/* F43 §5.3：删除二次确认（#195：遮罩点击不关闭；关闭仅 取消/Esc/确认成功） */}
      {pendingDelete && (
        <ConfirmDialog
          open
          title={t('lib.delete.title', { name: pendingDelete.title ?? pendingDelete.name ?? '' })}
          message={
            activeCat === 'world' ? (
              <>
                <p>{t('lib.delete.confirm')}</p>
                <p className="text-err">{t('lib.delete.worldCascade')}</p>
              </>
            ) : (
              t('lib.delete.confirm')
            )
          }
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="lib-confirm"
          onConfirm={() => void handleDelete()}
          onOpenChange={(open) => {
            if (!open) setPendingDelete(null);
          }}
        />
      )}
    </div>
  );
}
