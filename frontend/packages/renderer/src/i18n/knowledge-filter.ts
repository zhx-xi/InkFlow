/**
 * #1568：知识图谱筛选「双入口 / 三态」补充文案域（zh/en）。
 *
 * 独立成文件而非写入 zh.ts / en.ts：后两者已贴 900 行护栏（ci_cd/check_file_length.py），
 * 新增键即触线；同 pagination.ts / knowledge-drawio.ts 先例。zh 为权威，两语 key 集必须一致。
 *
 * 说明：`lib.knowledge.filter.clear` **不在此处**——该键早已存在于 zh.ts / en.ts，
 * 本次只把它的**值**由「清除筛选」改为「全选」（语义一直是全选，旧名名实不符，见 #1568）。
 */
export const knowledgeFilterZh: Record<string, string> = {
  'lib.knowledge.filter.cancelAll': '全部取消',
  'lib.knowledge.filter.none': '无',
};

export const knowledgeFilterEn: Record<string, string> = {
  'lib.knowledge.filter.cancelAll': 'Clear all',
  'lib.knowledge.filter.none': 'None',
};
