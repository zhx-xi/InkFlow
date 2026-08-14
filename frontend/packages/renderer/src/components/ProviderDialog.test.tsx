/**
 * ⚠️ 契约文件（Issue #106 ProviderDialog RED 阶段，spec §8.2③ / §8.3 / §8.6 M2）
 *
 * GREEN 新建 src/components/ProviderDialog.tsx，必须匹配：
 *
 * 组件契约：
 * - 受控组件 props：{ open: boolean; onOpenChange(open: boolean): void;
 *   editing?: ProviderConfig | null; onSaved(provider: ProviderConfig): void }
 *   ProviderConfig 结构（与 stores/models 契约一致）：{ id, name, base_url, default_model,
 *   models: [{id, type, roles}], key_saved, max_retries, timeout, created_at, updated_at }
 * - open=true → role=dialog + data-testid="provider-dialog"；标题：editing 为空 →「添加 Provider」，
 *   editing 有值 →「编辑 Provider」；open=false → 不渲染
 * - 表单：名称（label「名称」，必填——空则「保存」disabled）/ Base URL（label「Base URL」）/
 *   API Key（label「API Key」，type=password）
 * - 关闭：取消按钮（「取消」）→ onOpenChange(false)；ESC → onOpenChange(false)
 *
 * 行为契约：
 * - 测试连接（「测试连接」按钮）→ POST /api/v1/settings/llm/test（§8.3 既有端点复用），
 *   body 含 provider / model / base_url / api_key（#267 契约升级 2026-08-12：四键完整——
 *   F2 评审「三键即完整契约」作废。根因：测试发生在保存前 provider 未入库，缺 model
 *   时后端回退链（settings.py L170 注册表 default_model → config.llm_default_model）
 *   必然落空 → 回退 openai/gpt-4o → deepseek API 拒绝无效模型 → 真实 key 也失败。
 *   GREEN 必须将用户输入/预设默认的 model 随请求体发出）：
 *   成功 {ok:true} → toast ok「连接成功」；失败 {ok:false, message} → toast err「连接失败: {message}」
 *   （toast 断言 useToastStore 状态；文案与 agent store 测试连接一致）
 * - 模型输入框：label「模型」，位于名称旁（Base URL 上方）；编辑模式回显 editing.default_model
 * - 预置模板选择（非编辑模式）：选 preset → 名称/Base URL/模型自动填充
 *   （PRESET_TEMPLATES 各 preset 带默认模型：openai 空、deepseek→deepseek-chat、
 *   zhipu→glm-4-flash、ollama→qwen2.5）
 * - 模型留空时测试请求仍发送（body 不含 model 键——后端 LLMTestRequest 语义：
 *   model 缺失 → 回退链兜底；提供但空白（''）→ 提供即校验 422 拒绝。故留空必须缺键，
 *   等价旧行为不劣化）
 * - 保存（「保存」按钮）：
 *   * 添加模式（editing 空）→ POST /api/v1/provider-configs，body 含 name / base_url
 *   * 编辑模式（editing 有值）→ PATCH /api/v1/provider-configs/{id}
 *   * 填了 API Key → 先 POST /api/v1/settings/llm-keys（body 含 provider / api_key，加密存储）
 *   * 请求成功 → onSaved(返回的 ProviderConfig)
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；可复用已有 ag.save「保存」/ ag.test「测试连接」/
 * dlg.cancel「取消」）：m.name='名称' m.model='模型' m.baseUrl='Base URL' m.apiKey='API Key'
 * m.addProvider='添加 Provider' m.editProvider='编辑 Provider'
 * （#267 新增 m.model：zh '模型' / en 'Model'）
 *
 * RED 预期：./ProviderDialog 模块不存在 → module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProviderDialog } from './ProviderDialog';
import { apiFetch } from '../api/client';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约结构（与 stores/models 的 ProviderConfig 一致；GREEN 类型可来自 store 或组件内定义） */
interface ProviderModel {
  id: string;
  type: 'chat' | 'embedding';
  roles: string[];
}
interface ProviderConfig {
  id: number;
  name: string;
  base_url: string;
  default_model: string;
  models: ProviderModel[];
  key_saved: boolean;
  max_retries: number;
  timeout: number;
  created_at: string;
  updated_at: string;
}

const createdProvider: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: '',
  models: [], key_saved: false, max_retries: 3, timeout: 60,
  created_at: '2026-08-06T10:00:00Z', updated_at: '2026-08-06T10:00:00Z',
};

const editingProvider: ProviderConfig = {
  ...createdProvider,
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
  key_saved: true,
};

