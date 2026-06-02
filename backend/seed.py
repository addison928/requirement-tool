"""Seed the database with mock data from the original frontend prototype.
Run once: python seed.py
Safe to re-run — uses INSERT OR IGNORE so existing rows are not touched.
"""
import json
from database import init_db, get_conn

PARTNERS = [
    {'token': 'HB_a3f9b2c1', 'region_id': 'HB', 'region_name': '华北',    'name': '华北大区', 'lang': 'zh', 'tier': 'strategic', 'flag': '🏔️'},
    {'token': 'HN_b7e1d4a2', 'region_id': 'HN', 'region_name': '华南',    'name': '华南大区', 'lang': 'zh', 'tier': 'important', 'flag': '🌴'},
    {'token': 'HD_c2f8e3b5', 'region_id': 'HD', 'region_name': '华东',    'name': '华东大区', 'lang': 'zh', 'tier': 'important', 'flag': '🌆'},
    {'token': 'HZ_d5a3c9f1', 'region_id': 'HZ', 'region_name': '华中',    'name': '华中大区', 'lang': 'zh', 'tier': 'normal', 'flag': '🌾'},
    {'token': 'XB_e9b2f7d4', 'region_id': 'XB', 'region_name': '西部',    'name': '西部大区', 'lang': 'zh', 'tier': 'normal', 'flag': '🏜️'},
]

