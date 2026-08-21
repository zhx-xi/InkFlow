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
import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import {
  confirmExecution,
  executePipeline,
  getExecutionStatus,
  type PipelineExecuteRequest,
  type PipelineExecutionStatus,
} from '../api/pipeline';
import { startPolling } from '../lib/polling';

export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';

export interface UseExecutionPollResult {
  status: PipelineRunStatus;
  error: string | null;
  finalOutput: string;
  totalDurationMs: number;
  hitlPending: { question: string; role: string } | null;
  executionId: string | null; // #543：执行详情页数据源（初始 null，start 成功后为 execution_id，终态保留）
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
  const inFlightRef = useRef(false);
  const executionIdRef = useRef<string | null>(null);
  const pollHandleRef = useRef<{ cancel: () => void } | null>(null);

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

  const start = useCallback(
    (body: PipelineExecuteRequest) => {
      if (inFlightRef.current) return; // 防并发
      inFlightRef.current = true;
      setError(null);
      setFinalOutput('');
      setTotalDurationMs(0);
      setHitlPending(null);
      setStatus('running');

      executePipeline(body)
        .then((res) => {
          executionIdRef.current = res.execution_id;
          setExecutionId(res.execution_id);
          poll(res.execution_id);
        })
        .catch((err) => {
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
        });
    },
    [poll],
  );

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

  return { status, error, finalOutput, totalDurationMs, hitlPending, executionId, start, confirm, poll };
}
