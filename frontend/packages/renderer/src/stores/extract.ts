/**
 * #1582 提取会话 store（zustand；同目录惯例 = 同名 `.test.ts`）。
 *
 * 【为什么存在】「AI 提取」是两段式（#1545/#1546）：提交只把产物落在暂存区，等用户确认才物化。
 * 但会话状态（浮窗是否最小化 / 当前待确认结果）原本绑在**宿主页局部 state**
 * （`AIExtractEntry.tsx` 与 `pages/writing.tsx` 各一个 `useState`）→ 宿主重挂载或路由切换即复位，
 * 对话框内 `if (!open) return null` 连带把浮窗卸载 ⇒ 结果视图永久不可达（rc3 缺陷 G2）。
 * 本 store 承载**必须跨路由 / 重挂载存活的最小集**，由 App 层常驻组件消费。
 *
 * 【上提最小集】`open` / `minimized` / `staged` / `initialKind` / `projectId`
 * + 待确认批次列表 `pending`。
 * 【不上提】`chapters` / `volumes` / `runs` / 范围面等一次性输入（留在组件内，
 * 避免上一次提取的输入泄漏到下一次）。
 *
 * 【语义】关框只清结果视图（`staged`）——暂存批次仍在服务端，由「待确认提取（N）」入口列出
 * （关框 ≠ 丢弃结果）。
 */
import { create } from 'zustand';
import { apiFetch } from '../api/client';
// 仅类型引用（`import type` 不产生运行时依赖 → 与组件之间无循环）
import type { ExtractKind } from '../components/extract/AIExtractDialog';

/** 待确认批次（`GET /api/v1/projects/{pid}/extractions/staging` 响应项；W11a 轨 1 / #1581 交付） */
export interface PendingBatch {
  batch_id: string;
  type: string;
  created_at: string;
  item_count: number;
}

/** 暂存条目（结果视图展示用；与 POST /api/v1/extract 信封 detail 同形） */
export interface StagedEntry {
  id?: string;
  name?: string;
}

/** 当前待确认结果面（结果视图数据源） */
export interface StagedResult {
  batchIds: string[];
  created: StagedEntry[];
  updated: StagedEntry[];
}

export interface ExtractState {
  /** 对话框开（open 且 minimized 时渲染右下角浮窗） */
  open: boolean;
  /** 最小化到右下角浮窗 */
  minimized: boolean;
  projectId: string | null;
  /** 来源页默认类型（#1566） */
  initialKind: ExtractKind | undefined;
  /** 当前待确认结果面（非 null = 结果视图） */
  staged: StagedResult | null;
  pending: PendingBatch[];
  pendingLoaded: boolean;
  /** `pending` 归属哪个项目（切项目瞬间不显示别的项目的列表） */
  pendingFor: string | null;
  openDialog: (projectId: string, initialKind?: ExtractKind) => void;
  minimize: () => void;
  restore: () => void;
  /** 从「待确认提取」入口查看某一批 → 直接进结果视图 */
  viewBatch: (projectId: string, staged: StagedResult) => void;
  closeDialog: () => void;
  setStaged: (staged: StagedResult | null) => void;
  refreshPending: (projectId: string) => Promise<void>;
}

/** 只认最后一次 refreshPending（切项目时旧项目的迟到响应作废 → 不串项目） */
let listSeq = 0;

export const useExtractStore = create<ExtractState>((set) => ({
  open: false,
  minimized: false,
  projectId: null,
  initialKind: undefined,
  staged: null,
  pending: [],
  pendingLoaded: false,
  pendingFor: null,

  openDialog: (projectId, initialKind) =>
    set({ open: true, minimized: false, projectId, initialKind, staged: null }),

  minimize: () => set({ minimized: true }),

  restore: () => set({ minimized: false }),

  viewBatch: (projectId, staged) =>
    set({ open: true, minimized: false, projectId, initialKind: undefined, staged }),

  closeDialog: () => set({ open: false, minimized: false, staged: null }),

  setStaged: (staged) => set({ staged }),

  refreshPending: async (projectId) => {
    listSeq += 1;
    const seq = listSeq;
    let batches: PendingBatch[] = [];
    try {
      const data = await apiFetch<{ batches?: PendingBatch[] }>(
        `/api/v1/projects/${projectId}/extractions/staging`,
      );
      batches = data.batches ?? [];
    } catch {
      // 拉取失败 → 入口静默不渲染（不炸页面、不做假计数；batches 保持初值空列表）
    }
    if (seq !== listSeq) return; // 迟到的旧项目响应作废
    set({ pending: batches, pendingFor: projectId, pendingLoaded: true });
  },
}));
