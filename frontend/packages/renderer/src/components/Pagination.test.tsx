/**
 * #1300：分页公共组件 `Pagination` —— 组件单测（RED 契约）。
 *
 * 背景：分页逻辑此前两处内联且形态不一（pages/logs.tsx 完整形态含 pageSize 选择；
 * components/OutlineTreeBar.tsx OutlinePager 仅 页码 + prev/next），其余长列表页无分页。
 * 本契约锁定公共组件的 props 语义与边界行为，作为 logs / outline / 设定库 / 会话 / 搜索
 * 各页接入的单一事实来源。
 *
 * props 契约（实现必须逐项匹配）：
 *   page: number              当前页（0 基）
 *   pageSize: number          每页条数（<=0 视为未提供 → 回退默认值）
 *   total: number             总条数
 *   onPageChange(page)        翻页回调（收到 0 基页码）
 *   onPageSizeChange?(size)   pageSize 选择回调；**未提供时不渲染 Select**（大纲树形态）
 *   pageSizeOptions?: number[] 可选页大小（默认 [10, 25, 50, 100]，对齐日志页现状）
 *   totalText?: boolean       是否在 info 中携带总数（默认 true；info 恒含 part/total(pageSize 选择区)
 *   testIdPrefix?: string     testid 前缀（默认 'pagination'）；logs 页传 'log-page'、大纲传 'outline-page'
 *                             以保留既有契约 testid（log-page-prev / outline-page-next …）
 *
 * testid 形状（prefix 参数化单点生成，禁手写双份）：
 *   `${prefix}-prev` / `${prefix}-next` / `${prefix}-info` / `${prefix}-size-select`
 *
 * info 文案：i18n key `pagination.page.info`，插值 { page, pages, total }
 *   → zh：`第 {page} / {pages} 页 · 共 {total} 条`
 *   prev/next：`pagination.page.prev` / `pagination.page.next`
 *   页大小 aria-label：`pagination.page.size.label`
 *   （logs/outline 页改用公共组件后，既有断言文本 `第 1 / 12 页 · 共 120 条` 必须保持逐字一致
 *   → 该文案由 `pagination.page.info` 单点提供，zh/en 各一条。）
 *
 * 边界四类（issue §3.5 明细，本文件全覆盖）：
 *   B1 首页：page=0 → prev 禁用；page>0 → prev 可用
 *   B2 末页：(page+1)*pageSize >= total → next 禁用；未到末页 → next 可用
 *   B3 total=0：不崩、pages 收敛为 1、prev/next 均禁用、info 显示 共 0 条
 *   B4 pageSize 切换：改 pageSize → onPageSizeChange(size) + **重置到第 1 页**（onPageChange(0)）
 *      仅当 page !== 0 时才回调 onPageChange(0)（已首页不产生冗余回调）
 *
 * 可证伪性（RED 自证，交付时执行）：
 *   去掉 disabled={page<=0} → B1 必 FAIL；去掉 lastPage 判断 → B2 必 FAIL。
 *   本文件在组件不存在时 collection 失败（import 无法解析）→ 属预期 RED 形态。
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Pagination } from './Pagination';
import { tStatic } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';

/** 统一渲染助手：i18n 默认 zh（store 初始态） */
function renderPagination(props: Partial<React.ComponentProps<typeof Pagination>> = {}) {
  const onPageChange = vi.fn();
  const onPageSizeChange = vi.fn();
  const merged = {
    page: 0,
    pageSize: 10,
    total: 100,
    onPageChange,
    onPageSizeChange,
    ...props,
  } as React.ComponentProps<typeof Pagination>;
  render(<Pagination {...merged} />);
  return { onPageChange, onPageSizeChange };
}

