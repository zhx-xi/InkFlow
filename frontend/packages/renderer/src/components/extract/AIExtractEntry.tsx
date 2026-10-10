import { useState } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { useProjectStore } from '../../stores/project';
import { AIExtractDialog, type ExtractKind } from './AIExtractDialog';

/** #1566：资料库分类 → 弹框默认提取类型（未登记分类 = 无来源页上下文 → 回落 character） */
const KIND_BY_CAT: Record<string, ExtractKind> = {
  characters: 'character',
  world: 'world',
  timeline: 'timeline',
  foreshadow: 'foreshadowing',
  knowledge: 'knowledgeGraph',
};

/** #652：「AI 提取」入口（设定库工具栏按钮 + 弹窗，自包含）。
 *  仅已选项目（currentProjectId 非 null）时渲染按钮；弹窗打开拉取章节/运行记录。
 *  从 library.tsx 拆出以符合 900 行护栏（入口与弹窗是内聚单元）。
 *  #1566：cat = 当前资料库分类 → 弹框默认类型随来源页（未登记分类回落 character）。 */
export function AIExtractEntry({ cat }: { cat?: string }) {
  const { t } = useI18n();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const [extractOpen, setExtractOpen] = useState(false);

  if (currentProjectId === null) return null;

  return (
    <>
      <button
        type="button"
        data-testid="extract-entry-lib"
        className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        onClick={() => setExtractOpen(true)}
      >
        {t('extract.title')}
      </button>
      <AIExtractDialog
        open={extractOpen}
        onClose={() => setExtractOpen(false)}
        projectId={currentProjectId}
        initialKind={cat ? KIND_BY_CAT[cat] : undefined}
      />
    </>
  );
}
