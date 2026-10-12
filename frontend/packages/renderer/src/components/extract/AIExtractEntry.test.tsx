/**
 * 「待确认提取（N）」入口 RED 契约（#1582；`components/extract/AIExtractEntry.tsx` 内）。
 *
 * 【为什么要有它】两段式暂存（#1545/#1546）把产物留在 `extract_staging` 等确认，但**全仓无任何
 * UI 入口可看**——浮窗一消失（见 AIExtractResultView.test.tsx 的生命周期契约）结果就永久不可达，
 * 未确认批次只能靠 #1551 的 30 天过期清理兜底。拍板 B2-a：资料库工具栏加「待确认提取（N）」入口。
 *
 * 【契约】
 * - 位置：资料库工具栏（`AIExtractEntry` 内，位于「AI 提取」左侧）；仅 currentProjectId 非 null 渲染
 * - `extract-pending-entry`：入口按钮；文案含 i18n `extract.pending` + 角标 N
 * - **N = 待确认批次数**（`pending.length`，非条目数）；`N === 0` → 入口不渲染（拍板 D1，不占位）
 * - 点击 → `extract-pending-panel` 面板：每批一行 `extract-pending-item`（类型 / 条目数 / 时间）
 *   + 行内 `extract-pending-view` / `extract-pending-cancel` / `extract-pending-confirm`（拍板 D2）
 * - 「确认落库」→ `POST .../staging/{batch_id}/confirm`；「取消」→ `POST .../staging/{batch_id}/cancel`；
 *   两者完成后**重拉列表** → 角标 N 同步下降
 * - 「查看」→ `GET .../staging/{batch_id}`（既有端点，不新增）→ 按 action 拆新增/更新 → 开结果视图
 * - 数据源 `GET /api/v1/projects/{pid}/extractions/staging`（#1581 交付的冻结形状，本轨只消费）
 * - **跨进程存活**：进程内的 store 一旦清空（= 关掉 App 重开），入口重新挂载仍能从服务端列出批次
 *
 * 【RED 预期失败形态】`extract-pending-entry` 不存在（无入口）→ element-missing。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIExtractEntry } from './AIExtractEntry';
import { AIExtractDialog } from './AIExtractDialog';
import { apiFetch } from '../../api/client';
import { useExtractStore, type PendingBatch } from '../../stores/extract';
import { useProjectStore } from '../../stores/project';
import { useThemeStore } from '../../stores/theme';
import { useToastStore } from '../../stores/toast';
import { extractEn, extractZh } from '../../i18n/extract-keys';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1',
  name: '项目甲',
  tags: ['玄幻'],
  language: 'zh-CN',
  target_words: 800000,
  config: {},
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

function batch(id: string, type = 'timeline', itemCount = 18): PendingBatch {
  return { batch_id: id, type, created_at: '2026-10-11T06:02:00Z', item_count: itemCount };
}

/** 服务端「当前待确认批次」可变状态（confirm / cancel 后由 mock 递减，模拟真实列表端点） */
let batches: PendingBatch[] = [];

/** 单批暂存条目（#1590：payload 富字段，供详情抽屉逐项断言） */
function stagedItems(): Array<{
  id: number;
  entity_type: string;
  action: string;
  name: string;
  payload: Record<string, unknown>;
}> {
  return [
    {
      id: 7,
      entity_type: 'timeline_event',
      action: 'create',
      name: '事件甲',
      payload: {
        title: '事件甲',
        description: '角色甲与角色乙在山门前交手。',
        time_display: '示例历 317 年秋',
        parse_reason: '原文缺历法名',
        time_value: null,
        time_unit: '',
        era: '默认轴',
        era_value: null,
        era_scale: 1.0,
        narrative_position: null,
        timeline_flag: '',
      },
    },
    { id: 8, entity_type: 'timeline_event', action: 'update', name: '事件乙', payload: { title: '事件乙' } },
  ];
}

function installMock() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/extractions/staging') return { batches };
    // #1590 条目级端点（须先于批次 confirm / cancel 分支匹配）
    const item = /\/extractions\/staging\/([^/]+)\/items\/(\d+)(\/confirm)?$/.exec(path);
    if (item) {
      if (item[3]) return { item_id: Number(item[2]), event_id: 'ev-1' };
      if (init?.method === 'DELETE') return { deleted: 1 };
    }
    const single = /\/extractions\/staging\/([^/]+)$/.exec(path);
    if (single && (init?.method ?? 'GET') === 'GET') {
      const id = single[1];
      return { batch_id: id, items: stagedItems() };
    }
    if (path.endsWith('/confirm') || path.endsWith('/cancel')) {
      const id = path.split('/').slice(-2)[0];
      batches = batches.filter((x) => x.batch_id !== id);
      return { batch_id: id, created: 1, updated: 0, deleted: 1 };
    }
    if (path.startsWith('/api/v1/projects/p1/chapters')) return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: [] };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { items: [] };
    return { ok: true };
  });
}

