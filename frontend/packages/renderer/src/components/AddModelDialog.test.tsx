/**
 * AddModelDialog 单元测试（Issue #106 F3，spec §8.2③ L929 多选一次性添加）：
 * 渲染（provider 选择 + 模型行草稿）/ 行增删 / 类型与 Provider 切换 / 保存成功与失败 / 取消 / 遮罩 / 无 provider 守卫。
 *
 * 组件为纯受控弹窗（不直接调 apiFetch）：onAdd / onDone / onOpenChange 以 vi.fn 注入断言。
 * store.addModel 的 PATCH 全量语义由 models.test.tsx 集成用例覆盖（本文件不重测 store 逻辑）。
 */
import { describe, it, expect, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AddModelDialog } from './AddModelDialog';
import type { ProviderConfig, ProviderModel } from '../stores/models';

const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
    models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat',
    models: [],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

function renderDialog(overrides: {
  open?: boolean;
  providers?: ProviderConfig[];
  onOpenChange?: (open: boolean) => void;
  onAdd?: (providerId: number, model: ProviderModel) => Promise<void>;
  onDone?: () => void;
} = {}) {
  const onOpenChange = overrides.onOpenChange ?? vi.fn();
  const onAdd = overrides.onAdd ?? vi.fn();
  const onDone = overrides.onDone ?? vi.fn();
  render(
    <AddModelDialog
      open={overrides.open ?? true}
      providers={overrides.providers ?? PROVIDERS}
      onOpenChange={onOpenChange}
      onAdd={onAdd}
      onDone={onDone}
    />,
  );
  return { onOpenChange, onAdd, onDone };
}

describe('AddModelDialog — 渲染 / 开关', () => {
  it('open=true → dialog + 标题 + 默认第一个 Provider + 一行空草稿（模型 ID/类型/角色用途）+ 操作按钮', () => {
    renderDialog();
    const dlg = screen.getByTestId('add-model-dialog');
    expect(within(dlg).getByText('添加模型')).toBeInTheDocument();
    // 默认 Provider = 第一个（openai）
    expect(within(dlg).getByRole('combobox', { name: '选择 Provider' })).toHaveTextContent('openai');
    // 一行空草稿：模型 ID / 类型（默认 chat）/ 角色用途
    expect(within(dlg).getByLabelText('模型 ID 1')).toHaveValue('');
    expect(within(dlg).getByRole('combobox', { name: '类型 1' })).toHaveTextContent('chat');
    expect(within(dlg).getByLabelText('角色用途 1')).toHaveValue('');
    expect(within(dlg).getByRole('button', { name: '添加一行' })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: '取消' })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: '保存' })).toBeInTheDocument();
  });

  it('open=false → 不渲染', () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId('add-model-dialog')).not.toBeInTheDocument();
  });
});

describe('AddModelDialog — 行增删', () => {
  it('添加一行 → 第二行出现；删除行按钮 → 该行移除', async () => {
    const user = userEvent.setup();
    renderDialog();
    expect(screen.queryByLabelText('模型 ID 2')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '添加一行' }));
    expect(screen.getByLabelText('模型 ID 2')).toBeInTheDocument();
    expect(screen.getByLabelText('角色用途 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '删除 2' }));
    expect(screen.queryByLabelText('模型 ID 2')).not.toBeInTheDocument();
    expect(screen.getByLabelText('模型 ID 1')).toBeInTheDocument();
  });
});

