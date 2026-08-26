/**
 * 管线执行 + 轮询统一 hook（#472 R0 前置重构，spec §5.6）
 * 状态机: idle → running → success | failed | awaiting_human（HITL 中断，#343）
 * - start(body) → status='running' + executePipeline(body) + 自动轮询 getExecutionStatus（1s 间隔）
 * - completed → success + finalOutput/totalDurationMs；failed → failed + error；
 *   waiting_hitl → awaiting_human + hitlPending + 停止轮询（等待 confirm）
 * - confirm(approved) → confirmExecution(execution_id, approved) 后轮询续跑
 * - poll(executionId) 手动启动轮询（同时记录 executionId 供 confirm）
 * - 并发保护：执行中再次 start 无操作；终态（success/failed/awaiting_human）后允许再次 start
 * - execute/轮询网络失败 → failed + error
 * - 生命周期（timer/executionId）不入任何 store；卸载停止轮询
 */
import { useCallback, useEffect, useRef, useState, type MutableRefObject } from 'react';
import { errorMessage } from '../api/client';
import {
  confirmExecution,
  getExecutionStatus,
  streamPipeline,
  type PipelineExecuteRequest,
  type PipelineExecutionStatus,
  type PipelineStreamFrame,
} from '../api/pipeline';
import { startPolling } from '../lib/polling';

export type { PipelineStreamFrame } from '../api/pipeline';

export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';

/** #642-1：管线流式回调 sink（ChatPanel 注册既有流式 handler，streamPipeline 驱动复用） */
export interface PipelineStreamSink {
  onDelta?: (d: string) => void;
  onDone?: (f: PipelineStreamFrame) => void;
  onToolCall?: (c: { id: string; name: string; args: Record<string, unknown> }) => void;
  onToolResult?: (r: { id: string; name: string; result: string }) => void;
  /** #681：管线阶段切换帧（stage_id + stage_name）→ 前端 PipelineStatus 进度数据源 */
  onStage?: (s: { stage_id: string; stage_name: string }) => void;
}

export interface UseExecutionPollResult {
  status: PipelineRunStatus;
  error: string | null;
  finalOutput: string;
  totalDurationMs: number;
  hitlPending: { question: string; role: string } | null;
  executionId: string | null; // #543：执行详情页数据源（初始 null，start 成功后为 execution_id，终态保留）
  /** #681：当前管线阶段 id（stage 帧数据源） */
  currentStage: string | null;
  /** #681：当前管线阶段 display name */
  stageName: string | null;
  /** #681：阶段进度估算（已完成 stage 数 / 总数，百分比整数） */
  stageProgress: number;
  /** #681：生成整体耗时（ms，自 start 起累计） */
  stageElapsedMs: number;
  /** #642-1：管线流式回调 sink（透传 usePipeline/writing → ChatPanel 复用流式渲染） */
  streamSinkRef: MutableRefObject<PipelineStreamSink>;
  start: (body: PipelineExecuteRequest) => void; // 并发保护：执行中再次调用 = 无操作
  confirm: (approved: boolean) => void; // HITL 确认；无 executionId = 无操作
  poll: (executionId: string) => void; // 手动启动轮询（同时记录 executionId 供 confirm）
}

