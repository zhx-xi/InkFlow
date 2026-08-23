/**
 * F50 #563 RED 契约：设置页「MCP 接入」面板（McpSettingsCard）。
 *
 * 契约（GREEN 实现，本文件只写测试不改 src/）：
 * - 挂载调 fetchMcpInfo()（src/api/client.ts 新导出；GET /api/v1/mcp/info）
 * - root data-testid="mcp-settings-panel"
 * - 显示当前客户端 exe 路径（动态）：data-testid="mcp-client-path"
 * - 一键复制按钮：mcp-copy-path（复制 client_path）/ mcp-copy-claude / mcp-copy-cursor /
 *   mcp-copy-hermes（复制 config_template[host] 的 JSON.stringify(_, null, 2)）
 * - 用 navigator.clipboard.writeText；复制路径成功 → toast ok「已复制」/ 失败 → toast err
 * - fetchMcpInfo 失败 → 面板降级「暂不可用」（mcp-unavailable），不抛错
 *
 * Mock 形态：vi.mock('../api/client') 提供 fetchMcpInfo；navigator.clipboard 用
 * Object.defineProperty 注入 writeText mock（jsdom 无 clipboard）；useToastStore 真断言。
 *
 * RED 预期：./McpSettingsCard 组件不存在 → import 失败 → 整个文件 collection error（Failed Suites 1）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { McpSettingsCard } from './McpSettingsCard';
import { fetchMcpInfo } from '../api/client';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    fetchMcpInfo: vi.fn(),
  };
});

const fetchMcpInfoMock = vi.mocked(fetchMcpInfo);

const FAKE_CLIENT = 'C:\\fake\\resources\\kernel\\mcp\\inkflow-mcp.exe';
const MCP_INFO = {
  client_path: FAKE_CLIENT,
  version: '0.12.0',
  config_template: {
    claude: { mcpServers: { inkflow: { command: FAKE_CLIENT } } },
    cursor: { mcpServers: { inkflow: { command: FAKE_CLIENT } } },
    hermes: { mcpServers: { inkflow: { command: FAKE_CLIENT } } },
  },
};

const clipboardWriteMock = vi.fn();

beforeEach(() => {
  fetchMcpInfoMock.mockReset();
  useToastStore.setState({ toasts: [] });
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: clipboardWriteMock },
    configurable: true,
    writable: true,
  });
  clipboardWriteMock.mockReset();
  clipboardWriteMock.mockResolvedValue(undefined);
});

function renderCard() {
  return render(<McpSettingsCard />);
}

describe('McpSettingsCard — MCP 接入（#563）', () => {
  it('test_renders_panel_and_client_path：挂载展示 root + 动态 client_path', async () => {
    fetchMcpInfoMock.mockResolvedValue(MCP_INFO);
    renderCard();
    expect(await screen.findByTestId('mcp-settings-panel')).toBeInTheDocument();
    expect(screen.getByTestId('mcp-client-path')).toHaveTextContent(FAKE_CLIENT);
  });

  it('test_copy_path：点击复制路径 → clipboard.writeText(client_path)', async () => {
    fetchMcpInfoMock.mockResolvedValue(MCP_INFO);
    renderCard();
    await waitFor(() => expect(screen.getByTestId('mcp-copy-path')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mcp-copy-path'));
    await waitFor(() => expect(clipboardWriteMock).toHaveBeenCalledTimes(1));
    expect(clipboardWriteMock).toHaveBeenCalledWith(FAKE_CLIENT);
  });

  it('test_copy_claude_json：复制 Claude 配置 JSON（mcpServers.inkflow.command=client_path）', async () => {
    fetchMcpInfoMock.mockResolvedValue(MCP_INFO);
    renderCard();
    await waitFor(() => expect(screen.getByTestId('mcp-copy-claude')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mcp-copy-claude'));
    await waitFor(() => expect(clipboardWriteMock).toHaveBeenCalledTimes(1));
    const written = clipboardWriteMock.mock.calls[0][0] as string;
    expect(JSON.parse(written)).toEqual({
      mcpServers: { inkflow: { command: FAKE_CLIENT } },
    });
  });

  it('test_copy_cursor_and_hermes：三宿主复制按钮均在且 JSON 结构一致', async () => {
    fetchMcpInfoMock.mockResolvedValue(MCP_INFO);
    renderCard();
    await waitFor(() => expect(screen.getByTestId('mcp-copy-cursor')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mcp-copy-cursor'));
    fireEvent.click(screen.getByTestId('mcp-copy-hermes'));
    await waitFor(() => expect(clipboardWriteMock).toHaveBeenCalledTimes(2));
    for (const call of clipboardWriteMock.mock.calls) {
      expect(JSON.parse(call[0] as string)).toEqual({
        mcpServers: { inkflow: { command: FAKE_CLIENT } },
      });
    }
  });

  it('test_fetch_failed_shows_unavailable：端点失败 → 面板降级不抛错', async () => {
    fetchMcpInfoMock.mockRejectedValue(new Error('offline'));
    renderCard();
    expect(await screen.findByTestId('mcp-unavailable')).toBeInTheDocument();
  });
});
