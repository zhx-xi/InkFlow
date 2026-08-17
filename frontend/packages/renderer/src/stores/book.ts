/** 书级编排 store（F44 阶段1 GUI）：访谈会话 + WritingPlan + 运行状态（S1a #441 驱动） */
import { create } from 'zustand';
import { errorMessage } from '../api/client';
import {
  getBookRunStatus,
  getPlannerSession,
  respondPlanner,
  startBookRun,
  startPlanner,
  type PlannerQuestion,
  type PlannerRespondResponse,
  type RunStatusCounters,
  type WritingPlanDto,
} from '../api/books';

export type BookSessionStatus = 'idle' | 'drafting' | 'completed' | 'declined';

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
  loading: boolean;
  error: string | null;

  startPlanner: (projectId: string, oneLiner: string) => Promise<void>;
  respond: (answers: Record<string, string>) => Promise<void>;
  respondAuto: () => Promise<void>;
  loadSession: (sessionId: string) => Promise<void>;
  startRun: (planId: string) => Promise<void>;
  loadRunStatus: (runId: string) => Promise<void>;
  reset: () => void;
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

  startRun: async (planId) => {
    set({ loading: true, error: null });
    try {
      const res = await startBookRun({ writing_plan_id: planId });
      set({ runId: res.run_id, runStatus: res.status, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  loadRunStatus: async (runId) => {
    try {
      const res = await getBookRunStatus(runId);
      set({ runStatus: res.status, progress: res.progress, counters: res.counters });
    } catch (err) {
      // 失败仅记 error，不覆盖已有 runId/runStatus（轮询由面板按状态决定继续/停止）
      set({ error: errorMessage(err) });
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
      loading: false,
      error: null,
    });
  },
}));
