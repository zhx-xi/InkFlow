/**
 * F3 a11y 契约测试（S3e，2026-09-02）。
 *
 * 范围（对应 S3e 前端质量补测 F3）：
 * ① axe 扫描：关键对话框（ConfirmDialog / NewProjectDialog）0 违规 —— 守护未来不引入 aria 违规。
 * ② 键盘焦点：自定义对话框打开后焦点必须落入对话框内（初始焦点）+ Tab 不逃出对话框（焦点陷阱）。
 * ③ 流式区：SSE 增量渲染的输出区必须声名 aria-live（读屏器播报流式增量）。
 *
 * 注意：当前实现自定义对话框（div[role=dialog]）不管理初始焦点 → ② 为真 RED；①③ 中
 * aria-live 缺失为真 RED，axe 为守护。
 */

import { axe } from 'jest-axe';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmDialog } from './ConfirmDialog';
import { NewProjectDialog } from './NewProjectDialog';

// jest-axe 的 toHaveNoViolations 是 jest 专用 matcher（调 expectAssertion，vitest 无此 API）。
// 这里自定义一个 vitest 兼容的等效 matcher：失败信息列出违规 id/impact/help。
expect.extend({
  toHaveNoViolations(results: { violations: Array<{ id: string; impact: string; help: string }> }) {
    const violations = results.violations ?? [];
    if (violations.length === 0) {
      return { pass: true, message: () => '未发现 axe 违规' };
    }
    const msgs = violations.map((v) => `${v.id} (${v.impact}): ${v.help}`).join('\n');
    return { pass: false, message: () => `发现 ${violations.length} 处 axe 违规：\n${msgs}` };
  },
});

// NewProjectDialog 挂载会 loadTemplates（apiFetch GET /agent-templates）+ 依赖 templates store。
// mock apiFetch 返回空模板 + 默认 project/providers 空，对话框即可渲染（不触发真实网络）。
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/agent-templates') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/providers') return { items: [], total: 0, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

function renderConfirmDialog() {
  return render(
    <ConfirmDialog
      open
      title="确认删除"
      message={<p>将永久删除，无法恢复</p>}
      confirmText="删除"
      danger
      testidPrefix="confirm-test"
      onConfirm={() => {}}
      onOpenChange={() => {}}
    />,
  );
}

describe('F3 a11y：axe 扫描（守护，0 违规）', () => {
  it('ConfirmDialog axe 扫描无违规', async () => {
    renderConfirmDialog();
    const dialog = (await screen.findByRole('dialog', { name: '确认删除' })) as HTMLElement;
    expect(await axe(dialog)).toHaveNoViolations();
  });

  it('NewProjectDialog axe 扫描无违规', async () => {
    render(
      <MemoryRouter>
        <NewProjectDialog onClose={() => {}} />
      </MemoryRouter>,
    );
    const dialog = (await screen.findByRole('dialog')) as HTMLElement;
    expect(await axe(dialog)).toHaveNoViolations();
  });
});

describe('F3 a11y：对话框初始焦点 + 焦点陷阱（RED：当前 div[role=dialog] 不管理焦点）', () => {
  it('ConfirmDialog 打开后焦点必须落入对话框内（初始焦点）', async () => {
    renderConfirmDialog();
    const dialog = (await screen.findByRole('dialog', { name: '确认删除' })) as HTMLElement;
    // RED：当前 activeElement = body（未 autofocus / 未聚焦任一可操作元素）→ 断言失败
    await waitFor(() =>
      expect(dialog.contains(document.activeElement as Node)).toBe(true),
    );
  });

  it('ConfirmDialog 键盘操作：Tab 在对话框内循环（取消↔删除，不逃出）且 Esc 关闭', async () => {
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        title="确认删除"
        message={<p>将永久删除</p>}
        confirmText="删除"
        danger
        testidPrefix="confirm-test"
        onConfirm={() => {}}
        onOpenChange={onOpenChange}
      />,
    );
    const dialog = (await screen.findByRole('dialog', { name: '确认删除' })) as HTMLElement;
    const user = userEvent.setup();

    // 初始焦点必须已在对话框内（否则 Tab 可能逃逸）
    await waitFor(() => expect(dialog.contains(document.activeElement as Node)).toBe(true));

    // 连续 Tab，焦点始终在对话框内的可操作元素
    for (let i = 0; i < 4; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement as Node)).toBe(true);
    }

    // Esc 关闭
    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalled();
  });

  it('NewProjectDialog 打开后焦点必须落入对话框内（初始焦点）', async () => {
    render(
      <MemoryRouter>
        <NewProjectDialog onClose={() => {}} />
      </MemoryRouter>,
    );
    const dialog = (await screen.findByRole('dialog')) as HTMLElement;
    await waitFor(() =>
      expect(dialog.contains(document.activeElement as Node)).toBe(true),
    );
  });
});
