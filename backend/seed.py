"""Seed the database with mock data from the original frontend prototype.
Run once: python seed.py
Safe to re-run — uses INSERT OR IGNORE so existing rows are not touched.
"""
import json
from database import init_db, get_conn

PARTNERS = [
    {'token': 'TH_a3f9b2c1', 'country_id': 'TH', 'flag': '🇹🇭', 'country_name': '泰国',    'name': 'TH-Partner', 'lang': 'th', 'tier': 'strategic'},
    {'token': 'ID_b7e1d4a2', 'country_id': 'ID', 'flag': '🇮🇩', 'country_name': '印尼',    'name': 'ID-Partner', 'lang': 'id', 'tier': 'important'},
    {'token': 'IT_c2f8e3b5', 'country_id': 'IT', 'flag': '🇮🇹', 'country_name': '意大利',  'name': 'IT-Partner', 'lang': 'it', 'tier': 'important'},
    {'token': 'KH_d5a3c9f1', 'country_id': 'KH', 'flag': '🇰🇭', 'country_name': '柬埔寨',  'name': 'KH-Partner', 'lang': 'km', 'tier': 'normal'},
    {'token': 'MY_e9b2f7d4', 'country_id': 'MY', 'flag': '🇲🇾', 'country_name': '马来西亚', 'name': 'MY-Partner', 'lang': 'en', 'tier': 'normal'},
    {'token': 'FR_f1a6e8d3', 'country_id': 'FR', 'flag': '🇫🇷', 'country_name': '法国',    'name': 'FR-Partner', 'lang': 'fr', 'tier': 'normal'},
]

TICKETS = [
    {'id':'TH-0231','flag':'🇹🇭','partner_name':'TH-Partner','country_id':'TH','text':'ต้องการปรับแต่งสลิปใบเสร็จ ใส่โลโก้ร้านและ QR Code ลิงก์ LINE OA','merchant':'BangkokBistro','impact':'high','scenes':['收银'],'biz_type':'restaurant','time':'2026-05-20 14:32','status':'merged','cluster_id':'#042','lang':'Thai','attachments':[],'manual':0},
    {'id':'TH-0232','flag':'🇹🇭','partner_name':'TH-Partner','country_id':'TH','text':'ต้องการรายงานยอดขายแยกตามพนักงาน เพื่อคำนวณคอมมิชชั่น','merchant':'ChiangMaiCafe','impact':'mid','scenes':['报表'],'biz_type':'restaurant','time':'2026-05-21 09:15','status':'pending','cluster_id':None,'lang':'Thai','attachments':[],'manual':0},
    {'id':'ID-0118','flag':'🇮🇩','partner_name':'ID-Partner','country_id':'ID','text':'Perlu fitur cetak struk dengan logo toko dan barcode produk untuk outlet retail','merchant':'JakartaMart','impact':'high','scenes':['收银'],'biz_type':'retail','time':'2026-05-19 11:20','status':'merged','cluster_id':'#042','lang':'Indonesian','attachments':[],'manual':0},
    {'id':'IT-0089','flag':'🇮🇹','partner_name':'IT-Partner','country_id':'IT','text':'Necessità di stampa scontrino personalizzato con logo e QR code per fidelizzazione','merchant':'RomaPizzeria','impact':'high','scenes':['收银'],'biz_type':'restaurant','time':'2026-05-18 16:45','status':'merged','cluster_id':'#042','lang':'Italian','attachments':[],'manual':0},
    {'id':'ID-0119','flag':'🇮🇩','partner_name':'ID-Partner','country_id':'ID','text':'Butuh integrasi dengan sistem loyalty poin pelanggan yang sudah ada di aplikasi kami','merchant':'SurabayaStore','impact':'mid','scenes':['会员'],'biz_type':'retail','time':'2026-05-20 08:30','status':'scheduled','cluster_id':'#037','lang':'Indonesian','attachments':[],'manual':0},
    {'id':'KH-0045','flag':'🇰🇭','partner_name':'KH-Partner','country_id':'KH','text':'ត្រូវការប្រព័ន្ធគ្រប់គ្រងស្តុកទំនិញ ដើម្បីដឹងពីបរិមាណទំនិញដែលនៅសល់','merchant':'PhnomPenhShop','impact':'low','scenes':['库存'],'biz_type':'retail','time':'2026-05-17 13:00','status':'pending','cluster_id':None,'lang':'Khmer','attachments':[],'manual':0},
    {'id':'MY-0067','flag':'🇲🇾','partner_name':'MY-Partner','country_id':'MY','text':'Need kitchen display system integration to show order queue for kitchen staff','merchant':'KLNoodleHouse','impact':'mid','scenes':['厨显'],'biz_type':'restaurant','time':'2026-05-22 10:10','status':'pending','cluster_id':None,'lang':'English','attachments':[],'manual':0},
    {'id':'FR-0033','flag':'🇫🇷','partner_name':'FR-Partner','country_id':'FR','text':'Besoin d\'un rapport de ventes par catégorie de produits pour analyse mensuelle','merchant':'ParisBoulangerie','impact':'mid','scenes':['报表'],'biz_type':'restaurant','time':'2026-05-21 15:55','status':'pending','cluster_id':None,'lang':'French','attachments':[],'manual':0},
]

