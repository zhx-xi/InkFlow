/** 设定库页（spec §7.3：项目上下文 + 面包屑 + 六分类 tab + 空态引导；F43：行编辑/删除 + 保存指示；F48：知识图谱 tab） */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Library } from 'lucide-react';
import { apiFetch, ensureApiReady, errorMessage } from '../api/client';
import {
  createKnowledgeRelation,
  deleteKnowledgeRelation,
  listKnowledgeRelations,
  updateKnowledgeRelation,
  type GraphEdge,
  type GraphNode,
  type KnowledgeRelation,
} from '../api/knowledge-graph';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { LibraryCharacterDetail, type LibraryCharacterDetailHandle } from '../components/LibraryCharacterDetail';
import { CopyDialog } from '../components/CopyDialog';
import { AIExtractEntry } from '../components/extract/AIExtractEntry';
import { KnowledgeGraphView } from '../components/knowledge-graph/KnowledgeGraphView';
import { RelationForm, type KnowledgeRelationFormData } from '../components/knowledge-graph/RelationForm';
import { LibraryCreateDialog, type LibraryItemDTO } from '../components/LibraryCreateDialog';
import { LibraryItemList } from '../components/LibraryItemList';
import { MapWorkbench, type WorldMapDTO } from '../components/MapWorkbench';
import { Pagination } from '../components/Pagination';
import { OutlineTree, type OutlineLevel } from '../components/OutlineTree';
import { TimelineView } from '../components/TimelineView';
import { WorldCatActionButtons } from '../components/WorldCatActionButtons';
import { WorldCategoryDialog } from '../components/WorldCategoryDialog';
import { WorldCategoryToolbar } from '../components/WorldCategoryToolbar';
import { buildWorldTree, filterWorldTree, WorldNodeView } from '../components/WorldNodeView';
import { Skeleton } from '../components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { useDataChangeSubscription } from '../hooks/useDataChangeSubscription';
import { useWorldCategories, type WorldCategoryEntity } from '../hooks/useWorldCategories';
import { OUTLINE_PAGE_SIZE, useOutlineLibrary } from '../hooks/useOutlineLibrary';
import { LIBRARY_PAGE_SIZE, useLibraryPagedList, type PageableCatKey } from '../hooks/useLibraryPagedList';
import { useWorldFullList } from '../hooks/useWorldFullList';
import { useLibraryCategoryData } from '../hooks/useLibraryCategoryData';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';
import { cn } from '../lib/cn';
type CatKey = 'characters' | 'world' | 'outline' | 'timeline' | 'foreshadow' | 'knowledge';
/** F23 §15.6.2（#1088 A3）：本页关心的项目作用域变更域（含子实体独立域）；事件到达一律 FR。 */
const LIBRARY_DATA_CHANGE_DOMAINS = [
  'map', 'map_pin', 'character', 'character_group',
  'character_relation', 'outline', 'plot_point', 'story_arc',
  'world_setting', 'world_category', 'foreshadowing', 'timeline_event', 'knowledge_relation',
] as const;
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
  { key: 'knowledge', labelKey: 'nav.lib.knowledge', endpoint: (id) => `/api/v1/projects/${id}/knowledge-graph` },
];
const CAT_KEYS = CATS.map((c) => c.key);
/** #1300：服务端分页分类（后端支持 ?limit=&offset= 且返回 total；其余分类形态特殊不自带分页） */
const PAGEABLE_CATS: PageableCatKey[] = ['characters', 'foreshadow'];
/** #1320：world 用全量取数（整树语义），不进分页分类 → 只读该分类 */
/** F43 §3.1：编辑保存 PATCH 扁平端点（按 activeCat，已核实 backend/api/routers） */
const PATCH_ENDPOINTS: Record<Exclude<CatKey, 'knowledge'>, (id: string | number) => string> = {
  characters: (id) => `/api/v1/characters/${id}`,
  world: (id) => `/api/v1/world-settings/${id}`,
  outline: (id) => `/api/v1/outlines/${id}`,
  timeline: (id) => `/api/v1/timeline/events/${id}`,
  foreshadow: (id) => `/api/v1/foreshadowings/${id}`,
};
/** F43 §3.1：删除端点（世界观统一 ?cascade=true，D11 拍板） */
const DELETE_ENDPOINTS: Record<Exclude<CatKey, 'knowledge'>, (id: string | number) => string> = {
  characters: (id) => `/api/v1/characters/${id}`,
  world: (id) => `/api/v1/world-settings/${id}?cascade=true`,
  outline: (id) => `/api/v1/outlines/${id}`,
  timeline: (id) => `/api/v1/timeline/events/${id}`,
  foreshadow: (id) => `/api/v1/foreshadowings/${id}`,
};
/** F48 §5.4：图谱节点类型 → 实体编辑分类 tab（map_pin 归属世界观地图工作台） */
const KG_ENTITY_CAT: Record<GraphNode['type'], CatKey> = {
  character: 'characters', world: 'world', outline: 'outline',
  timeline: 'timeline', foreshadow: 'foreshadow', map_pin: 'world',
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
/** F43 P1（§5.5/§5.3）：复制对话框状态 + 前端建树节点（parent_id 树） */
interface CopyState { open: boolean; mode: 'subtree' | 'all'; rootId?: string | number }
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
  // #1300：分类列表装配由 useLibraryCategoryData / useLibraryPagedList 持有（本文件不再持有其 state）
  const [reloadKey, setReloadKey] = useState(0);
  // #196：分类实体手动创建对话框开关（仅非 knowledge 分类空态 CTA 打开）
  const [createOpen, setCreateOpen] = useState(false);
  // F43：行编辑对象（非空 = 编辑模式预填；随对话框关闭重置）
  const [editing, setEditing] = useState<LibraryItemDTO | null>(null);
  // #675：outline 分级创建上下文（＋整本/＋卷/＋章细纲 → 预填 level + parent_id）
  const [addCtx, setAddCtx] = useState<{ level: OutlineLevel; parentId?: string | number | null } | null>(null);
  // F43：行删除确认对象（非空 = ConfirmDialog 打开）
  const [pendingDelete, setPendingDelete] = useState<LibraryItemDTO | null>(null);
  // #189 模式：顶部保存指示状态 + 自动隐藏计时器 ref（clearTimeout 防重叠）
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const saveHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // F43 P1：世界观分类筛选（null = 未选 → 展示所有，D3 无「全部」选项）
  const [activeWorldCat, setActiveWorldCat] = useState<string | null>(null);
  // #1320：角色等级筛选（'all' = 总览）。上提自 LibraryItemList 内部 state —— 筛选需下沉
  // 服务端（?role_rank=），否则 total 吃未筛选总数、跨页项漏取。
  const [characterRank, setCharacterRank] = useState<string>('all');
  // F43 P1：世界观树收起集合（默认全部展开；点击 toggle 收起/展开）
  const [collapsedIds, setCollapsedIds] = useState<Set<string | number>>(new Set());
  // F43 P1：复制对话框状态（行内 subtree / 顶部整体 all）
  const [copyState, setCopyState] = useState<CopyState | null>(null);
  // F43 P2：地图列表（挂载时拉取）+ 当前选中地图 + 工作台态（世界观 tab 默认进入）
  const [maps, setMaps] = useState<WorldMapDTO[]>([]);
  const [activeMapId, setActiveMapId] = useState<string | null>(null);
  const [workbenchActive, setWorkbenchActive] = useState(false);
  // F48：知识图谱 tab——图谱视图/关系列表切换 + 图谱数据 + 关系增删改表单态
  const [kgView, setKgView] = useState<'graph' | 'list'>('graph');
  const [relations, setRelations] = useState<KnowledgeRelation[]>([]);
  const [relationFormOpen, setRelationFormOpen] = useState(false);
  const [editingRelation, setEditingRelation] = useState<KnowledgeRelation | null>(null);
  const [pendingRelationDelete, setPendingRelationDelete] = useState<KnowledgeRelation | null>(null);
  const characterDetailRef = useRef<LibraryCharacterDetailHandle>(null);

  // #1002：大纲 tab 数据装配（排序 toggle/顶层分页/卷章全量缓存，含章标题映射）——自本文件拆出以守 900 行护栏
  const outlineLib = useOutlineLibrary(currentProjectId, activeCat, reloadKey);
  // #1300：设定库分页分类（characters/world/foreshadow）的服务端分页装配——自本文件拆出
  // （本文件基线 897 行 / 护栏 900，分页逻辑不得内联；同 useOutlineLibrary 先例）
  const catEndpoint = (CATS.find((c) => c.key === activeCat) ?? CATS[0]).endpoint;
  // #1320：角色等级筛选下沉服务端（extraQuery 变化 → hook 内部重置页码到第 1 页）。
  // world 不进分页分类（下）→ 恒 null；仅 characters 需要该条件。
  const pagedExtraQuery = useMemo(
    () =>
      activeCat === 'characters' && characterRank !== 'all'
        ? { role_rank: characterRank }
        : null,
    [activeCat, characterRank],
  );
  const pagedLib = useLibraryPagedList<LibraryItemDTO>(
    currentProjectId,
    activeCat,
    reloadKey,
    catEndpoint,
    pagedExtraQuery,
  );
  // #1300：timeline / knowledge 分类装配（图谱聚合 / 双数组）——自本文件拆出以守 900 行护栏
  const catData = useLibraryCategoryData<LibraryItemDTO>(
    currentProjectId,
    activeCat,
    reloadKey,
    CATS,
  );
  // #1300：分页分类用 pagedLib（#1320：world 已移出——整树语义需全量数据，见 worldLib）；其余（timeline/knowledge）由 catData、outline 由 outlineLib 持有
  const isPagedCat = PAGEABLE_CATS.includes(activeCat as PageableCatKey);
  // #1320：world 全量取数（不分页；清 51+ 条静默截断 + 树构建的数据源失真）
  const worldLib = useWorldFullList<LibraryItemDTO>(currentProjectId, activeCat, reloadKey);
  const isWorldCat = activeCat === 'world';
  const listItems = isPagedCat
    ? pagedLib.items
    : isWorldCat
      ? worldLib.items
      : (catData.items as LibraryItemDTO[]);
  const listLoading = isPagedCat ? pagedLib.loading : isWorldCat ? worldLib.loading : catData.loading;
  const listFailed = isPagedCat ? pagedLib.loadFailed : isWorldCat ? worldLib.loadFailed : catData.loadFailed;
  const { timelineNarrative, graphNodes, graphEdges } = catData;
  // F23 §15.6.2（#1088 批 A3）：数据面变更订阅——外部（CLI/HTTP/MCP/agent）写入 → 事件到达
  // 后 bump reloadKey，复用既有 effect 全量重拉（maps / 分类列表 / 大纲；FR 粒度裁决，不新增局部更新路径）。
  useDataChangeSubscription(LIBRARY_DATA_CHANGE_DOMAINS, () => setReloadKey((k) => k + 1));
  // #1002：outline tab 的 loading/error 由 hook 持有；其余分类沿用通用 effect 态（非 outline 行为零改动）
  const viewLoading = activeCat === 'outline' ? outlineLib.loading : listLoading;
  const viewFailed = activeCat === 'outline' ? outlineLib.loadFailed : listFailed;

  const cat = CATS.find((c) => c.key === activeCat) ?? CATS[0];
  // knowledge 无创建端点（图谱关系编辑走画布/列表内交互），对话框仅在五个可创建分类下渲染
  const createCat = activeCat === 'knowledge' ? null : activeCat;
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? null;
  // #389：世界观分类实体列表 + 新建分类（state/加载/保存逻辑集中在 hook）
  const { worldCategoryList, worldCatDialogOpen, setWorldCatDialogOpen, handleWorldCatSave, handleWorldCatDelete } = useWorldCategories(currentProjectId, activeCat, reloadKey, () => {
    setReloadKey((k) => k + 1);
    setActiveWorldCat(null);
  });
  const worldCatEntities = useMemo<WorldCategoryEntity[]>(() => {
    if (activeCat !== 'world') return [];
    const seen = new Set<string>();
    return worldCategoryList.filter((c) => {
      const name = c.name.trim();
      if (!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
  }, [activeCat, worldCategoryList]);
  const worldCategories = useMemo(() => worldCatEntities.map((c) => c.name), [worldCatEntities]);
  // F43 P1 §5.3 世界观树；#588：已有根条目（parent_id===null）时仍保留「创建」入口，允许创建子分类
  const worldRoots = useMemo(
    () => (activeCat === 'world' ? buildWorldTree(listItems) : []),
    [activeCat, listItems],
  );
  // §5.4：分类筛选作用于整棵树（#567 单例：一项目一根，分类元素为根的子孙→保留匹配节点+子树）
  const filteredWorldRoots = useMemo(
    () => (activeCat === 'world' ? filterWorldTree(worldRoots, activeWorldCat) : []),
    [activeCat, worldRoots, activeWorldCat],
  );

  // F43 P1（D-13）：建议标签 = 当前项目角色 extra.groups 并集（数据驱动，供创建/编辑对话框）
  const tagSuggestions = useMemo(() => {
    if (activeCat !== 'characters') return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of listItems) {
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
  }, [activeCat, listItems]);

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

  // F43 P2：挂载/项目切换时拉取地图列表（世界观点亮徽标的数据源；失败置空 + err toast）
  // #973（#1089 批 A4 收编）：依赖 [currentProjectId, reloadKey, workbenchActive] 重拉，定位为
  // **推送缺位时的降级重拉**——主路径已是 SSE 推送（A3 已接 `map` 域，spec §15.6.2/§15.7.1），
  // 外部建图到达事件后 bump reloadKey 即触发本 effect 全量重拉；「进/退工作台重拉」降级为兜底
  // （断连 / 事件丢失时仍能靠进/退工作台收敛，§15.7.2 安全偏向）。删除条件见 spec §15.7.3。
  useEffect(() => {
    if (!currentProjectId) {
      setMaps([]);
      return;
    }
    let cancelled = false;
    void apiFetch<{ items?: WorldMapDTO[] }>(`/api/v1/projects/${currentProjectId}/maps`)
      .then((data) => {
        if (cancelled) return;
        const fetched = data.items ?? [];
        // #973 × #761：重拉以服务端为准，但保留本会话已经 onMapsChanged 回传的本地图
        // （如刚创建/改名后快照暂未含该图，退出/重进不得抹掉）；仅合并同项目防切项目残留
        setMaps((prev) => {
          const ownPrev = prev.filter(
            (m) => String(m.project_id) === String(currentProjectId),
          );
          const merged = [...fetched];
          for (const m of ownPrev) {
            if (!merged.some((x) => String(x.id) === String(m.id))) merged.push(m);
          }
          return merged;
        });
      })
      .catch((err) => {
        if (!cancelled) {
          setMaps([]);
          // #973：失败不再静默置空，推送 err toast（同 MapWorkbench.refreshPins 先例）
          useToastStore.getState().pushToast('err', errorMessage(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, reloadKey, workbenchActive]);

  // URL cat 变化（AppNav 直达）→ 同步激活 tab
  useEffect(() => {
    const p = searchParams.get('cat');
    if (isCatKey(p) && p !== activeCat) setActiveCat(p);
  }, [searchParams, activeCat]);

  // F48 §5.4：关系列表视图激活时拉取（分页响应 {items,...}；增删改后经 reloadKey 局部刷新）
  useEffect(() => {
    if (!currentProjectId || activeCat !== 'knowledge' || kgView !== 'list') {
      setRelations([]);
      return;
    }
    let cancelled = false;
    void listKnowledgeRelations(currentProjectId)
      .then((data) => {
        if (!cancelled) setRelations(data.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setRelations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, kgView, reloadKey]);

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
    characterDetailRef.current?.reset(); // 切换分类时卸载角色详情面板
  };
  const handleProjectChange = (id: string) => {
    selectProject(id);
    characterDetailRef.current?.reset(); // 切换项目时卸载角色详情面板
  };
  // F43 行操作（四处消费方统一形态：打开编辑对话框 / 打开删除确认）；#1302 新增时间线行内入口复用
  const openEdit = (item: LibraryItemDTO) => {
    setEditing(item);
    setCreateOpen(true);
  };
  const openDelete = (item: LibraryItemDTO) => setPendingDelete(item);
  // #196 + F43：保存回调——editing 非空 → PATCH 扁平端点；为空 → POST 创建端点（#196 现状保留）
  const handleSave = async (input: Record<string, unknown>) => {
    if (!currentProjectId) return;
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    // knowledge 不适用（无创建/编辑端点；图谱关系编辑走画布/列表内交互，此处防御性早退）
    if (current.key === 'knowledge') return;
    try {
      if (editing) {
        // F43 §5.2：编辑保存 → PATCH 扁平端点（spec §3.1 表）→ 关闭 + 刷新 + 顶部「已保存」指示
        setSaveState('saving');
        await apiFetch(PATCH_ENDPOINTS[current.key as Exclude<CatKey, 'knowledge'>](editing.id), {
          method: 'PATCH',
          body: input,
        });
      } else {
        // 关键：timeline 分类的创建端点是 /timeline/events（不是 /timeline 列表端点）
        const createEndpoint = current.key === 'timeline'
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
  // F43 §5.3：删除确认 → DELETE（世界观 ?cascade=true）→ 关闭 + 刷新 + ok toast；失败同样关闭确认框（E2），err toast
  const handleDelete = async () => {
    if (!pendingDelete || !currentProjectId) return;
    const target = pendingDelete;
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    if (current.key === 'knowledge') return;
    try {
      await apiFetch(DELETE_ENDPOINTS[current.key as Exclude<CatKey, 'knowledge'>](target.id), {
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
  // F48 §5.4：图谱关系保存（create → POST /projects/{pid}/knowledge-relations；edit → PATCH /knowledge-relations/{rid}）→ 关表单 + reloadKey 局部刷新
  const handleRelationSave = async (data: KnowledgeRelationFormData) => {
    if (!currentProjectId) return;
    try {
      if (editingRelation) await updateKnowledgeRelation(editingRelation.id, data);
      else await createKnowledgeRelation(currentProjectId, data);
      setRelationFormOpen(false);
      setEditingRelation(null);
      setReloadKey((k) => k + 1);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };
  // F48 §5.4：关系删除确认 → DELETE /knowledge-relations/{rid}（真删）→ 刷新 + ok toast
  const handleRelationDelete = async () => {
    if (!pendingRelationDelete) return;
    try {
      await deleteKnowledgeRelation(pendingRelationDelete.id);
      setPendingRelationDelete(null);
      setReloadKey((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setPendingRelationDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };
  // F48 §5.4：图谱边 → 关系行（仅 knowledge_relations 可编辑；cr: 行 F9 只读）
  const relationFromEdge = (edge: GraphEdge): KnowledgeRelation | null => {
    if (edge.source_table !== 'knowledge_relations') return null;
    const src = graphNodes.find((n) => n.id === edge.source);
    const tgt = graphNodes.find((n) => n.id === edge.target);
    if (!src || !tgt) return null;
    return {
      id: edge.id.replace(/^kr:/, ''),
      project_id: currentProjectId ?? '',
      source_type: src.type,
      source_id: src.entity_id,
      target_type: tgt.type,
      target_id: tgt.entity_id,
      relation_type: edge.label,
      description: edge.description ?? '',
      source: 'manual',
      created_at: '',
      updated_at: '',
    };
  };
  // F48 §5.4：图谱节点「去编辑」→ 对应实体分类 tab（map_pin 归属世界观地图工作台）
  const handleOpenKgEntity = (node: GraphNode) => handleTabChange(KG_ENTITY_CAT[node.type]);
  // F43 P1（§5.5/§3.3）：复制确认 → POST F37 copy 端点 → 结果 toast；成功关框；失败 err toast + 对话框保持打开可重试（E24）
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
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  // #675：outline 新增入口（＋整本/＋卷/＋章细纲）→ 打开创建对话框并预填层级上下文
  const handleOutlineAdd = (ctx: { level: OutlineLevel; parentId?: string | number | null }) => {
    setEditing(null);
    setAddCtx(ctx);
    setCreateOpen(true);
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
        <div data-testid="library-empty" className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center">
          <Library className="h-10 w-10 text-ink-3" aria-hidden="true" />
          <p className="mt-3 font-serif text-[17px] font-semibold text-ink">{t('lib.empty.noProject')}</p>
          <button type="button" data-testid="library-go-projects" className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60" onClick={() => navigate('/projects')}>
            {t('lib.empty.goProjects')}
          </button>
        </div>
      ) : (
        <>
          {/* 六分类 tab（角色/世界观/大纲/时间线/伏笔/知识图谱） */}
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
            {/* #545 + #568：列表非空保留常态"新建"入口（knowledge 无端点不渲染；空态 CTA 覆盖空列表；world 根态隐藏、选中分类显示） */}
            {currentProjectId !== null && (
              <div className="mb-3 flex items-center justify-end gap-2">
                {createCat !== null && !viewLoading && !viewFailed && listItems.length > 0 && !(activeCat === 'world' && workbenchActive) && (activeCat !== 'world' || activeWorldCat !== null) && activeCat !== 'outline' && (
                  <button type="button" data-testid="library-create-btn" className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60" onClick={() => setCreateOpen(true)}>
                    {t('lib.empty.create')}
                  </button>
                )}
                <AIExtractEntry />
              </div>
            )}
            {viewLoading ? (
              <div data-testid="library-list" className="space-y-2">
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
              </div>
            ) : viewFailed ? (
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
            ) : activeCat === 'knowledge' ? (
              /* F48 §5.4：知识图谱 tab 装配（视图 UI 在独立组件文件，library.tsx 只做状态与回调接线） */
              <KnowledgeGraphView
                nodes={graphNodes}
                edges={graphEdges}
                relations={relations}
                view={kgView}
                onViewChange={setKgView}
                onCreateRelation={() => {
                  setEditingRelation(null);
                  setRelationFormOpen(true);
                }}
                onEditRelation={(relation) => {
                  setEditingRelation(relation);
                  setRelationFormOpen(true);
                }}
                onDeleteRelation={setPendingRelationDelete}
                onOpenEntity={handleOpenKgEntity}
                onEditEdge={(edge) => {
                  const relation = relationFromEdge(edge);
                  if (relation) {
                    setEditingRelation(relation);
                    setRelationFormOpen(true);
                  }
                }}
                onDeleteEdge={(edge) => {
                  const relation = relationFromEdge(edge);
                  if (relation) setPendingRelationDelete(relation);
                }}
                onGoEntities={() => handleTabChange('characters')}
              />
            ) : activeCat === 'world' && workbenchActive && (listItems.length > 0 || maps.length > 0) ? (
              /* F43 P2（§5.8）：地图工作台——左树（#378 目录树 + P1/P2 兼容徽标）+ 右画布/pin 列表；#378：世界条目为空但已有地图时仍进入工作台 */
              <MapWorkbench
                projectId={currentProjectId}
                worldItems={listItems}
                maps={maps}
                activeMapId={activeMapId}
                reloadKey={reloadKey}
                onSelectMap={(mapId) => setActiveMapId(mapId)}
                onExitWorkbench={() => setWorkbenchActive(false)}
                onClearMap={() => setActiveMapId(null)}
                worldCategories={worldCategories}
                worldCatEntities={worldCatEntities}
                activeWorldCat={activeWorldCat}
                onWorldCatChange={setActiveWorldCat}
                onAddCategory={() => setWorldCatDialogOpen(true)}
                collapsedIds={collapsedIds}
                onToggle={toggleCollapsed}
                onEdit={openEdit}
                onDelete={openDelete}
                onCopy={(item) => setCopyState({ open: true, mode: 'subtree', rootId: item.id })}
                onCopyAll={() => setCopyState({ open: true, mode: 'all' })}
                copyTargetOptions={copyTargetOptions}
                onMapsChanged={(next) => setMaps(next)}
              />
            ) : activeCat === 'outline' ? (
              <OutlineTree
                outlines={outlineLib.treeItems}
                chapterTitles={outlineLib.chapterTitles}
                projectId={currentProjectId}
                sortDesc={outlineLib.sortDesc}
                onSortChange={outlineLib.setSortDesc}
                total={outlineLib.total}
                page={outlineLib.page}
                onPageChange={outlineLib.setPage}
                pageSize={OUTLINE_PAGE_SIZE}
                onOutlineGenerated={outlineLib.handleOutlineGenerated}
                onEdit={openEdit}
                onDelete={openDelete}
                onAdd={handleOutlineAdd}
              />
            ) : listItems.length === 0 ? (
              <div
                data-testid="library-tab-empty"
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.empty.tab', { name: t(cat.labelKey) })}</p>
                <button
                  type="button"
                  data-testid="library-tab-empty-cta"
                  className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => setCreateOpen(true)}
                >
                  {t('lib.empty.create')}
                </button>
                {/* #389：世界观空态也提供「新建分类」+「地图视图」入口（列表页工具栏同款）；空态无根条目 → showCreate 恒 true 无需传 */}
                {cat.key === 'world' && (
                  <div className="mt-4 flex items-center gap-2">
                    <WorldCatActionButtons
                      onAddCategory={() => setWorldCatDialogOpen(true)}
                      onOpenMapView={() => setWorkbenchActive(true)}
                    />
                  </div>
                )}
              </div>
            ) : activeCat === 'world' ? (
              <>
                {/* #699：世界观分类工具栏（chips kind 图标 + 地图入口门控 + 整体复制）拆至 WorldCategoryToolbar */}
                <WorldCategoryToolbar
                  categories={worldCatEntities}
                  activeWorldCat={activeWorldCat}
                  onSelect={setActiveWorldCat}
                  onDelete={(id) => void handleWorldCatDelete(id)}
                  onAddCategory={() => setWorldCatDialogOpen(true)}
                  onOpenMapView={() => setWorkbenchActive(true)}
                  onCreateWorld={activeWorldCat ? () => setCreateOpen(true) : undefined}
                  copyDisabled={copyTargetOptions.length === 0}
                  copyNeedTwoTitle={copyTargetOptions.length === 0 ? t('lib.copy.needTwo') : undefined}
                  onCopyAll={() => setCopyState({ open: true, mode: 'all' })}
                />
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
                        onEdit={openEdit}
                        onDelete={openDelete}
                        onCopy={(item) => setCopyState({ open: true, mode: 'subtree', rootId: item.id })}
                      />
                    ))
                  )}
                </div>
              </>
            ) : activeCat === 'timeline' ? (
              <TimelineView
                projectId={currentProjectId}
                eventTimeline={listItems}
                narrativeOrder={timelineNarrative}
                onEdit={openEdit}
                onDelete={openDelete}
              />
            ) : (
              <>
                <LibraryItemList
                  items={listItems}
                  withCharacterExtras={activeCat === 'characters'}
                  withForeshadowExtras={activeCat === 'foreshadow'}
                  projectId={currentProjectId}
                  rank={activeCat === 'characters' ? characterRank : undefined}
                  onRankChange={
                    activeCat === 'characters'
                      ? (next) => {
                          // #1320：切等级筛选 = 换数据集 → 页码归零（hook 的 extraQuery scope 也会收敛，
                          // 此处显式归零保证首帧即第 1 页，不与「翻页失败保留原页」语义混淆）
                          setCharacterRank(next);
                          pagedLib.setPage(0);
                        }
                      : undefined
                  }
                  onEdit={openEdit}
                  onDelete={openDelete}
                  onOpenDetail={activeCat === 'characters' ? (item) => characterDetailRef.current?.openDetail(item) : undefined}
                />
                {/* #1300：分页分类（characters/foreshadow）列表下方分页条；total<=pageSize 时组件仍渲染（prev/next 双禁用）
                    #1320：world 已移出分页分类（全量取数），故此处 isPagedCat 天然不含 world */}
                {isPagedCat && (
                  <Pagination
                    className="mt-4 justify-end"
                    page={pagedLib.page}
                    pageSize={LIBRARY_PAGE_SIZE}
                    total={pagedLib.total}
                    onPageChange={pagedLib.setPage}
                    testIdPrefix="library-page"
                  />
                )}
              </>
            )}
          </div>
        </>
      )}

      {/* #196 + F43 + #568：创建/编辑双模式对话框（挂在页面根部，open 受控；knowledge 分类不渲染；world 选中分类 initialCategory 预填） */}
      {createCat !== null && (
        <LibraryCreateDialog
          open={createOpen}
          cat={createCat}
          isRoot={createCat === 'world' ? (activeWorldCat === null && !editing) : undefined}
          editing={editing}
          tagSuggestions={tagSuggestions}
          initialCategory={activeCat === 'world' ? (activeWorldCat ?? undefined) : undefined}
          initialLevel={addCtx?.level}
          initialParentId={addCtx?.parentId ?? null}
          onSave={handleSave}
          onOpenChange={(open) => {
            setCreateOpen(open);
            if (!open) setEditing(null);
            if (!open) setAddCtx(null);
          }}
        />
      )}

      {/* #389：新建分类对话框（仅世界观 tab 工具栏入口打开；保存成功父级关框 + 刷新） */}
      <WorldCategoryDialog
        open={worldCatDialogOpen}
        onSave={(name, kind) => void handleWorldCatSave(name, kind)}
        onOpenChange={setWorldCatDialogOpen}
      />

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

      {/* F48 §5.4：新建/编辑关系表单（遮罩弹层；列表/画布视图保持挂载，保存后局部刷新） */}
      {relationFormOpen && (
        <RelationForm
          mode={editingRelation ? 'edit' : 'create'}
          initial={editingRelation}
          entities={graphNodes}
          onSubmit={(data) => void handleRelationSave(data)}
          onCancel={() => {
            setRelationFormOpen(false);
            setEditingRelation(null);
          }}
        />
      )}

      {/* F48 §5.4：关系删除二次确认（真删；testid 契约 library-kg-confirm-*） */}
      {pendingRelationDelete && (
        <ConfirmDialog
          open
          title={t('lib.delete.title', { name: pendingRelationDelete.relation_type })}
          message={t('lib.delete.confirm')}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="library-kg-confirm"
          onConfirm={() => void handleRelationDelete()}
          onOpenChange={(open) => {
            if (!open) setPendingRelationDelete(null);
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

      <LibraryCharacterDetail ref={characterDetailRef} currentProjectId={currentProjectId} items={listItems} reload={() => setReloadKey((k) => k + 1)} />
    </div>
  );
}
