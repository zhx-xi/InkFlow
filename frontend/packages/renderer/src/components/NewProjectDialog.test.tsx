/**
 * NewProjectDialog 测试契约（Issue #105 §6.2③ 模态交互 + §6.3② 创建失败错误展示）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/components/NewProjectDialog.tsx 必须匹配：
 *
 * §6.2③ 模态交互（新增）：
 * - ESC 键关闭：keydown Escape（焦点在对话框内时）→ 调用 onClose、对话框卸载
 * - 遮罩点击关闭：点击 backdrop（role=dialog 的外层容器）→ onClose（dialog 内部点击不冒泡关闭）
 * - 焦点归还：任何关闭路径（ESC/遮罩/取消）后焦点归还触发按钮（记录打开时 activeElement
 *   或调用方传 triggerRef；本测试用 Harness 模拟 projects.tsx 的「触发按钮打开对话框」用法）
 * - 过渡动效（≤180ms，reduced-motion 降级）：不测样式，仅要求关闭可同步/短时完成（waitFor 兜底）
 *
 * §6.3② 创建失败错误展示（新增，现状 handleCreate 无 try/catch）：
 * - createProject reject → 对话框内展示错误文案（复用现有内联 error 区域，样式 text-err）
 * - 新增 i18n key：`dlg.createFailed`（如「创建失败: {原因}」）——GREEN 补 zh.ts/en.ts
 * - 对话框保持打开（用户可修正后重试）
 *
 * 既有行为保持（迁移自 projects.test.tsx）：
 * - 创建成功 → POST /api/v1/projects（body {name, genre, language, target_words}）→ navigate('/writing')
 * - 书名空校验「书名不能为空」不发 POST（既有）
 *
 * RED 预期：ESC 关闭/焦点归还/错误展示缺失 → element-missing / 行为断言 FAIL。
 */
import { useState } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { NewProjectDialog } from './NewProjectDialog';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 模拟 projects.tsx 用法：触发按钮打开对话框（焦点归还的目标） */
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" data-testid="open-trigger" onClick={() => setOpen(true)}>
        打开新建
      </button>
      {open && <NewProjectDialog onClose={() => setOpen(false)} />}
    </div>
  );
}

function renderHarness() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Harness />} />
        <Route path="/writing" element={<div data-testid="writing-probe">写作页探针</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useProjectStore.setState({
    projects: [],
    currentProjectId: null,
    loading: false,
    error: null,
    chapterProgress: {},
  });
  apiFetchMock.mockResolvedValue({ ok: true });
});

describe('新建项目对话框 — ESC 关闭 + 遮罩点击 + 焦点归还（Issue #105 §6.2③）', () => {
  it('ESC 键关闭对话框 + 焦点归还触发按钮', async () => {
    const user = userEvent.setup();
    renderHarness();

    const trigger = screen.getByTestId('open-trigger');
    await user.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 焦点在对话框内时按 ESC → 关闭 + 焦点回到触发按钮
    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(trigger);
  });

  it('遮罩点击关闭：点击 backdrop → 对话框卸载（dialog 内部点击不关闭）', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    const dialog = screen.getByRole('dialog');
    // backdrop = role=dialog 的外层容器（presentation 角色不在可访问性树，用 DOM 查询）
    const backdrop = dialog.parentElement as HTMLElement;
    expect(backdrop).not.toBeNull();

    // dialog 内部点击（如标题区域）不应关闭
    fireEvent.click(dialog);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 遮罩点击 → 关闭
    fireEvent.click(backdrop);
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('取消按钮关闭 + 焦点归还触发按钮', async () => {
    const user = userEvent.setup();
    renderHarness();

    const trigger = screen.getByTestId('open-trigger');
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: '取消' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(trigger);
  });
});

describe('新建项目对话框 — 创建失败错误展示（Issue #105 §6.3②）', () => {
  it('createProject 失败 → 内联错误文案展示 + 对话框保持打开', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核未就绪'));
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    await user.click(screen.getByRole('button', { name: '创建' }));

    // GREEN 契约：新 i18n key `dlg.createFailed`（如「创建失败: 内核未就绪」）内联展示
    expect(await screen.findByText(/创建失败/)).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });

  it('书名空校验保持：空书名 → 「书名不能为空」，不发 POST', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.click(screen.getByRole('button', { name: '创建' }));

    expect(screen.getByText('书名不能为空')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });
});

describe('新建项目对话框 — 创建成功（既有行为保持）', () => {
  it('创建成功：POST /api/v1/projects → 201 → 跳转写作页', async () => {
    const created = {
      id: 'p9',
      name: '青山入我怀',
      genre: '玄幻',
      language: 'zh-CN',
      target_words: 800000,
      config: {},
      created_at: '2026-08-06T10:00:00Z',
      updated_at: '2026-08-06T10:00:00Z',
    };
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return created;
      return { ok: true };
    });
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', genre: '玄幻', language: 'zh-CN', target_words: 800000 },
      });
    });
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });
});
