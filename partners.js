// 服务商配置表 — 每个 token 对应唯一服务商身份
// 生产环境中 token 应由后端生成并存储，此处为前端 mock
const PARTNERS = {
  'TH_a3f9b2c1': { id: 'TH', name: 'Thailand · TH-Partner',   flag: '🇹🇭', prefix: 'TH', lang: 'th' },
  'ID_b7e1d4a2': { id: 'ID', name: 'Indonesia · ID-Partner',   flag: '🇮🇩', prefix: 'ID', lang: 'id' },
  'IT_c2f8e3b5': { id: 'IT', name: 'Italy · IT-Partner',       flag: '🇮🇹', prefix: 'IT', lang: 'it' },
  'KH_d5a3c9f1': { id: 'KH', name: 'Cambodia · KH-Partner',   flag: '🇰🇭', prefix: 'KH', lang: 'km' },
  'MY_e9b2f7d4': { id: 'MY', name: 'Malaysia · MY-Partner',    flag: '🇲🇾', prefix: 'MY', lang: 'en' },
  'FR_f1a6e8d3': { id: 'FR', name: 'France · FR-Partner',      flag: '🇫🇷', prefix: 'FR', lang: 'fr' },
};

function resolvePartner() {
  const token = new URLSearchParams(location.search).get('token');
  if (!token || !PARTNERS[token]) return null;
  return { token, ...PARTNERS[token] };
}