CLUSTERS = [
    {'id':'#042','score':87,'urgent':1,'summary':'支持打印自定义小票模板（Logo + 二维码）','layer':'saas','impact':'high','source_ids':['TH','ID','IT'],'partners':['TH-Partner','ID-Partner','IT-Partner'],'count':5,'periods':2,'status':'merged','ai_summary':'多个国家商户反馈，现有小票打印功能无法满足品牌化需求。主要诉求：①支持上传门店 Logo 并印在小票顶部；②支持自定义二维码（关联 LINE OA、Instagram 或自有会员小程序）；③泰国商户还要求支持泰文字体。影响集中在餐饮和零售场景的收银环节，属于 SaaS 层可配置能力。','ticket_ids':['TH-0231','ID-0118','IT-0089']},
    {'id':'#037','score':72,'urgent':0,'summary':'会员积分系统与第三方 App 打通','layer':'platform','impact':'mid','source_ids':['ID','MY'],'partners':['ID-Partner','MY-Partner'],'count':3,'periods':2,'status':'scheduled','ai_summary':'印尼和马来西亚服务商均反映商户已有自建会员体系，希望与 SaaS 收银系统双向同步积分。核心需求：①收银时自动识别会员（扫码/手机号）；②消费后实时更新积分到第三方系统；③支持 Webhook 或 Open API 方式对接。属于平台层能力，需要统一 API 规范。','ticket_ids':['ID-0119']},
    {'id':'#031','score':58,'urgent':0,'summary':'营业额报表支持按员工/班次拆分','layer':'saas','impact':'mid','source_ids':['TH','FR'],'partners':['TH-Partner','FR-Partner'],'count':2,'periods':1,'status':'pending','ai_summary':'泰国餐饮商户和法国面包店均需要按员工或班次维度拆分营业数据，用于计算绩效奖金和交接班对账。当前报表仅支持门店级汇总，缺少人员维度。','ticket_ids':['TH-0232','FR-0033']},
    {'id':'#028','score':45,'urgent':0,'summary':'厨显系统集成（KDS）','layer':'saas','impact':'mid','source_ids':['MY'],'partners':['MY-Partner'],'count':2,'periods':1,'status':'pending','ai_summary':'马来西亚餐饮商户需要将点单信息实时推送至厨房显示屏，支持按品类分区显示、出餐确认和催单提醒功能。','ticket_ids':['MY-0067']},
    {'id':'#019','score':31,'urgent':0,'summary':'库存预警与自动补货建议','layer':'saas','impact':'low','source_ids':['KH'],'partners':['KH-Partner'],'count':2,'periods':1,'status':'pending','ai_summary':'柬埔寨零售商户希望系统能在库存低于阈值时发出预警，并根据历史销量自动生成补货建议单。','ticket_ids':['KH-0045']},
    {'id':'#011','score':18,'urgent':0,'summary':'多语言收银界面切换','layer':'platform','impact':'low','source_ids':['KH','MY'],'partners':['KH-Partner','MY-Partner'],'count':1,'periods':1,'status':'live','ai_summary':'东南亚门店员工多语言混用，希望收银界面支持一键切换语言，无需重新登录。','ticket_ids':[]},
]

SCORING_CONFIG = {
    'impactWeight': {'high': 3.0, 'mid': 2.0, 'low': 1.0},
    'countryWeight': {'TH': 1.5, 'ID': 1.3, 'IT': 1.2, 'MY': 1.1, 'KH': 1.0, 'FR': 1.0},
    'partnerTier': {'TH-Partner': 'strategic', 'ID-Partner': 'important', 'IT-Partner': 'important', 'KH-Partner': 'normal', 'MY-Partner': 'normal', 'FR-Partner': 'normal'},
    'tierWeight': {'strategic': 2.0, 'important': 1.5, 'normal': 1.0},
    'periodCoeff': [1.0, 1.3, 1.6],
}


def seed():
    init_db()
    with get_conn() as conn:
        for p in PARTNERS:
            conn.execute(
                'INSERT INTO partners VALUES (?,?,?,?,?,?,?) ON CONFLICT (token) DO NOTHING',
                (p['token'], p['country_id'], p['flag'], p['country_name'], p['name'], p['lang'], p['tier'])
            )

        for t in TICKETS:
            conn.execute(
                '''INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING''',
                (t['id'], t['flag'], t['partner_name'], t['country_id'], t['text'],
                 t['merchant'], t['impact'], json.dumps(t['scenes'], ensure_ascii=False),
                 t.get('biz_type'), t['time'], t['status'], t['cluster_id'],
                 json.dumps(t.get('attachments', []), ensure_ascii=False), t.get('manual', 0), t['lang'])
            )

        for c in CLUSTERS:
            conn.execute(
                '''INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING''',
                (c['id'], c['score'], c['urgent'], c['summary'], c['layer'], c['impact'],
                 json.dumps(c['source_ids'], ensure_ascii=False),
                 json.dumps(c['partners'], ensure_ascii=False),
                 c['count'], c['periods'], c['status'], c['ai_summary'])
            )
            for tid in c.get('ticket_ids', []):
                conn.execute(
                    'INSERT INTO cluster_tickets VALUES (?,?) ON CONFLICT DO NOTHING',
                    (c['id'], tid)
                )

        existing = conn.execute('SELECT COUNT(*) FROM scoring_config').fetchone()[0]
        if existing == 0:
            conn.execute(
                'INSERT INTO scoring_config (config_json) VALUES (?)',
                (json.dumps(SCORING_CONFIG, ensure_ascii=False),)
            )

    print('✅ Seed complete.')


if __name__ == '__main__':
    seed()
