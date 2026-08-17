/** 书级编排 store（F44 阶段1 GUI）：访谈会话 + WritingPlan + 运行状态（S1a #441 驱动） */
import { create } from 'zustand';
import { errorMessage } from '../api/client';
import {
  confirmBookRun,
  getBookRunStatus,
  getPlannerSession,
  respondPlanner,
  startBookRun,
  startPlanner,
  type HitlPayload,
  type PlannerQuestion,
  type PlannerRespondResponse,
  type RunStatusCounters,
  type WritingPlanDto,
} from '../api/books';

export type BookSessionStatus = 'idle' | 'drafting' | 'completed' | 'declined';

/** 章级进度状态机派生统计（S2a #445，progress 值计数） */
export interface ProgressStats {
  total: number;
  done: number;
  inProgress: number;
  failed: number;
  skipped: number;
  pending: number;
}

interface BookState {
  sessionId: string | null;
  round: number;
  questions: PlannerQuestion[];
  answers: Record<string, string>;
  authorized: string[];
  sessionStatus: BookSessionStatus;
  oneLiner: string;
  writingPlan: WritingPlanDto | null;
  runId: string | null;
  runStatus: string | null;
  progress: Record<string, string>;
  counters: RunStatusCounters | null;
  progressStats: ProgressStats;
  /** F44 阶段3 #337：卷级 HITL 确认对话框状态（waiting_hitl 时弹出） */
  waitingHitl: boolean;
  hitlPayload: HitlPayload | null;
  confirming: boolean;
  loading: boolean;
  error: string | null;

  startPlanner: (projectId: string, oneLiner: string) => Promise<void>;
  respond: (answers: Record<string, string>) => Promise<void>;
  respondAuto: () => Promise<void>;
  loadSession: (sessionId: string) => Promise<void>;
  startRun: (planId: string, limits?: Record<string, number>) => Promise<void>;
  loadRunStatus: (runId: string) => Promise<void>;
  confirmRun: (approved: boolean, decision?: string) => Promise<boolean>;
  reset: () => void;
}

/** 从 progress 值计数派生章级进度统计（未知值不计入任何分类但计入 total） */
export function deriveProgressStats(progress: Record<string, string>): ProgressStats {
  const stats: ProgressStats = {
    total: Object.keys(progress).length,
    done: 0,
    inProgress: 0,
    failed: 0,
    skipped: 0,
    pending: 0,
  };
  for (const status of Object.values(progress)) {
    if (status === 'done') stats.done += 1;
    else if (status === 'in_progress') stats.inProgress += 1;
    else if (status === 'failed') stats.failed += 1;
    else if (status === 'skipped') stats.skipped += 1;
    else if (status === 'pending') stats.pending += 1;
  }
  return stats;
}

export const useBookStore = create<BookState>((set, get) => ({
  sessionId: null,
  round: 0,
  questions: [],
  answers: {},
  authorized: [],
  sessionStatus: 'idle',
  oneLiner: '',
  writingPlan: null,
  runId: null,
  runStatus: null,
  progress: {},
  counters: null,
  progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
  waitingHitl: false,
  hitlPayload: null,
  confirming: false,
  loading: false,
  error: null,

  startPlanner: async (projectId, oneLiner) => {
    set({ loading: true, error: null, oneLiner });
    try {
      const res = await startPlanner({ project_id: projectId, one_liner: oneLiner });
      set({
        sessionId: res.session_id,
        round: res.round,
        questions: res.questions,
        sessionStatus: 'drafting',
        loading: false,
      });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  respond: async (answers) => {
    const sessionId = get().sessionId;
    if (sessionId === null) return;
    set({ loading: true, error: null });
    try {
      const res: PlannerRespondResponse = await respondPlanner(sessionId, { answers, auto: false });
      set((s) => ({
        round: res.round,
        questions: res.questions,
        answers: { ...s.answers, ...answers },
        ...(res.completed
          ? { sessionStatus: 'completed' as const, writingPlan: res.writing_plan ?? null }
          : {}),
        loading: false,
      }));
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  respondAuto: async () => {
    const sessionId = get().sessionId;
    if (sessionId === null) return;
    set({ loading: true, error: null });
    try {
      const res: PlannerRespondResponse = await respondPlanner(sessionId, { answers: {}, auto: true });
      set({
        round: res.round,
        questions: res.questions,
        ...(res.completed
          ? { sessionStatus: 'completed' as const, writingPlan: res.writing_plan ?? null }
          : {}),
        loading: false,
      });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  loadSession: async (sessionId) => {
    set({ loading: true, error: null });
    try {
      const dto = await getPlannerSession(sessionId);
      set({
        sessionId: dto.id,
        round: dto.round,
        questions: dto.asked_questions,
        answers: dto.answers,
        authorized: dto.authorized,
        sessionStatus: dto.status as BookSessionStatus,
        loading: false,
      });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  startRun: async (planId, limits) => {
    set({ loading: true, error: null });
    try {
      const res = await startBookRun(
        limits ? { writing_plan_id: planId, limits } : { writing_plan_id: planId },
      );
      set({ runId: res.run_id, runStatus: res.status, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  loadRunStatus: async (runId) => {
    try {
      const res = await getBookRunStatus(runId);
      set({
        runStatus: res.status,
        progress: res.progress,
        counters: res.counters,
        progressStats: deriveProgressStats(res.progress),
        waitingHitl: res.waiting_hitl === true,
        hitlPayload: res.hitl_payload ?? null,
      });
    } catch (err) {
      // 失败仅记 error，不覆盖已有 runId/runStatus（轮询由面板按状态决定继续/停止）
      set({ error: errorMessage(err) });
    }
  },

  confirmRun: async (approved, decision) => {
    const runId = get().runId;
    if (runId === null) return false;
    set({ confirming: true, error: null });
    try {
      const res = await confirmBookRun(runId, decision ? { approved, decision } : { approved });
      if (res.status === 'waiting_hitl' && res.hitl_payload) {
        set({ runStatus: res.status, waitingHitl: true, hitlPayload: res.hitl_payload, confirming: false });
      } else {
        set({ runStatus: res.status, waitingHitl: false, hitlPayload: null, confirming: false });
      }
      return true;
    } catch (err) {
      set({ error: errorMessage(err), confirming: false });
      return false;
    }
  },

  reset: () => {
    set({
      sessionId: null,
      round: 0,
      questions: [],
      answers: {},
      authorized: [],
      sessionStatus: 'idle',
      oneLiner: '',
      writingPlan: null,
      runId: null,
      runStatus: null,
      progress: {},
      counters: null,
      progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
      waitingHitl: false,
      hitlPayload: null,
      confirming: false,
      loading: false,
      error: null,
    });
  },
}));
