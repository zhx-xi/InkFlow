/** F48 新建/编辑关系表单（specs/f48-knowledge-graph/spec.md §5.4）
 * - 起点/终点：类型选择（六实体类型显示名）+ 实体选择（当前类型图谱节点名）
 * - 关系类型/描述：原生输入；提交 → onSubmit 六元组 + description
 *   （source_id/target_id = 实体 UUID = GraphNode.entity_id，非节点 id 字符串）
 */
import { useState, type FormEvent } from 'react';
import type { EntityType, GraphNode, KnowledgeRelation } from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';

export interface KnowledgeRelationFormData {
  source_type: EntityType;
  source_id: string;
  target_type: EntityType;
  target_id: string;
  relation_type: string;
  description: string;
}

/** 六实体类型顺序（与 library.tsx 六分类 tab 对齐） */
const ENTITY_TYPES: EntityType[] = ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin'];

const ENTITY_TYPE_KEYS: Record<EntityType, string> = {
  character: 'lib.knowledge.type.character',
  world: 'lib.knowledge.type.world',
  outline: 'lib.knowledge.type.outline',
  timeline: 'lib.knowledge.type.timeline',
  foreshadow: 'lib.knowledge.type.foreshadow',
  map_pin: 'lib.knowledge.type.map_pin',
};

export interface RelationFormProps {
  mode: 'create' | 'edit';
  /** edit 模式回填现值（六元组 + description） */
  initial?: KnowledgeRelation | null;
  /** 可选实体 = 图谱节点（source_id/target_id 用 entity_id） */
  entities: GraphNode[];
  onSubmit: (data: KnowledgeRelationFormData) => void;
  onCancel: () => void;
}

const selectCls =
  'h-9 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50';

export function RelationForm({ mode, initial, entities, onSubmit, onCancel }: RelationFormProps) {
  const { t } = useI18n();
  const [sourceType, setSourceType] = useState<EntityType>(initial?.source_type ?? 'character');
  const [sourceId, setSourceId] = useState(initial?.source_id ?? '');
  const [targetType, setTargetType] = useState<EntityType>(initial?.target_type ?? 'world');
  const [targetId, setTargetId] = useState(initial?.target_id ?? '');
  const [relationType, setRelationType] = useState(initial?.relation_type ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');

  const sourceEntities = entities.filter((n) => n.type === sourceType);
  const targetEntities = entities.filter((n) => n.type === targetType);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const relation = relationType.trim();
    if (!sourceId || !targetId || !relation) return;
    onSubmit({
      source_type: sourceType,
      source_id: sourceId,
      target_type: targetType,
      target_id: targetId,
      relation_type: relation,
      description: description.trim(),
    });
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <form
        data-testid="library-kg-relation-form"
        className="max-h-[90vh] w-[520px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {mode === 'edit' ? t('lib.knowledge.form.editTitle') : t('lib.knowledge.form.createTitle')}
        </h2>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.sourceType')}</span>
            <select
              data-testid="library-kg-form-source-type"
              aria-label={t('lib.knowledge.form.sourceType')}
              className={selectCls}
              value={sourceType}
              onChange={(e) => {
                setSourceType(e.target.value as EntityType);
                setSourceId('');
              }}
            >
              {ENTITY_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(ENTITY_TYPE_KEYS[type])}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.sourceEntity')}</span>
            <select
              data-testid="library-kg-form-source-entity"
              aria-label={t('lib.knowledge.form.sourceEntity')}
              className={selectCls}
              value={sourceId}
              disabled={sourceEntities.length === 0}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">{t('lib.knowledge.form.entityPlaceholder')}</option>
              {sourceEntities.map((n) => (
                <option key={n.id} value={n.entity_id}>
                  {n.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.targetType')}</span>
            <select
              data-testid="library-kg-form-target-type"
              aria-label={t('lib.knowledge.form.targetType')}
              className={selectCls}
              value={targetType}
              onChange={(e) => {
                setTargetType(e.target.value as EntityType);
                setTargetId('');
              }}
            >
              {ENTITY_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(ENTITY_TYPE_KEYS[type])}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.targetEntity')}</span>
            <select
              data-testid="library-kg-form-target-entity"
              aria-label={t('lib.knowledge.form.targetEntity')}
              className={selectCls}
              value={targetId}
              disabled={targetEntities.length === 0}
              onChange={(e) => setTargetId(e.target.value)}
            >
              <option value="">{t('lib.knowledge.form.entityPlaceholder')}</option>
              {targetEntities.map((n) => (
                <option key={n.id} value={n.entity_id}>
                  {n.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="mt-3 block">
          <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.relationType')}</span>
          <input
            data-testid="library-kg-form-relation-type"
            className="h-9 w-full rounded-md border border-line bg-surface px-3 text-[13px] text-ink transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg"
            value={relationType}
            placeholder={t('lib.knowledge.form.relationTypePlaceholder')}
            onChange={(e) => setRelationType(e.target.value)}
          />
        </label>
        <label className="mt-3 block">
          <span className="text-[12px] text-ink-2">{t('lib.knowledge.form.description')}</span>
          <input
            data-testid="library-kg-form-description"
            className="h-9 w-full rounded-md border border-line bg-surface px-3 text-[13px] text-ink transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg"
            value={description}
            placeholder={t('lib.knowledge.form.descriptionPlaceholder')}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="library-kg-form-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={onCancel}
          >
            {t('lib.create.cancel')}
          </button>
          <button
            type="submit"
            data-testid="library-kg-form-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            {t('lib.create.save')}
          </button>
        </div>
      </form>
    </div>
  );
}