describe('#1300 Pagination 公共组件', () => {
  describe('B1 首页边界', () => {
    it('page=0 → prev 禁用', () => {
      renderPagination({ page: 0, pageSize: 10, total: 100 });
      expect(screen.getByTestId('pagination-prev')).toBeDisabled();
    });

    it('page>0 → prev 可用', () => {
      renderPagination({ page: 2, pageSize: 10, total: 100 });
      expect(screen.getByTestId('pagination-prev')).not.toBeDisabled();
    });

    it('点击 prev → onPageChange(page-1)', async () => {
      const user = userEvent.setup();
      const { onPageChange } = renderPagination({ page: 3, pageSize: 10, total: 100 });
      await user.click(screen.getByTestId('pagination-prev'));
      expect(onPageChange).toHaveBeenCalledWith(2);
    });
  });

  describe('B2 末页边界', () => {
    it('末页（(page+1)*pageSize >= total）→ next 禁用', () => {
      renderPagination({ page: 9, pageSize: 10, total: 100 });
      expect(screen.getByTestId('pagination-next')).toBeDisabled();
    });

    it('末页恰好整除 → next 禁用', () => {
      renderPagination({ page: 4, pageSize: 20, total: 100 });
      expect(screen.getByTestId('pagination-next')).toBeDisabled();
    });

    it('未到末页 → next 可用', () => {
      renderPagination({ page: 8, pageSize: 10, total: 100 });
      expect(screen.getByTestId('pagination-next')).not.toBeDisabled();
    });

    it('点击 next → onPageChange(page+1)', async () => {
      const user = userEvent.setup();
      const { onPageChange } = renderPagination({ page: 1, pageSize: 10, total: 100 });
      await user.click(screen.getByTestId('pagination-next'));
      expect(onPageChange).toHaveBeenCalledWith(2);
    });
  });

  describe('B3 total=0 不崩', () => {
    it('total=0 → 渲染成功且 prev/next 均禁用', () => {
      renderPagination({ page: 0, pageSize: 10, total: 0 });
      expect(screen.getByTestId('pagination-prev')).toBeDisabled();
      expect(screen.getByTestId('pagination-next')).toBeDisabled();
    });

    it('total=0 → info 显示「第 1 / 1 页 · 共 0 条」（pages 收敛为 1）', () => {
      renderPagination({ page: 0, pageSize: 10, total: 0 });
      expect(screen.getByTestId('pagination-info')).toHaveTextContent('第 1 / 1 页 · 共 0 条');
    });
  });

  describe('B4 pageSize 切换重置到第 1 页', () => {
    it('page>0 时切换 pageSize → onPageSizeChange(size) + onPageChange(0)', async () => {
      const user = userEvent.setup();
      const { onPageChange, onPageSizeChange } = renderPagination({
        page: 5,
        pageSize: 50,
        total: 500,
      });
      await user.click(screen.getByTestId('pagination-size-select'));
      await user.click(screen.getByRole('option', { name: '10' }));
      expect(onPageSizeChange).toHaveBeenCalledWith(10);
      expect(onPageChange).toHaveBeenCalledWith(0);
    });

    it('已在第 1 页切换 pageSize → onPageSizeChange(size)，不产生冗余 onPageChange', async () => {
      const user = userEvent.setup();
      const { onPageChange, onPageSizeChange } = renderPagination({
        page: 0,
        pageSize: 50,
        total: 500,
      });
      await user.click(screen.getByTestId('pagination-size-select'));
      await user.click(screen.getByRole('option', { name: '25' }));
      expect(onPageSizeChange).toHaveBeenCalledWith(25);
      expect(onPageChange).not.toHaveBeenCalled();
    });
  });

  describe('页面信息与页大小选项', () => {
    it('info 文案：第 {page} / {pages} 页 · 共 {total} 条（1 基显示）', () => {
      renderPagination({ page: 1, pageSize: 10, total: 120 });
      expect(screen.getByTestId('pagination-info')).toHaveTextContent('第 2 / 12 页 · 共 120 条');
    });

    it('默认页大小选项 = 10/25/50/100（对齐日志页现状）', async () => {
      const user = userEvent.setup();
      renderPagination({ page: 0, pageSize: 50, total: 500 });
      await user.click(screen.getByTestId('pagination-size-select'));
      for (const size of ['10', '25', '50', '100']) {
        expect(screen.getByRole('option', { name: size })).toBeInTheDocument();
      }
    });

    it('pageSizeOptions 可定制（自下而上覆盖默认档位）', async () => {
      const user = userEvent.setup();
      renderPagination({ page: 0, pageSize: 20, total: 200, pageSizeOptions: [20, 40] });
      await user.click(screen.getByTestId('pagination-size-select'));
      expect(screen.getByRole('option', { name: '20' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: '40' })).toBeInTheDocument();
    });

    it('未提供 onPageSizeChange → 不渲染页大小 Select（大纲树形态）', () => {
      renderPagination({ page: 0, pageSize: 10, total: 100, onPageSizeChange: undefined });
      expect(screen.queryByTestId('pagination-size-select')).not.toBeInTheDocument();
      // prev/info/next 仍须存在
      expect(screen.getByTestId('pagination-prev')).toBeInTheDocument();
      expect(screen.getByTestId('pagination-info')).toBeInTheDocument();
      expect(screen.getByTestId('pagination-next')).toBeInTheDocument();
    });
  });

  describe('testIdPrefix：既有契约 testid 保留（迁移零改测）', () => {
    it("prefix='log-page' → log-page-prev / log-page-info / log-page-next / log-page-size-select", () => {
      renderPagination({ page: 0, pageSize: 50, total: 500, testIdPrefix: 'log-page' });
      expect(screen.getByTestId('log-page-prev')).toBeInTheDocument();
      expect(screen.getByTestId('log-page-info')).toBeInTheDocument();
      expect(screen.getByTestId('log-page-next')).toBeInTheDocument();
      expect(screen.getByTestId('log-page-size-select')).toBeInTheDocument();
    });

    it("prefix='outline-page' → outline-page-prev / -info / -next（无 size-select）", () => {
      renderPagination({
        page: 0,
        pageSize: 10,
        total: 100,
        testIdPrefix: 'outline-page',
        onPageSizeChange: undefined,
      });
      expect(screen.getByTestId('outline-page-prev')).toBeInTheDocument();
      expect(screen.getByTestId('outline-page-info')).toBeInTheDocument();
      expect(screen.getByTestId('outline-page-next')).toBeInTheDocument();
      expect(screen.queryByTestId('outline-page-size-select')).not.toBeInTheDocument();
    });
  });

  describe('i18n 双语', () => {
    it('新增 pagination.* key 已就位（zh）', () => {
      useThemeStore.setState({ lang: 'zh' });
      expect(tStatic('pagination.page.prev')).toBe('上一页');
      expect(tStatic('pagination.page.next')).toBe('下一页');
      expect(tStatic('pagination.page.info')).toBe('第 {page} / {pages} 页 · 共 {total} 条');
      expect(tStatic('pagination.page.size.label')).toBe('每页条数');
    });

    it('新增 pagination.* key 已就位（en）', () => {
      useThemeStore.setState({ lang: 'en' });
      expect(tStatic('pagination.page.prev')).toBe('Previous');
      expect(tStatic('pagination.page.next')).toBe('Next');
      expect(tStatic('pagination.page.info')).toBe('Page {page} / {pages} · {total} entries');
      expect(tStatic('pagination.page.size.label')).toBe('Page size');
      useThemeStore.setState({ lang: 'zh' });
    });
  });
});