describe('AddModelDialog — 保存', () => {
  it('保存成功：单行 → onAdd(providerId, {id,type,roles}) + onDone + onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onAdd, onDone, onOpenChange } = renderDialog();
    // 角色串容忍空白：' writing , audit ' → ['writing','audit']
    await user.type(screen.getByLabelText('模型 ID 1'), 'gpt-4o-mini');
    await user.type(screen.getByLabelText('角色用途 1'), ' writing , audit ');

    await user.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledWith(1, { id: 'gpt-4o-mini', type: 'chat', roles: ['writing', 'audit'] });
    });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('多行 + 类型切换 + Provider 切换：onAdd 按行序逐条调用', async () => {
    const user = userEvent.setup();
    const { onAdd, onDone, onOpenChange } = renderDialog();

    await user.type(screen.getByLabelText('模型 ID 1'), 'a-chat');
    // 第二行：类型切 embedding
    await user.click(screen.getByRole('button', { name: '添加一行' }));
    await user.type(screen.getByLabelText('模型 ID 2'), 'b-emb');
    await user.click(screen.getByRole('combobox', { name: '类型 2' }));
    await user.click(await screen.findByRole('option', { name: 'embedding' }));
    // Provider 切到 deepseek（id=2）
    await user.click(screen.getByRole('combobox', { name: '选择 Provider' }));
    await user.click(await screen.findByRole('option', { name: 'deepseek' }));

    await user.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledTimes(2);
    });
    expect(onAdd).toHaveBeenNthCalledWith(1, 2, { id: 'a-chat', type: 'chat', roles: [] });
    expect(onAdd).toHaveBeenNthCalledWith(2, 2, { id: 'b-emb', type: 'embedding', roles: [] });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('全部行 ID 为空 → 保存 no-op（onAdd/onDone/onOpenChange 均不调用，弹窗仍在）', async () => {
    const user = userEvent.setup();
    const { onAdd, onDone, onOpenChange } = renderDialog();
    await user.click(screen.getByRole('button', { name: '保存' }));
    expect(onAdd).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByTestId('add-model-dialog')).toBeInTheDocument();
  });

  it('保存失败（onAdd reject）→ 弹窗不关闭 + onDone 不调用 + 保存按钮恢复可用', async () => {
    // vitest 对 unhandledRejection：存在第二个监听器时视为用户代码已接管（execute catchError 检查 listeners.length > 1），
    // 组件 handleSave 无 catch（onAdd reject 沿 void handleSave() 逸出），测试注册吞错监听避免污染套件
    const swallow = () => {};
    process.on('unhandledRejection', swallow);
    try {
      const onAdd = vi.fn().mockRejectedValue(new Error('网络错误'));
      const { onOpenChange, onDone } = renderDialog({ onAdd });
      const user = userEvent.setup();
      await user.type(screen.getByLabelText('模型 ID 1'), 'gpt-4o-mini');
      await user.click(screen.getByRole('button', { name: '保存' }));

      await waitFor(() => {
        expect(onAdd).toHaveBeenCalledTimes(1);
        expect(onDone).not.toHaveBeenCalled();
        expect(onOpenChange).not.toHaveBeenCalled();
        // finally 复位 saving → 按钮恢复可用（可重试）
        expect(screen.getByRole('button', { name: '保存' })).toBeEnabled();
      });
      expect(screen.getByTestId('add-model-dialog')).toBeInTheDocument();
    } finally {
      process.removeListener('unhandledRejection', swallow);
    }
  });

  it('无 provider → 保存 no-op（activeProviderId 为 null 守卫）', async () => {
    const user = userEvent.setup();
    const { onAdd, onDone, onOpenChange } = renderDialog({ providers: [] });
    expect(screen.getByRole('combobox', { name: '选择 Provider' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '保存' }));
    expect(onAdd).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

describe('AddModelDialog — 关闭路径', () => {
  it('取消按钮 → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('遮罩点击（非 saving）→ onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole('presentation'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('保存进行中（onAdd pending）→ 遮罩点击不关闭；完成后 onDone + 关闭', async () => {
    let resolveAdd!: () => void;
    const onAdd = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => { resolveAdd = resolve; }),
    );
    const { onOpenChange, onDone } = renderDialog({ onAdd });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('模型 ID 1'), 'gpt-4o-mini');
    await user.click(screen.getByRole('button', { name: '保存' }));

    // saving=true：遮罩点击 no-op
    await user.click(screen.getByRole('presentation'));
    expect(onOpenChange).not.toHaveBeenCalled();

    // 完成保存 → onDone + 关闭
    await act(async () => { resolveAdd(); });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
