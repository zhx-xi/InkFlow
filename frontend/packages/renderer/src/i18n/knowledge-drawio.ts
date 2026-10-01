/**
 * #1360：drawio（mxGraph XML）导入 / 导出文案域（zh/en）。
 *
 * 独立成文件而非写入 zh.ts / en.ts：后两者已贴 900 行护栏（ci_cd/check_file_length.py），
 * 新增键即触线；同 pagination.ts / foreshadow-filter.ts 先例。zh 为权威，两语 key 集必须一致。
 */
export const knowledgeDrawioZh: Record<string, string> = {
  'lib.knowledge.drawio.export': '导出 drawio',
  'lib.knowledge.drawio.import': '导入 drawio',
  'lib.knowledge.drawio.exported': '已保存到 {filename}',
  'lib.knowledge.drawio.importTitle': '导入 drawio 图谱',
  'lib.knowledge.drawio.modeMerge': '合并（跳过已存在）',
  'lib.knowledge.drawio.modeReplace': '替换全部既有关系',
  'lib.knowledge.drawio.replaceAck': '我了解这会删除本项目全部既有关系',
  'lib.knowledge.drawio.file': 'drawio 文件',
  'lib.knowledge.drawio.submit': '导入',
  'lib.knowledge.drawio.cancel': '取消',
  'lib.knowledge.drawio.result': '导入完成：新增 {imported} · 跳过 {skipped} · 失败 {failed}',
  'lib.knowledge.drawio.saveUnavailable': '当前环境无法写盘（缺少文件通道）',
  'lib.knowledge.drawio.loading': '导入中…',
};

export const knowledgeDrawioEn: Record<string, string> = {
  'lib.knowledge.drawio.export': 'Export drawio',
  'lib.knowledge.drawio.import': 'Import drawio',
  'lib.knowledge.drawio.exported': 'Saved to {filename}',
  'lib.knowledge.drawio.importTitle': 'Import drawio graph',
  'lib.knowledge.drawio.modeMerge': 'Merge (skip existing)',
  'lib.knowledge.drawio.modeReplace': 'Replace all existing relations',
  'lib.knowledge.drawio.replaceAck': 'I understand this will delete all existing relations in this project',
  'lib.knowledge.drawio.file': 'drawio file',
  'lib.knowledge.drawio.submit': 'Import',
  'lib.knowledge.drawio.cancel': 'Cancel',
  'lib.knowledge.drawio.result': 'Imported {imported} · skipped {skipped} · failed {failed}',
  'lib.knowledge.drawio.saveUnavailable': 'Cannot save a file in this environment (no file channel)',
  'lib.knowledge.drawio.loading': 'Importing…',
};
