/**
 * #675 大纲分级创建（level / parent_id）—— GUI 契约
 * specs/f43-setting-library-crud/spec.md §5.15 + #675 拍板：
 *   - outline 分类创建表单新增 level 字段（overall/volume/chapter 三选）
 *   - 创建入口传父级上下文：＋卷 → parent=overall+level=volume；＋章细纲 → parent=volume+level=chapter；＋整本 → level=overall+parent=null
 *   - POST /projects/{pid}/outlines body 含 level/parent_id
 *
 * RED 预期（重写前实现无 level 字段/props）：
 *   R1 library-create-level 不存在 → element-missing FAIL
 *   R2-R4 onSave 收到的 body 无 level/parent_id → toHaveBeenCalledWith 断言 FAIL
 *   R5 无 level select → getByTestId FAIL
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryCreateDialog } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';

const onSave = vi.fn();

function renderOutlineDialog(props?: {
  initialLevel?: 'overall' | 'volume' | 'chapter';
  initialParentId?: string | number | null;
}) {
  return render(
    <LibraryCreateDialog
      open
      cat="outline"
      editing={null}
      initialLevel={props?.initialLevel}
      initialParentId={props?.initialParentId}
      onSave={onSave}
      onOpenChange={() => {}}
    />,
  );
}

beforeEach(() => {
  onSave.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#675 大纲分级创建（level 字段 + 父级上下文）', () => {
  it('R1 outline 创建表单有 level 字段（overall/volume/chapter 三选）', () => {
    renderOutlineDialog();
    const levelSelect = screen.getByTestId('library-create-level');
    expect(levelSelect).toBeInTheDocument();
    const options = Array.from(levelSelect.querySelectorAll('option')).map((o) => o.value);
    expect(options).toEqual(['overall', 'volume', 'chapter']);
  });

  it('R2「＋卷」预填 parent=overall + level=volume → POST body 含 level=volume+parent_id', async () => {
    renderOutlineDialog({ initialLevel: 'volume', initialParentId: 'o1' });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '第一卷');
    expect((screen.getByTestId('library-create-level') as HTMLSelectElement).value).toBe('volume');
    await user.click(screen.getByTestId('library-create-save'));
    expect(onSave).toHaveBeenCalled();
    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.level).toBe('volume');
    expect(body.parent_id).toBe('o1');
  });

  it('R3「＋章细纲」预填 parent=volume + level=chapter → POST body 含 level=chapter+parent_id', async () => {
    renderOutlineDialog({ initialLevel: 'chapter', initialParentId: 'v1' });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '第一章');
    expect((screen.getByTestId('library-create-level') as HTMLSelectElement).value).toBe('chapter');
    await user.click(screen.getByTestId('library-create-save'));
    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.level).toBe('chapter');
    expect(body.parent_id).toBe('v1');
  });

  it('R4「＋整本」预填 level=overall + parent=null → POST body 含 level=overall+parent_id null', async () => {
    renderOutlineDialog({ initialLevel: 'overall', initialParentId: null });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '主线规划');
    expect((screen.getByTestId('library-create-level') as HTMLSelectElement).value).toBe('overall');
    await user.click(screen.getByTestId('library-create-save'));
    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.level).toBe('overall');
    expect(body.parent_id).toBeNull();
  });

  it('R5 用户可切换 level（overall/volume/chapter 三选）', async () => {
    renderOutlineDialog({ initialLevel: 'chapter' });
    const user = userEvent.setup();
    const levelSelect = screen.getByTestId('library-create-level');
    await user.selectOptions(levelSelect, 'overall');
    expect((levelSelect as HTMLSelectElement).value).toBe('overall');
  });
});
