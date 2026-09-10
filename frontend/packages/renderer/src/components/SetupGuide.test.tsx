/**
 * F60 首启模型配置引导组件契约（RED — #934 §5 / N1-N5）。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须新建 src/components/SetupGuide.tsx，导出：
 *
 *   export function SetupGuide(): JSX.Element
 *
 * 组件契约（spec §5.1-§5.6）：
 * - 全屏引导容器 data-testid="setup-guide"；不可 ESC 关闭（无 ESC 监听）
 * - 三步指示：data-testid="setup-steps"，步骤 1/2/3 各一项（setup-step-1..3）
 * - 步骤 1：Provider 列表 + 添加 Provider（setup-add-provider）+ 下一步（setup-to-step2）
 * - 步骤 2：chat 模型下拉（setup-chat-select）+ 测试连接（setup-test-conn）
 *   + 失败错误行（setup-test-error）+ 上一步（setup-back-step1）
 * - 步骤 3：embedding 录入 + 跳过（setup-skip-embedding）+ 完成（setup-finish）
 * - 步骤切换：setup-to-step2 进入步骤 2；步骤 2 测试通过后进入步骤 3
 * - N5：llm/test 返回 {ok:false, message} → 留在步骤 2 + 展示 message + 可重试
 * - 完成/跳过 → 调 useModelReadinessStore.getState().load() 复核判据
 *   （由 App 层据新判据卸载本组件；组件自身不 unmount）
 *
 * i18n：新增 key 前缀 setup.*（GREEN 补 zh.ts/en.ts）；断言用 data-testid
 * 而非硬编码中文（防文案微调脆弱）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SetupGuide } from './SetupGuide';
import { apiFetch } from '../api/client';
import { useModelReadinessStore } from '../stores/modelReadiness';
import { useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 已注册一个带 chat 模型的 provider（步骤 1 完成态，可进入步骤 2） */
const PROVIDERS = [
  {
    id: 1,
    name: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    default_model: '',
    models: [{ id: 'deepseek-chat', type: 'chat', roles: [] }],
    key_saved: true,
    max_retries: 3,
    timeout: 120,
    created_at: '2026-09-10T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useModelReadinessStore.setState({
    readiness: {
      ready: false,
      has_chat_model: false,
      has_embedding_model: false,
      reason: 'no_provider',
    },
    loading: false,
  });
  useModelsStore.setState({ providers: [], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // 默认 enrichment：provider 列表信封（组件挂载即 loadProviders）
  apiFetchMock.mockImplementation(async (url: string) => {
    if (url === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: PROVIDERS.length };
    }
    return { ok: true };
  });
});

/** 渲染并等待 provider 列表加载完成（步骤 1 可交互） */
async function renderLoaded() {
  render(<SetupGuide />);
  await waitFor(() => expect(screen.getByTestId('setup-to-step2')).toBeEnabled());
}

/** 推进到步骤 3（步骤 2 探测通过） */
async function advanceToStep3(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('setup-to-step2'));
  await user.click(screen.getByTestId('setup-chat-select'));
  await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
  await user.click(screen.getByTestId('setup-test-conn'));
  await waitFor(() => expect(screen.getByTestId('setup-skip-embedding')).toBeInTheDocument());
}

describe('SetupGuide — 首启配置引导（#934 N1-N5）', () => {
  it('N1：渲染全屏引导容器 + 三步指示', async () => {
    await renderLoaded();
    expect(screen.getByTestId('setup-guide')).toBeInTheDocument();
    expect(screen.getByTestId('setup-steps')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-1')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-2')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-3')).toBeInTheDocument();
  });

  it('N2：步骤 3 有「跳过」按钮（embedding 可跳过）', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    await advanceToStep3(user);
    expect(screen.getByTestId('setup-skip-embedding')).toBeInTheDocument();
  });

  it('N5：llm/test 失败 → 留在引导 + 展示可读错误 + 可重试', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/v1/provider-configs') {
        return { items: PROVIDERS, total: PROVIDERS.length };
      }
      if (url === '/api/v1/settings/llm/test') {
        return { ok: false, message: 'invalid api key' };
      }
      return { ok: true };
    });
    await renderLoaded();
    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(screen.getByTestId('setup-chat-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
    await user.click(screen.getByTestId('setup-test-conn'));
    await waitFor(() => {
      expect(screen.getByTestId('setup-test-error')).toHaveTextContent('invalid api key');
    });
    // 仍在引导内（未卸载）+ 可重试（按钮仍可点）
    expect(screen.getByTestId('setup-guide')).toBeInTheDocument();
    expect(screen.getByTestId('setup-test-conn')).toBeEnabled();
  });

  it('N1/N4：跳过 embedding → 触发 readiness 刷新（load 被调用）', async () => {
    const user = userEvent.setup();
    const loadSpy = vi.spyOn(useModelReadinessStore.getState(), 'load').mockResolvedValue();
    await renderLoaded();
    await advanceToStep3(user);
    await user.click(screen.getByTestId('setup-skip-embedding'));
    await waitFor(() => expect(loadSpy).toHaveBeenCalled());
  });
});