export function useExecutionPoll(): UseExecutionPollResult {
  const [status, setStatus] = useState<PipelineRunStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [finalOutput, setFinalOutput] = useState('');
  const [totalDurationMs, setTotalDurationMs] = useState(0);
  const [hitlPending, setHitlPending] = useState<{ question: string; role: string } | null>(null);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState<string | null>(null);
  const [stageName, setStageName] = useState<string | null>(null);
  const [stageProgress, setStageProgress] = useState(0);
  const [stageElapsedMs, setStageElapsedMs] = useState(0);
  const inFlightRef = useRef(false);
  const executionIdRef = useRef<string | null>(null);
  const pollHandleRef = useRef<{ cancel: () => void } | null>(null);
  const streamSinkRef = useRef<PipelineStreamSink>({});
  // #681：已到达 stage 列表（去重；stageProgress 按已完 stage 数估算）+ start 时刻
  const stageListRef = useRef<string[]>([]);
  const startedAtRef = useRef(0);

  const poll = useCallback((executionId: string) => {
    executionIdRef.current = executionId;
    setExecutionId(executionId);
    pollHandleRef.current?.cancel();
    pollHandleRef.current = startPolling<PipelineExecutionStatus>(
      async () => {
        try {
          return await getExecutionStatus(executionId);
        } catch (err) {
          // 轮询网络失败 → failed + error（throw 让 startPolling 停止轮询）
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
          throw err;
        }
      },
      (s) => s.status !== 'pending' && s.status !== 'running',
      {
        onValue: (s) => {
          if (s.status === 'completed') {
            setFinalOutput(s.final_output);
            setTotalDurationMs(s.total_duration_ms);
            setError(null);
            setStatus('success');
            inFlightRef.current = false;
          } else if (s.status === 'failed') {
            setError(s.error || '执行失败');
            setStatus('failed');
            inFlightRef.current = false;
          } else if (s.status === 'waiting_hitl') {
            setHitlPending(
              s.hitl_pending ? { question: s.hitl_pending.question, role: s.hitl_pending.role } : null,
            );
            setStatus('awaiting_human');
            inFlightRef.current = false; // 停止轮询，等待人工确认
          }
          // 其它（pending/running）→ 保持 running，startPolling 继续轮询
        },
      },
    );
  }, []);

  const start = useCallback((body: PipelineExecuteRequest) => {
    if (inFlightRef.current) return; // 防并发
    inFlightRef.current = true;
    setError(null);
    setFinalOutput('');
    setTotalDurationMs(0);
    setHitlPending(null);
    setCurrentStage(null);
    setStageName(null);
    setStageProgress(0);
    setStageElapsedMs(0);
    stageListRef.current = [];
    startedAtRef.current = Date.now();
    setStatus('running');

    streamPipeline(body, {
      onDelta: (d) => streamSinkRef.current.onDelta?.(d),
      onDone: (f) => {
        streamSinkRef.current.onDone?.(f);
        // #681：done 帧携带 execution_id → 捕获供执行详情页
        if (f.execution_id) setExecutionId(f.execution_id);
        setFinalOutput(f.final_output ?? '');
        setError(null);
        setStatus('success');
        inFlightRef.current = false;
      },
      onToolCall: (c) => streamSinkRef.current.onToolCall?.(c),
      onToolResult: (r) => streamSinkRef.current.onToolResult?.(r),
      onStage: (s) => {
        streamSinkRef.current.onStage?.(s);
        // 去重收集已到达 stage（同一阶段多次事件只记一次）
        const list = stageListRef.current;
        if (!list.includes(s.stage_id)) list.push(s.stage_id);
        setCurrentStage(s.stage_id);
        setStageName(s.stage_name);
        setStageElapsedMs(Date.now() - startedAtRef.current);
        // 无总阶段数：按「已到 stage / (已到 + 1 个待办)」估算进度
        setStageProgress(Math.min(99, Math.round((list.length / Math.max(1, list.length + 1)) * 100)));
      },
      onError: (m) => {
        setError(m);
        setStatus('failed');
        inFlightRef.current = false;
      },
    }).catch(() => {});
  }, []);

  const confirm = useCallback(
    (approved: boolean) => {
      const executionId = executionIdRef.current;
      if (!executionId) return; // 无 executionId = 无操作
      setStatus('running');
      confirmExecution(executionId, approved)
        .then(() => {
          poll(executionId);
        })
        .catch((err) => {
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
        });
    },
    [poll],
  );

  useEffect(() => {
    return () => {
      pollHandleRef.current?.cancel();
    };
  }, []);

  return {
    status,
    error,
    finalOutput,
    totalDurationMs,
    hitlPending,
    executionId,
    currentStage,
    stageName,
    stageProgress,
    stageElapsedMs,
    streamSinkRef,
    start,
    confirm,
    poll,
  };
}