function renderDialog(overrides?: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  editing?: ProviderConfig | null;
  onSaved?: (provider: ProviderConfig) => void;
}) {
  const onOpenChange = overrides?.onOpenChange ?? vi.fn();
  const onSaved = overrides?.onSaved ?? vi.fn();
  render(
    <ProviderDialog
      open={overrides?.open ?? true}
      onOpenChange={onOpenChange}
      editing={overrides?.editing ?? null}
      onSaved={onSaved}
    />,
  );
  return { onOpenChange, onSaved };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockResolvedValue({ ok: true });
});

describe('ProviderDialog — 打开 / 关闭', () => {
  it('open=true → dialog 渲染 + 「添加 Provider」标题', () => {
    renderDialog();
    const dlg = screen.getByRole('dialog');
    expect(dlg).toHaveAttribute('data-testid', 'provider-dialog');
    expect(within(dlg).getByText('添加 Provider')).toBeInTheDocument();
  });

  it('open=false → 不渲染', () => {
    renderDialog({ open: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('取消按钮 → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('ESC → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('编辑模式：editing 有值 → 「编辑 Provider」标题 + 名称/模型回显', () => {
    renderDialog({ editing: editingProvider });
    const dlg = screen.getByRole('dialog');
    expect(within(dlg).getByText('编辑 Provider')).toBeInTheDocument();
    expect(within(dlg).getByLabelText('名称')).toHaveValue('openai');
    expect(within(dlg).getByLabelText('模型')).toHaveValue('gpt-4o');
  });
});

describe('ProviderDialog — 输入校验', () => {
  it('名称空 → 「保存」disabled；输入名称 → enabled', async () => {
    const user = userEvent.setup();
    renderDialog();
    const saveBtn = screen.getByRole('button', { name: '保存' });
    expect(saveBtn).toBeDisabled();
    await user.type(screen.getByLabelText('名称'), 'openai');
    expect(saveBtn).toBeEnabled();
  });

  it('字段齐全：名称 / 模型 / Base URL / API Key（password）', () => {
    renderDialog();
    expect(screen.getByLabelText('名称')).toBeInTheDocument();
    expect(screen.getByLabelText('模型')).toBeInTheDocument();
    expect(screen.getByLabelText('Base URL')).toBeInTheDocument();
    expect(screen.getByLabelText('API Key')).toHaveAttribute('type', 'password');
  });

  it('选择 deepseek 预置模板 → 名称/Base URL/模型自动填充（deepseek-chat）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('combobox', { name: '预置模板' }));
    await user.click(await screen.findByRole('option', { name: 'deepseek' }));
    expect(screen.getByLabelText('名称')).toHaveValue('deepseek');
    expect(screen.getByLabelText('模型')).toHaveValue('deepseek-chat');
    expect(screen.getByLabelText('Base URL')).toHaveValue('https://api.deepseek.com/v1');
  });

  it('选择 zhipu 预置模板 → 模型自动填充 glm-4-flash；ollama → qwen2.5', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('combobox', { name: '预置模板' }));
    await user.click(await screen.findByRole('option', { name: 'zhipu' }));
    expect(screen.getByLabelText('模型')).toHaveValue('glm-4-flash');
    await user.click(screen.getByRole('combobox', { name: '预置模板' }));
    await user.click(await screen.findByRole('option', { name: 'ollama' }));
    expect(screen.getByLabelText('模型')).toHaveValue('qwen2.5');
  });

  it('openai 预置模板 → 默认模型为空（无预设，用户自填）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('combobox', { name: '预置模板' }));
    await user.click(await screen.findByRole('option', { name: 'openai' }));
    expect(screen.getByLabelText('模型')).toHaveValue('');
  });
});

describe('ProviderDialog — 测试连接（POST /settings/llm/test）', () => {
  async function fillAndTest() {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('名称'), 'openai');
    await user.type(screen.getByLabelText('模型'), 'gpt-4o');
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
    await user.type(screen.getByLabelText('API Key'), 'sk-test-123');
    await user.click(screen.getByRole('button', { name: '测试连接' }));
    return user;
  }

  it('成功 {ok:true} → 请求体四键 {provider, model, base_url, api_key} + toast ok「连接成功」', async () => {
    renderDialog();
    await fillAndTest();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/settings/llm/test',
        expect.objectContaining({
          method: 'POST',
          // #267 契约升级：请求体必须含 model（toEqual 全等锁四键——缺 model 即 FAIL）
          body: {
            provider: 'openai',
            model: 'gpt-4o',
            base_url: 'https://api.openai.com/v1',
            api_key: 'sk-test-123',
          },
        }),
      );
    });
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      const last = toasts[toasts.length - 1];
      expect(last.type).toBe('ok');
      expect(last.message).toBe('连接成功');
    });
  });

  it('失败 {ok:false, message} → toast err「连接失败: {原因}」', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settings/llm/test') return { ok: false, message: '模型不可达' };
      return { ok: true };
    });
    renderDialog();
    await fillAndTest();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/settings/llm/test',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({ model: 'gpt-4o' }),
        }),
      );
    });
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      const last = toasts[toasts.length - 1];
      expect(last.type).toBe('err');
      expect(last.message).toBe('连接失败: 模型不可达');
    });
  });

  it('模型留空 → 测试请求仍发送（body 不含 model 键，后端回退链兜底）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByLabelText('名称'), 'openai');
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
    await user.type(screen.getByLabelText('API Key'), 'sk-test-123');
    await user.click(screen.getByRole('button', { name: '测试连接' }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/settings/llm/test',
        expect.objectContaining({
          method: 'POST',
          // 后端 LLMTestRequest 语义：model 缺失 → 回退链；提供但空白（如 ''）→ 422 拒绝
          // （提供即校验）。故 model 留空时 body 必须不含 model 键（= 旧行为，不劣化）。
          body: {
            provider: 'openai',
            base_url: 'https://api.openai.com/v1',
            api_key: 'sk-test-123',
          },
        }),
      );
    });
  });
});

