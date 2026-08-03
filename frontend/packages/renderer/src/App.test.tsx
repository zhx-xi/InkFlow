/**
 * 工程冒烟测试（第一条前端测试，TDD 起点）
 * 断言: App 挂载渲染品牌 + 三路由可达（HashRouter 在 jsdom 下正常）
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';

describe('App 骨架', () => {
  it('渲染品牌与三导航项', () => {
    render(<App />);
    expect(screen.getByText('InkFlow')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '项目' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '写作' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Agent 配置' })).toBeInTheDocument();
  });

  it('默认路由显示项目页', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
  });

  it('点击导航切换到写作页', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '写作' }));
    expect(screen.getByTestId('editor')).toBeInTheDocument();
  });
});
