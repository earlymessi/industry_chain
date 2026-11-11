const PRODUCTION_SLUGS = new Set([
  'dashboard',
  'database',
  'aps',
  'compare',
  'assistant',
  'reports',
  'energy',
  'health',
  'logistics',
  'staffing',
  'materials',
])

export function productionPath(slug) {
  return `/home/production/${slug}`
}

/** 将旧版 /dashboard 等路径规范为 Hub 嵌套生产路径 */
export function normalizeProductionPath(path) {
  if (!path || typeof path !== 'string') return path
  if (path.startsWith('/home/production/')) return path
  const slug = path.replace(/^\//, '')
  if (PRODUCTION_SLUGS.has(slug)) return productionPath(slug)
  return path
}