TICKETS = [
    # ── 商品场景 ──
    {'id':'HB-0231','partner_name':'华北大区','region_id':'HB','text':'需要支持鲜食商品（便当、饭团、三明治等）效期管理，临期2小时自动降价销售并推送提醒到店长手机','merchant':'北京朝阳7-Eleven','impact':'high','scenes':['商品场景'],'biz_type':'convenience','time':'2026-05-20 14:32','status':'merged','cluster_id':'#042','lang':'zh','attachments':[],'manual':0},
    {'id':'HN-0120','partner_name':'华南大区','region_id':'HN','text':'需要支持即食商品（关东煮、烤肠、包子等）的加热计时管理，超时自动提醒废弃并记录损耗','merchant':'广州白云全家便利','impact':'mid','scenes':['商品场景'],'biz_type':'convenience','time':'2026-05-22 11:40','status':'merged','cluster_id':'#052','lang':'zh','attachments':[],'manual':0},
    {'id':'HD-0033','partner_name':'华东大区','region_id':'HD','text':'需要按商品类别和单品的日/周/月销售分析报表，用于指导选品优化和货架陈列调整','merchant':'杭州西湖喜士多','impact':'mid','scenes':['商品场景'],'biz_type':'convenience','time':'2026-05-21 15:55','status':'merged','cluster_id':'#031','lang':'zh','attachments':[],'manual':0},
    # ── 智能补货场景 ──
    {'id':'HZ-0045','partner_name':'华中大区','region_id':'HZ','text':'需要库存管理系统，能够实时查看各商品库存余量并在低于阈值时预警，根据历史销量自动生成补货建议单','merchant':'武汉洪山today便利','impact':'high','scenes':['智能补货场景'],'biz_type':'convenience','time':'2026-05-17 13:00','status':'merged','cluster_id':'#019','lang':'zh','attachments':[],'manual':0},
    {'id':'XB-0067','partner_name':'西部大区','region_id':'XB','text':'需要支持冷柜温度监控预警功能，冷柜温度异常时自动推送通知到店长手机，避免食品安全风险','merchant':'成都锦里红旗连锁','impact':'mid','scenes':['智能补货场景'],'biz_type':'convenience','time':'2026-05-22 10:10','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
    {'id':'HB-0232','partner_name':'华北大区','region_id':'HB','text':'需要支持基于天气和节假日的智能销量预测，提前3天自动生成补货计划，减少缺货率和过度囤货','merchant':'北京海淀全家便利','impact':'mid','scenes':['智能补货场景'],'biz_type':'convenience','time':'2026-05-21 09:15','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
    # ── 采购入库 ──
    {'id':'HD-0089','partner_name':'华东大区','region_id':'HD','text':'需要支持供应商送货验收功能，扫码核对送货单与采购订单，自动登记入库并更新库存','merchant':'上海静安便利蜂','impact':'mid','scenes':['采购入库'],'biz_type':'convenience','time':'2026-05-18 16:45','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
    {'id':'HN-0118','partner_name':'华南大区','region_id':'HN','text':'需要支持采购订单在线审批流程，区域经理可在手机上审批下属门店的采购申请，加快补货效率','merchant':'深圳福田罗森便利','impact':'mid','scenes':['采购入库'],'biz_type':'convenience','time':'2026-05-19 11:20','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
    # ── 店内操作 ──
    {'id':'XB-0068','partner_name':'西部大区','region_id':'XB','text':'需要支持电子价签联动功能，商品信息变更时自动同步电子价签显示最新价格和促销信息','merchant':'西安雁塔便利蜂','impact':'high','scenes':['店内操作'],'biz_type':'convenience','time':'2026-05-23 09:05','status':'merged','cluster_id':'#028','lang':'zh','attachments':[],'manual':0},
    {'id':'HN-0119','partner_name':'华南大区','region_id':'HN','text':'需要支持店内盘点功能，员工用手机扫码即可完成货架盘点，自动生成差异报表并同步库存数据','merchant':'广州天河美宜佳','impact':'mid','scenes':['店内操作'],'biz_type':'convenience','time':'2026-05-20 08:30','status':'scheduled','cluster_id':'#037','lang':'zh','attachments':[],'manual':0},
    # ── 店内POS ──
    {'id':'XB-0069','partner_name':'西部大区','region_id':'XB','text':'需要支持自助收银机扫码支付功能，减少排队等候时间，高峰期自动分流到自助通道','merchant':'成都武侯红旗连锁','impact':'high','scenes':['店内POS'],'biz_type':'convenience','time':'2026-05-23 10:30','status':'merged','cluster_id':'#011','lang':'zh','attachments':[],'manual':0},
    {'id':'HB-0233','partner_name':'华北大区','region_id':'HB','text':'需要收银系统支持微信、支付宝、银联等多种支付方式聚合，一笔交易可组合多种支付','merchant':'北京东城7-Eleven','impact':'mid','scenes':['店内POS'],'biz_type':'convenience','time':'2026-05-24 08:20','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
    # ── O2O线上销售 ──
    {'id':'HD-0090','partner_name':'华东大区','region_id':'HD','text':'需要支持外卖平台（美团、饿了么）订单自动接入收银系统，统一管理线上线下订单，避免漏单','merchant':'上海浦东便利蜂','impact':'high','scenes':['O2O线上销售'],'biz_type':'convenience','time':'2026-05-24 09:45','status':'merged','cluster_id':'#044','lang':'zh','attachments':[],'manual':0},
    {'id':'HZ-0046','partner_name':'华中大区','region_id':'HZ','text':'需要支持小程序自营商城功能，老客户可通过微信小程序下单自提或外卖配送，积累私域流量','merchant':'武汉光谷today便利','impact':'mid','scenes':['O2O线上销售'],'biz_type':'convenience','time':'2026-05-24 11:00','status':'pending','cluster_id':None,'lang':'zh','attachments':[],'manual':0},
]

CLUSTERS = [
    # ── 商品场景 ──
    {'id':'#042','score':87,'urgent':1,'summary':'鲜食效期管理与临期自动打折','layer':'saas','impact':'high','source_ids':['HB','HN'],'partners':['华北大区','华南大区'],'count':3,'periods':2,'status':'merged','ai_summary':'华北和华南便利店反馈鲜食商品管理需求：便当、饭团等临期商品需要自动降价促销减少损耗；关东煮、烤肠等即食商品需要加热计时管理，超时自动提醒废弃。核心诉求是降低鲜食损耗率，属于便利店商品场景的核心运营需求。','ticket_ids':['HB-0231','HN-0120']},
    {'id':'#031','score':58,'urgent':0,'summary':'商品销售分析与选品优化报表','layer':'saas','impact':'mid','source_ids':['HD'],'partners':['华东大区'],'count':2,'periods':1,'status':'merged','ai_summary':'华东便利店需要按商品类别和单品维度拆分销售数据，用于指导选品决策和货架陈列优化。当前报表仅支持门店级汇总，缺少品类细分。','ticket_ids':['HD-0033']},
    # ── 智能补货场景 ──
    {'id':'#019','score':85,'urgent':1,'summary':'库存预警与智能补货建议','layer':'saas','impact':'high','source_ids':['HZ','XB','HB'],'partners':['华中大区','西部大区','华北大区'],'count':5,'periods':2,'status':'merged','ai_summary':'多个区域便利店反馈库存管理需求：华中门店需要库存低于阈值时预警并自动生成补货单；西部门店需要冷柜温度监控避免食品安全风险；华北门店希望基于天气和节假日预测销量提前补货。核心诉求是减少缺货率、降低损耗。','ticket_ids':['HZ-0045','XB-0067','HB-0232']},
    # ── 店内操作 ──
    {'id':'#028','score':72,'urgent':0,'summary':'电子价签联动与店内扫码盘点','layer':'saas','impact':'high','source_ids':['XB','HN'],'partners':['西部大区','华南大区'],'count':3,'periods':2,'status':'scheduled','ai_summary':'西部和华南便利店反馈店内操作效率需求：商品信息变更时需自动同步电子价签；门店需支持手机扫码盘点自动生成差异报表。核心诉求是降低人工操作成本和出错率。','ticket_ids':['XB-0068','HN-0119']},
    # ── 店内POS ──
    {'id':'#011','score':78,'urgent':1,'summary':'自助收银与聚合支付','layer':'saas','impact':'high','source_ids':['XB','HB'],'partners':['西部大区','华北大区'],'count':4,'periods':2,'status':'scheduled','ai_summary':'西部和华北便利店反馈收银效率需求：需要自助收银机分流高峰客流；收银系统需支持微信、支付宝、银联等聚合支付。核心诉求是提升收银效率和支付体验。','ticket_ids':['XB-0069','HB-0233']},
    # ── O2O线上销售 ──
    {'id':'#044','score':80,'urgent':1,'summary':'外卖平台对接与小程序自营商城','layer':'platform','impact':'high','source_ids':['HD','HZ'],'partners':['华东大区','华中大区'],'count':3,'periods':2,'status':'merged','ai_summary':'华东和华中便利店反馈线上销售需求：需要美团、饿了么等外卖平台订单自动接入收银系统统一管理；需要支持微信小程序自营商城积累私域流量。核心诉求是拓展线上渠道、提升门店营收。','ticket_ids':['HD-0090','HZ-0046']},
    # ── 采购入库 ──
    {'id':'#037','score':55,'urgent':0,'summary':'供应商送货验收与采购在线审批','layer':'saas','impact':'mid','source_ids':['HD','HN'],'partners':['华东大区','华南大区'],'count':3,'periods':1,'status':'pending','ai_summary':'华东和华南便利店反馈采购入库效率需求：需要扫码验收送货单自动登记入库；需要区域经理手机端在线审批采购申请，加快门店补货效率。','ticket_ids':['HD-0089','HN-0118']},
]

SCORING_CONFIG = {
    'impactWeight': {'high': 3.0, 'mid': 2.0, 'low': 1.0},
    'regionWeight': {'HB': 1.5, 'HN': 1.3, 'HD': 1.2, 'HZ': 1.1, 'XB': 1.0},
    'partnerTier': {'华北大区': 'strategic', '华南大区': 'important', '华东大区': 'important', '华中大区': 'normal', '西部大区': 'normal'},
    'tierWeight': {'strategic': 2.0, 'important': 1.5, 'normal': 1.0},
    'periodCoeff': [1.0, 1.3, 1.6],
}


def seed():
    init_db()
    with get_conn() as conn:
        for p in PARTNERS:
            conn.execute(
                'INSERT INTO partners (token, region_id, region_name, name, lang, tier, flag) VALUES (?,?,?,?,?,?,?) ON CONFLICT (token) DO UPDATE SET flag=excluded.flag, name=excluded.name, region_name=excluded.region_name, tier=excluded.tier',
                (p['token'], p['region_id'], p['region_name'], p['name'], p['lang'], p['tier'], p['flag'])
            )

        for t in TICKETS:
            conn.execute(
                '''INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING''',
                (t['id'], t['partner_name'], t['region_id'], t['text'],
                 t['merchant'], t['impact'], json.dumps(t['scenes'], ensure_ascii=False),
                 t.get('biz_type'), t['time'], t['status'], t['cluster_id'],
                 json.dumps(t.get('attachments', []), ensure_ascii=False), t.get('manual', 0), t['lang'],
                 t.get('user_summary', ''))
            )

        for c in CLUSTERS:
            conn.execute(
                '''INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (id) DO NOTHING''',
                (c['id'], c['score'], c['urgent'], c['summary'], c['layer'], c['impact'],
                 json.dumps(c['source_ids'], ensure_ascii=False),
                 json.dumps(c['partners'], ensure_ascii=False),
                 c['count'], c['periods'], c['status'], c['ai_summary'],
                 json.dumps(c.get('related_saas', []), ensure_ascii=False))
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
