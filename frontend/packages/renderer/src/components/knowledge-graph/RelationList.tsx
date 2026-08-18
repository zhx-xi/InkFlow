/** F48 关系列表视图（specs/f48-knowledge-graph/spec.md §5.4：复用 F9 列表交互——筛选/编辑/删除）
 * - 每行显示：source 名 → label → target 名 + description（名称经图谱节点解析，缺省回退原始 id）
 * - 行内按钮：library-kg-rel-edit-<rid>（编辑）/ library-kg-rel-delete-<rid>（删除）
 */
import { Pencil, Trash2 } from 'lucide-react';
import type { EntityType, GraphNode, KnowledgeRelation } from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';

export interface RelationListProps {
  relations: KnowledgeRelation[];
  /** 图谱节点（名称解析：type + entity_id → name） */
  entities: GraphNode[];
  onEdit: (relation: KnowledgeRelation) => void;
  onDelete: (relation: KnowledgeRelation) => void;
}

export function RelationList({ relations, entities, onEdit, onDelete }: RelationListProps) {
  const { t } = useI18n();
  const nameOf = (type: EntityType, id: string): string =>
    entities.find((n) => n.type === type && n.entity_id === id)?.name ?? id;

  return (
    <div
      data-testid="library-kg-relation-list"
      className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
    >
      {relations.length === 0 ? (
        <div className="px-4 py-10 text-center text-[13px] text-ink-2">{t('lib.knowledge.list.empty')}</div>
      ) : (
        relations.map((r) => (
          <div key={r.id} className="group flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink">
            <div className="min-w-0 flex-1">
              <span className="font-medium">{nameOf(r.source_type, r.source_id)}</span>
              <span className="mx-1.5 text-ink-3">→</span>
              <span className="text-accent">{r.relation_type}</span>
              <span className="mx-1.5 text-ink-3">→</span>
              <span className="font-medium">{nameOf(r.target_type, r.target_id)}</span>
              {r.description ? <p className="mt-0.5 text-[12px] text-ink-2">{r.description}</p> : null}
            </div>
            <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                data-testid={`library-kg-rel-edit-${r.id}`}
                aria-label={`${t('lib.edit')} ${r.relation_type}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onEdit(r)}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`library-kg-rel-delete-${r.id}`}
                aria-label={`${t('lib.delete')} ${r.relation_type}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onDelete(r)}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