describe('ProviderDialog — 保存（onSaved 回调）', () => {
  it('添加模式：POST /api/v1/provider-configs → 成功 → onSaved(创建结果)', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') return createdProvider;
      return { ok: true };
    });
    const user = userEvent.setup();
    const { onSaved } = renderDialog();
    await user.type(screen.getByLabelText('名称'), 'openai');
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/provider-configs',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({ name: 'openai', base_url: 'https://api.openai.com/v1' }),
        }),
      );
    });
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(createdProvider);
    });
  });

  it('#348: 添加模式填写模型名 → POST body 含 default_model（设置页/模型管理页同源显示）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') return { ...createdProvider, default_model: 'gpt-4o' };
      return { ok: true };
    });
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByLabelText('名称'), 'openai');
    await user.type(screen.getByLabelText('模型'), 'gpt-4o');
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/provider-configs',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({
            name: 'openai',
            base_url: 'https://api.openai.com/v1',
            // #348：用户填的模型名必须随保存落库（旧实现不发送 → 两页不一致）
            default_model: 'gpt-4o',
          }),
        }),
      );
    });
  });

  it('#348: 编辑模式修改模型名 → PATCH body 含 default_model', async () => {
    const updated = { ...editingProvider, default_model: 'gpt-4o-turbo' };
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs/1') return updated;
      return { ok: true };
    });
    const user = userEvent.setup();
    const { onSaved } = renderDialog({ editing: editingProvider });
    await user.clear(screen.getByLabelText('模型'));
    await user.type(screen.getByLabelText('模型'), 'gpt-4o-turbo');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/provider-configs/1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ default_model: 'gpt-4o-turbo' }),
        }),
      );
    });
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(updated);
    });
  });

  it('编辑模式：PATCH /api/v1/provider-configs/{id} → onSaved', async () => {
    const updated = { ...editingProvider, base_url: 'https://api.openai.com/v2' };
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs/1') return updated;
      return { ok: true };
    });
    const user = userEvent.setup();
    const { onSaved } = renderDialog({ editing: editingProvider });
    await user.clear(screen.getByLabelText('Base URL'));
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v2');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/provider-configs/1',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(updated);
    });
  });

  it('填 API Key 保存：先 POST /settings/llm-keys 落 key（加密存储），再注册 provider-configs', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') return createdProvider;
      return { ok: true };
    });
    const user = userEvent.setup();
    const { onSaved } = renderDialog();
    await user.type(screen.getByLabelText('名称'), 'openai');
    await user.type(screen.getByLabelText('Base URL'), 'https://api.openai.com/v1');
    await user.type(screen.getByLabelText('API Key'), 'sk-test-123');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    // 落 key 调用（body 含 provider / api_key）
    expect(
      apiFetchMock.mock.calls.some(
        (c) => c[0] === '/api/v1/settings/llm-keys' && c[1]?.method === 'POST',
      ),
    ).toBe(true);
    // 注册调用
    expect(
      apiFetchMock.mock.calls.some(
        (c) => c[0] === '/api/v1/provider-configs' && c[1]?.method === 'POST',
      ),
    ).toBe(true);
  });
});
