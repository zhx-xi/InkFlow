/**
 * #1466 成书页水合接线契约：BookPlannerPanel 的 hydrate 触发时机。
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须在 src/components/BookPlannerPanel.tsx 追加：
 *
 *   const hydrate = useBookStore((s) => s.hydrate);
 *   useEffect(() => {
 *     void hydrate(projectId);
 *   }, [projectId, hydrate]);
 *
 * 行为契约：
 * - 首屏挂载 → 用传入 projectId 调一次 hydrate（既有 plan/run 从后端读回来）
 * - projectId prop 变更 → 用**新** id 再调 hydrate
 *
 * 判据来源：issue #1466 修复方向 2「首屏 + projectId 变更时调用」。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { BookPlannerPanel } from './BookPlannerPanel';
import { useBookStore } from '../stores/book';
import { useModelsStore } from '../stores/models';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.startsWith('/api/v1/agent/books/plans')) {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    return { run_id: 'wp-1', status: 'completed' };
  });
  useModelsStore.setState({ providers: [], loading: false, error: null });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useBookStore.getState().reset();
});

describe('#1466 BookPlannerPanel — 水合接线', () => {
  it('首屏挂载 → hydrate(projectId) 恰好一次', async () => {
    const hydrateSpy = vi.spyOn(useBookStore.getState(), 'hydrate').mockResolvedValue();

    render(<BookPlannerPanel projectId="p1" />);

    await waitFor(() => {
      expect(hydrateSpy).toHaveBeenCalledWith('p1');
    });
  });

  it('projectId 变更 → 用新 id 再水合', async () => {
    const hydrateSpy = vi.spyOn(useBookStore.getState(), 'hydrate').mockResolvedValue();

    const { rerender } = render(<BookPlannerPanel projectId="p1" />);
    await waitFor(() => {
      expect(hydrateSpy).toHaveBeenCalledWith('p1');
    });

    hydrateSpy.mockClear();
    rerender(<BookPlannerPanel projectId="p2" />);

    await waitFor(() => {
      expect(hydrateSpy).toHaveBeenCalledWith('p2');
    });
    expect(hydrateSpy).not.toHaveBeenCalledWith('p1');
  });
});