/** 挂载入口（+ App 层的对话框，供「查看」断言结果视图） */
function renderEntry(withDialog = false) {
  return render(
    <>
      <AIExtractEntry cat="characters" />
      {withDialog ? <AIExtractDialog /> : null}
    </>,
  );
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockReset();
  installMock();
  batches = [];
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
  useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1', loading: false, error: null });
  useExtractStore.setState({
    open: false,
    minimized: false,
    projectId: null,
    initialKind: undefined,
    staged: null,
    pending: [],
    pendingLoaded: false,
    pendingFor: null,
  });
});

describe('「待确认提取（N）」入口（#1582）', () => {
  it('契约1：未选项目 → 入口与「AI 提取」都不渲染', async () => {
    useProjectStore.setState({ currentProjectId: null });
    renderEntry();
    await waitFor(() => expect(screen.queryByTestId('extract-entry-lib')).not.toBeInTheDocument());
    expect(screen.queryByTestId('extract-pending-entry')).not.toBeInTheDocument();
  });

  it('契约2：无待确认批次（N=0）→ 入口不渲染，但「AI 提取」照常', async () => {
    renderEntry();
    await waitFor(() => expect(screen.getByTestId('extract-entry-lib')).toBeInTheDocument());
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/staging')).toBe(
        true,
      ),
    );
    expect(screen.queryByTestId('extract-pending-entry')).not.toBeInTheDocument();
  });

  it('契约3（N 口径）：2 个批次 → 入口渲染且角标 = 2（批次数，非 18+3=21 条目数）', async () => {
    batches = [batch('ext-2', 'timeline', 18), batch('ext-1', 'character', 3)];
    renderEntry();

    const entry = await screen.findByTestId('extract-pending-entry');
    expect(entry).toHaveTextContent('待确认提取');
    expect(entry).toHaveTextContent('2');
    expect(entry).not.toHaveTextContent('21');
  });

  it('契约4（跨进程存活）：store 清空（= 重开 App）+ 重新挂载 → 仍能列出该批次', async () => {
    batches = [batch('ext-2', 'timeline', 18)];
    const first = renderEntry();
    await screen.findByTestId('extract-pending-entry');
    first.unmount();

    // 进程内状态全丢（等价「关掉 App 后回来」）——批次只在服务端
    useExtractStore.setState({
      open: false,
      minimized: false,
      projectId: null,
      initialKind: undefined,
      staged: null,
      pending: [],
      pendingLoaded: false,
      pendingFor: null,
    });
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    const rows = within(panel).getAllByTestId('extract-pending-item');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('时间线');
    expect(rows[0]).toHaveTextContent('18');
  });

  it('契约5（N 同步下降）：面板「确认落库」→ POST confirm → 重拉 → 角标 2 → 1', async () => {
    batches = [batch('ext-2', 'timeline', 18), batch('ext-1', 'character', 3)];
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-confirm')[0]);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/confirm',
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(useExtractStore.getState().pending).toHaveLength(1));
    expect(screen.getByTestId('extract-pending-entry')).toHaveTextContent('1');
  });

  it('契约6（N 同步下降 / #1590 修订）：面板「取消」→ 先弹确认 → × 确认 → POST cancel → 重拉 → 角标下降', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-cancel')[0]);

    // #1590：点了不再即删——先二次确认
    const prompt = await screen.findByTestId('extract-pending-cancel-prompt-dialog');
    expect(cancelCalls()).toHaveLength(0);
    await user.click(within(prompt).getByTestId('extract-pending-cancel-prompt-dismiss'));

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/cancel',
        ),
      ).toBe(true),
    );
    // 取消 = 零物化：不得调 confirm
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm'))).toBe(false);
    await waitFor(() => expect(useExtractStore.getState().pending).toHaveLength(1));
  });

  it('契约7（查看）：读单批（既有端点）→ 按 action 拆新增/更新 → 打开结果视图', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry(true);
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-view')[0]);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2'),
      ).toBe(true),
    );
    const result = await screen.findByTestId('ai-extract-result');
    expect(within(within(result).getByTestId('ai-extract-created')).getAllByTestId('ai-extract-created-item')).toHaveLength(1);
    expect(within(within(result).getByTestId('ai-extract-updated')).getAllByTestId('ai-extract-updated-item')).toHaveLength(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// #1590：取消批次二次确认（三出路：× 确认取消 / — 最小化保留 / 返回）
// ═══════════════════════════════════════════════════════════════════════════
const cancelCalls = () =>
  apiFetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/cancel'));

/** 开面板 → 点行内「取消」→ 返回确认弹窗 */
async function openCancelPrompt(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('extract-pending-entry'));
  const panel = await screen.findByTestId('extract-pending-panel');
  await user.click(within(panel).getAllByTestId('extract-pending-cancel')[0]);
  return screen.findByTestId('extract-pending-cancel-prompt-dialog');
}

