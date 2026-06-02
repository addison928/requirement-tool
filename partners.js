// 大区配置表 — 每个 token 对应唯一大区身份
// 生产环境中 token 应由后端生成并存储，此处为前端 mock
const PARTNERS = {
  'HB_a3f9b2c1': { id: 'HB', name: '华北大区',   flag: '🏔️', prefix: 'HB', lang: 'zh' },
  'HN_b7e1d4a2': { id: 'HN', name: '华南大区',   flag: '🌴', prefix: 'HN', lang: 'zh' },
  'HD_c2f8e3b5': { id: 'HD', name: '华东大区',   flag: '🌆', prefix: 'HD', lang: 'zh' },
  'HZ_d5a3c9f1': { id: 'HZ', name: '华中大区',   flag: '🌾', prefix: 'HZ', lang: 'zh' },
  'XB_e9b2f7d4': { id: 'XB', name: '西部大区',   flag: '🏜️', prefix: 'XB', lang: 'zh' },
};

function resolvePartner() {
  const token = new URLSearchParams(location.search).get('token');
  if (!token || !PARTNERS[token]) return null;
  return { token, ...PARTNERS[token] };
}
