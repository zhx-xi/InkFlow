/**
 * #650/#651 角色详情面板宿主：持有 detailItem 状态并挂载 CharacterDetailPanel。
 * 入口：library.tsx 角色行点名字 → ref.openDetail(item)；面板关闭 → onClose；
 * 切 tab/切项目 → ref.reset() 卸载（与 #650 既有重置语义一致）。
 * item 优先取 items 内最新对象（列表刷新后 group_id 等字段同步），找不到时回退打开时对象。
 */
import { useImperativeHandle, useState } from 'react';
import type { Ref } from 'react';
import { CharacterDetailPanel } from './CharacterDetailPanel';
import type { LibraryItemDTO } from './LibraryCreateDialog';

export interface LibraryCharacterDetailHandle {
  /** 打开详情面板（角色行点名字入口） */
  openDetail: (item: LibraryItemDTO) => void;
  /** 关闭面板（CharacterDetailPanel onClose） */
  close: () => void;
  /** 卸载面板（切分类 / 切项目时调用） */
  reset: () => void;
}

interface LibraryCharacterDetailProps {
  ref: Ref<LibraryCharacterDetailHandle>;
  currentProjectId: string | null;
  items: LibraryItemDTO[];
  reload: () => void;
}

export function LibraryCharacterDetail({
  ref,
  currentProjectId,
  items,
  reload,
}: LibraryCharacterDetailProps) {
  const [detailItem, setDetailItem] = useState<LibraryItemDTO | null>(null);
  useImperativeHandle(ref, () => ({
    openDetail: (item) => setDetailItem(item),
    close: () => setDetailItem(null),
    reset: () => setDetailItem(null),
  }));

  return (
    <>
      {currentProjectId !== null && detailItem && (
        <CharacterDetailPanel
          item={items.find((i) => String(i.id) === String(detailItem.id)) ?? detailItem}
          projectId={currentProjectId}
          onClose={() => setDetailItem(null)}
          onUpdated={reload}
        />
      )}
    </>
  );
}