describe('取消批次二次确认（#1590）', () => {
  it('契约8（先弹确认）：点「取消」只弹确认框，未发 cancel 请求', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();

    const dialog = await openCancelPrompt(user);
    expect(dialog).toBeInTheDocument();
    // 弹窗未确认 → 零删除请求，批次仍在
    expect(cancelCalls()).toHaveLength(0);
    expect(useExtractStore.getState().pending).toHaveLength(2);
  });

  it('契约9（× 确认取消）：POST cancel → 该批消失 + 角标 N 减 1', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();

    const dialog = await openCancelPrompt(user);
    await user.click(within(dialog).getByTestId('extract-pending-cancel-prompt-dismiss'));

    await waitFor(() =>
      expect(
        cancelCalls().some((c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/cancel'),
      ).toBe(true),
    );
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm'))).toBe(false);
    await waitFor(() => expect(useExtractStore.getState().pending).toHaveLength(1));
    expect(screen.getByTestId('extract-pending-entry')).toHaveTextContent('1');
    expect(screen.queryByTestId('extract-pending-cancel-prompt-dialog')).not.toBeInTheDocument();
  });

  it('契约10（— 最小化保留）：弹窗与面板关闭，批次仍在，且零请求', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();

    const dialog = await openCancelPrompt(user);
    const callsBefore = apiFetchMock.mock.calls.length;
    await user.click(within(dialog).getByTestId('extract-pending-cancel-prompt-minimize'));

    await waitFor(() =>
      expect(screen.queryByTestId('extract-pending-cancel-prompt-dialog')).not.toBeInTheDocument(),
    );
    expect(apiFetchMock.mock.calls.length).toBe(callsBefore); // 零副作用
    expect(screen.queryByTestId('extract-pending-panel')).not.toBeInTheDocument();
    expect(useExtractStore.getState().pending).toHaveLength(2);
  });

  it('契约11（返回）：弹窗关闭、面板保持打开、批次仍在、零请求', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();

    const dialog = await openCancelPrompt(user);
    const callsBefore = apiFetchMock.mock.calls.length;
    await user.click(within(dialog).getByTestId('extract-pending-cancel-prompt-ok'));

    await waitFor(() =>
      expect(screen.queryByTestId('extract-pending-cancel-prompt-dialog')).not.toBeInTheDocument(),
    );
    expect(apiFetchMock.mock.calls.length).toBe(callsBefore);
    expect(screen.getByTestId('extract-pending-panel')).toBeInTheDocument();
    expect(within(screen.getByTestId('extract-pending-panel')).getAllByTestId('extract-pending-item')).toHaveLength(2);
  });

  it('契约12（文案两条出路）：弹窗写明「清除本批暂存」与「可最小化保留」', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const dialog = await openCancelPrompt(user);
    const body = extractZh['extract.pendingCancelBody'];
    expect(body).toContain('清除');
    expect(body).toContain('最小化');
    expect(dialog).toHaveTextContent(extractZh['extract.pendingCancelTitle']);
    expect(within(dialog).getByTestId('extract-pending-cancel-prompt-ok')).toHaveTextContent(
      extractZh['extract.pendingCancelBack'],
    );
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// #1590：条目详情右侧面板（字段逐项取自暂存 payload；底部单一动作区）
// ═══════════════════════════════════════════════════════════════════════════
async function openDrawer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('extract-pending-entry'));
  const panel = await screen.findByTestId('extract-pending-panel');
  await user.click(within(panel).getAllByTestId('extract-pending-detail')[0]);
  return screen.findByTestId('extract-pending-drawer');
}

