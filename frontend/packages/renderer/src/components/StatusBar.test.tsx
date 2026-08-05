/**
 * 状态栏空值契约（Issue #98 RED 阶段，spec §5.2.7 差距 #8）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 StatusBar 必须匹配（行为断言，不测样式）：
 *
 * - model 空字符串 '' 与 null 统一显示「—」（现状 null 已处理、'' 未处理 → RED 缺口）
 *   - '' 时渲染「模型: —」，不得渲染「模型: 」空值残留
 * - 内核连接项显示状态值：StatusBar 新增可选 prop `kernelConnected?: boolean`（缺省 true）
 *   - true（或缺省）→ t('sb.kernel') 文案「内核已连接」
 *   - false → t('sb.kernelOffline') 文案「内核未就绪」
 *   （现状仅渲染 sb.kernel 固定文案、无状态值切换 → RED 缺口）
 * - 正常 model 值渲染「模型: {model}」不变（回归）
 *
 * 设计假设：内核连接状态以组件 prop 注入（组件层可测，不依赖全局状态）；
 * WritingPage 传入真实内核状态属 GREEN 集成范畴，本文件只契约组件自身。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBar } from './StatusBar';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('StatusBar — 空值契约（#98 §5.2.7）', () => {
  it('model 空字符串 → 显示「—」（不显示「模型: 」空值残留）', () => {
    render(<StatusBar model="" wordCount={0} savedAt={null} />);
    expect(screen.getByText('模型: —')).toBeInTheDocument();
  });

  it('model null → 显示「—」（既有 null 处理保持）', () => {
    render(<StatusBar model={null} wordCount={0} savedAt={null} />);
    expect(screen.getByText('模型: —')).toBeInTheDocument();
  });

  it('model 正常值 → 显示「模型: {model}」', () => {
    render(<StatusBar model="gpt-4o" wordCount={1234} savedAt={null} />);
    expect(screen.getByText('模型: gpt-4o')).toBeInTheDocument();
    expect(screen.getByText('字数: 1,234')).toBeInTheDocument();
  });

  it('内核连接项状态值：kernelConnected 缺省 → 「内核已连接」', () => {
    render(<StatusBar model={null} wordCount={0} savedAt={null} />);
    expect(screen.getByText('内核已连接')).toBeInTheDocument();
  });

  it('内核连接项状态值：kernelConnected=false → 「内核未就绪」（不显示已连接）', () => {
    render(<StatusBar model={null} wordCount={0} savedAt={null} kernelConnected={false} />);
    expect(screen.getByText('内核未就绪')).toBeInTheDocument();
    expect(screen.queryByText('内核已连接')).not.toBeInTheDocument();
  });
});
