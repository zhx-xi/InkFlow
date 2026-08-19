/** 书级编排 store（F44 阶段1 GUI）：访谈会话 + WritingPlan + 运行状态（S1a #441 驱动） */
import { create } from 'zustand';
import { errorMessage } from '../api/client';
import {
  confirmBookRun,
  getBookRunSummary,
  getBookRunStatus,
  getPlannerSession,
  interveneBookRun,
  respondPlanner,
  startBookRun,
  startPlanner,
  type ConfirmedItem,
  type ConflictRecord,
  type HitlPayload,
  type InterveneAction,
  type InterveneDiff,
  type InterveneRequest,
  type PlannerQuestion,
  type PlannerRespondResponse,
  type RunStatusCounters,
  type RunSummaryResponse,
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

/** F44 v1.2 #475：对话式访谈消息（store 本地构建，无后端回传） */
export interface PlannerChatMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: 'one_liner' | 'question' | 'answer' | 'confirm_summary' | 'confirm' | 'auto';
  text: string;
  questionId?: string;
  template?: string;
  questionKind?: 'general' | 'targeted' | 'conflict';
  confirmedItems?: ConfirmedItem[];
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
  /** F44 阶段4 #338：观察流三层密度（纯前端本地 Zustand 状态，后端无 density 参数） */
  density: 'performance' | 'dashboard' | 'silent';
  /** 最近一次干预 diff（null = 无高亮） */
  interveneDiff: InterveneDiff | null;
  intervening: boolean;
  summary: RunSummaryResponse | null;
  summaryLoading: boolean;
  loading: boolean;
  error: string | null;
  /** F44 v1.2 #475：对话式消息流 + 末尾总体确认阶段状态（与 #337 HITL confirming 区分） */
  messages: PlannerChatMessage[];
  confirmedItems: ConfirmedItem[];
  conflicts: ConflictRecord[];
  sessionConfirming: boolean;

  startPlanner: (projectId: string, oneLiner: string) => Promise<void>;
  respond: (answers: Record<string, string>) => Promise<void>;
  respondAuto: () => Promise<void>;
  respondConfirm: () => Promise<void>;
  loadSession: (sessionId: string) => Promise<void>;
  startRun: (planId: string, limits?: Record<string, number>) => Promise<void>;
  loadRunStatus: (runId: string) => Promise<void>;
  confirmRun: (approved: boolean, decision?: string) => Promise<boolean>;
  setDensity: (density: 'performance' | 'dashboard' | 'silent') => void;
  interveneRun: (
    action: InterveneAction,
    target?: string,
    to?: string,
    payload?: { brief?: string },
  ) => Promise<boolean>;
  loadSummary: (runId: string) => Promise<void>;
  clearInterveneDiff: () => void;
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

/** 消息 id 自增序列（store 本地生成；测试不检查具体 id） */
let msgSeq = 0;
function nextMsgId(): string {
  msgSeq += 1;
  return `m-${msgSeq}`;
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
  density: 'dashboard',
  interveneDiff: null,
  intervening: false,
  summary: null,
  summaryLoading: false,
  loading: false,
  error: null,
  messages: [],
  confirmedItems: [],
  conflicts: [],
  sessionConfirming: false,

  startPlanner: async (projectId, oneLiner) => {
    set({ loading: true, error: null, oneLiner });
    try {
      const res = await startPlanner({ project_id: projectId, one_liner: oneLiner });
      const questionMsgs: PlannerChatMessage[] = res.questions.map(
        (q): PlannerChatMessage => ({
          id: nextMsgId(),
          role: 'assistant',
          kind: 'question',
          questionId: q.id,
          text: q.text,
          template: q.template,
          questionKind: q.kind,
        }),
      );
      set({
        sessionId: res.session_id,
        round: res.round,
        questions: res.questions,
        sessionStatus: 'drafting',
        confirmedItems: res.confirmed_items ?? [],
        conflicts: res.conflicts ?? [],
        sessionConfirming: res.confirming === true,
        messages: [
          { id: nextMsgId(), role: 'user', kind: 'one_liner', text: oneLiner },
          ...questionMsgs,
        ],
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
      const questionMsgs: PlannerChatMessage[] = res.questions.map(
        (q): PlannerChatMessage => ({
          id: nextMsgId(),
          role: 'assistant',
          kind: 'question',
          questionId: q.id,
          text: q.text,
          template: q.template,
          questionKind: q.kind,
        }),
      );
      const summaryMsg: PlannerChatMessage = {
        id: nextMsgId(),
        role: 'assistant',
        kind: 'confirm_summary',
        text: '确认以下设定？',
        confirmedItems: res.confirmed_items ?? [],
      };
      set((s) => ({
        round: res.round,
        questions: res.questions,
        answers: { ...s.answers, ...answers },
        confirmedItems: res.confirmed_items ?? [],
        conflicts: res.conflicts ?? [],
        sessionConfirming: res.confirming === true,
        messages: [
          ...s.messages,
          { id: nextMsgId(), role: 'user', kind: 'answer', text: Object.values(answers)[0] ?? '' },
          ...(res.confirming === true ? [summaryMsg] : questionMsgs),
        ],
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
      set((s) => ({
        round: res.round,
        questions: res.questions,
        messages: [
          ...s.messages,
          { id: nextMsgId(), role: 'user', kind: 'auto', text: '全部你决定' },
        ],
        ...(res.completed
          ? { sessionStatus: 'completed' as const, writingPlan: res.writing_plan ?? null }
          : {}),
        loading: false,
      }));
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  respondConfirm: async () => {
    const sessionId = get().sessionId;
    if (sessionId === null) return;
    set({ loading: true, error: null });
    try {
      const res: PlannerRespondResponse = await respondPlanner(sessionId, { confirm: true });
      set((s) => ({
        messages: [
          ...s.messages,
          { id: nextMsgId(), role: 'user', kind: 'confirm', text: '确认以下设定？' },
        ],
        sessionStatus: 'completed',
        writingPlan: res.writing_plan ?? null,
        sessionConfirming: false,
        loading: false,
      }));
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
        confirmedItems: dto.confirmed_items ?? [],
        conflicts: dto.conflicts ?? [],
        sessionConfirming: dto.confirming === true,
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

  setDensity: (density) => {
    set({ density });
  },

  interveneRun: async (action, target, to, payload) => {
    const runId = get().runId;
    if (runId === null) return false;
    set({ intervening: true, error: null });
    try {
      const body: InterveneRequest =
        action === 'redirect'
          ? { action, target, to }
          : action === 'edit'
            ? { action, target, payload: { brief: payload?.brief } }
            : { action };
      const res = await interveneBookRun(runId, body);
      set({
        runStatus: res.status,
        interveneDiff: res.diff ?? null,
        intervening: false,
      });
      return true;
    } catch (err) {
      set({ error: errorMessage(err), intervening: false });
      return false;
    }
  },

  loadSummary: async (runId) => {
    set({ summaryLoading: true, error: null });
    try {
      const res = await getBookRunSummary(runId);
      set({ summary: res, summaryLoading: false });
    } catch (err) {
      set({ error: errorMessage(err), summaryLoading: false });
    }
  },

  clearInterveneDiff: () => {
    set({ interveneDiff: null });
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
      density: 'dashboard',
      interveneDiff: null,
      intervening: false,
      summary: null,
      summaryLoading: false,
      loading: false,
      error: null,
      messages: [],
      confirmedItems: [],
      conflicts: [],
      sessionConfirming: false,
    });
  },
}));