describe('条目详情右侧面板（#1590）', () => {
  it('契约13（入口）：行内「详情」→ 抽屉打开 + 读单批明细端点', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const drawer = await openDrawer(user);
    expect(drawer).toBeInTheDocument();
    expect(
      apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2'),
    ).toBe(true);
    expect(within(drawer).getAllByTestId('extract-pending-drawer-item')).toHaveLength(2);

    // 1A：整行（非按钮处）点开同样开抽屉
    await user.click(within(drawer).getByTestId('extract-pending-drawer-close'));
    await waitFor(() => expect(screen.queryByTestId('extract-pending-drawer')).not.toBeInTheDocument());
    await user.click(within(screen.getByTestId('extract-pending-item')).getByText('18 项'));
    expect(await screen.findByTestId('extract-pending-drawer')).toBeInTheDocument();
  });

  it('契约14（字段逐项一致）：与单批端点的 payload 一致（含 time_display 原文 / parse_reason）', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const drawer = await openDrawer(user);
    expect(within(drawer).getByTestId('extract-pending-field-title')).toHaveTextContent('事件甲');
    expect(within(drawer).getByTestId('extract-pending-field-description')).toHaveTextContent(
      '角色甲与角色乙在山门前交手。',
    );
    expect(within(drawer).getByTestId('extract-pending-field-time_display')).toHaveTextContent('示例历 317 年秋');
    expect(within(drawer).getByTestId('extract-pending-field-parse_reason')).toHaveTextContent('原文缺历法名');
    expect(within(drawer).getByTestId('extract-pending-field-era')).toHaveTextContent('默认轴');
    expect(within(drawer).getByTestId('extract-pending-field-entity_type')).toHaveTextContent('时间线');
    expect(within(drawer).getByTestId('extract-pending-field-action')).toHaveTextContent(
      extractZh['extract.pendingActionCreate'],
    );

    // 切条目 → 明细随选中条目切换
    await user.click(within(drawer).getAllByTestId('extract-pending-drawer-item')[1]);
    expect(within(drawer).getByTestId('extract-pending-field-title')).toHaveTextContent('事件乙');
    expect(within(drawer).getByTestId('extract-pending-field-action')).toHaveTextContent(
      extractZh['extract.pendingActionUpdate'],
    );
  });

  it('契约15（空字段）：给占位文案、不渲染 null', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const drawer = await openDrawer(user);
    const empty = extractZh['extract.pendingFieldEmpty'];
    expect(within(drawer).getByTestId('extract-pending-field-time_value')).toHaveTextContent(empty);
    expect(within(drawer).getByTestId('extract-pending-field-time_unit')).toHaveTextContent(empty);
    expect(within(drawer).getByTestId('extract-pending-field-narrative_position')).toHaveTextContent(empty);
    expect(drawer.textContent ?? '').not.toContain('null');
  });

  it('契约16（丢弃）：DELETE 条目级端点、零物化（不调 confirm）', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const drawer = await openDrawer(user);
    await user.click(within(drawer).getByTestId('extract-pending-discard'));

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) =>
            c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/items/7' &&
            (c[1] as { method?: string })?.method === 'DELETE',
        ),
      ).toBe(true),
    );
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm'))).toBe(false);
  });

  it('契约17（确认落库强制带时间）：未填禁用；填后 POST 条目级端点（带 time_value / time_unit）', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry();

    const drawer = await openDrawer(user);
    const confirmBtn = within(drawer).getByTestId('extract-pending-item-confirm');
    expect(confirmBtn).toBeDisabled();

    await user.type(within(drawer).getByTestId('extract-pending-drawer-time'), '317');
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/items/7/confirm',
      );
      expect(call).toBeDefined();
      expect((call?.[1] as { body?: Record<string, unknown> })?.body).toEqual({
        time_value: 317,
        time_unit: '年',
      });
    });
  });

  it('契约18（i18n）：新增键 zh/en 逐条对齐', async () => {
    const keys = [
      'pendingCancelTitle',
      'pendingCancelBody',
      'pendingCancelMinimize',
      'pendingCancelBack',
      'pendingDetail',
      'pendingDrawerTitle',
      'pendingDrawerItems',
      'pendingFieldEmpty',
      'pendingTimeLabel',
      'pendingTimePlaceholder',
      'pendingActionCreate',
      'pendingActionUpdate',
      'pendingField.title',
      'pendingField.description',
      'pendingField.time_display',
      'pendingField.parse_reason',
      'pendingField.time_value',
      'pendingField.time_unit',
      'pendingField.era',
      'pendingField.era_value',
      'pendingField.era_scale',
      'pendingField.narrative_position',
      'pendingField.timeline_flag',
      'pendingField.entity_type',
      'pendingField.action',
    ];
    for (const k of keys) {
      const key = `extract.${k}`;
      expect(extractZh[key], `${key} zh`).toBeTruthy();
      expect(extractEn[key], `${key} en`).toBeTruthy();
    }
  });
});
