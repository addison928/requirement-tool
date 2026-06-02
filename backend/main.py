from dotenv import load_dotenv
load_dotenv('../.env')  # project root
load_dotenv()  # backend dir fallback

import json
import os
import random
import re
import string
import sys
from datetime import datetime, timezone, timedelta

_TZ_CST = timezone(timedelta(hours=8))
from typing import Optional

# Force UTF-8 stdout/stderr so non-ASCII content doesn't break on macOS
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from openai import OpenAI
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import init_db, get_conn

app = FastAPI(title='Requirement Tool API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def startup():
    try:
        init_db()
        print('✅ Database initialized successfully', flush=True)
    except Exception as e:
        print(f'❌ Database init failed: {e}', flush=True)


@app.get('/api/health')
def health():
    import os
    db_url = os.environ.get('DATABASE_URL', '')
    try:
        with get_conn() as conn:
            conn.execute('SELECT 1').fetchone()
        db_status = 'ok'
    except Exception as ex:
        db_status = str(ex)[:200]
    return {
        'status': 'ok',
        'db': db_status,
        'db_url_set': bool(db_url),
        'db_url_prefix': db_url[:30] if db_url else '',
        'tz_now': datetime.now(_TZ_CST).strftime('%Y-%m-%d %H:%M %Z'),
    }


# ── Helpers ────────────────────────────────────────────────────────────────

def row_to_dict(row):
    return dict(row) if row else None


def parse_json_field(val, default):
    if val is None:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


def ticket_row(row):
    d = row_to_dict(row)
    d['scenes'] = parse_json_field(d.get('scenes'), [])
    d['attachments'] = parse_json_field(d.get('attachments'), [])
    d['manual'] = bool(d.get('manual', 0))
    d['user_summary'] = d.get('user_summary', '') or ''
    return d


def cluster_row(row):
    d = row_to_dict(row)
    d['source_ids'] = parse_json_field(d.get('source_ids'), [])
    d['partners'] = parse_json_field(d.get('partners'), [])
    d['related_saas'] = parse_json_field(d.get('related_saas'), [])
    d['urgent'] = bool(d.get('urgent', 0))
    # attach tickets
    with get_conn() as conn:
        tids = [r['ticket_id'] for r in conn.execute(
            'SELECT ticket_id FROM cluster_tickets WHERE cluster_id=?', (d['id'],)
        ).fetchall()]
        items = []
        for tid in tids:
            t = conn.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
            if t:
                items.append(ticket_row(t))
    d['items'] = items
    return d


def generate_token(region_id: str) -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f'{region_id}_{suffix}'


def generate_ticket_id(region_id: str) -> str:
    with get_conn() as conn:
        for _ in range(20):
            tid = f'{region_id}-{random.randint(1000, 9999)}'
            exists = conn.execute('SELECT 1 FROM tickets WHERE id=?', (tid,)).fetchone()
            if not exists:
                return tid
    raise RuntimeError('Could not generate unique ticket ID')


# ── Stats ───────────────────────────────────────────────────────────────────

@app.get('/api/stats')
def get_stats():
    with get_conn() as conn:
        total_tickets = conn.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
        total_clusters = conn.execute('SELECT COUNT(*) FROM clusters').fetchone()[0]
        by_region = conn.execute(
            'SELECT region_id, COUNT(*) as cnt FROM tickets GROUP BY region_id ORDER BY cnt DESC'
        ).fetchall()
        by_layer = conn.execute(
            'SELECT layer, COUNT(*) as cnt FROM clusters GROUP BY layer'
        ).fetchall()
    return {
        'total_tickets': total_tickets,
        'total_clusters': total_clusters,
        'by_region': [dict(r) for r in by_region],
        'by_layer': [dict(r) for r in by_layer],
    }


# ── Partners ────────────────────────────────────────────────────────────────

class PartnerIn(BaseModel):
    region_id: str
    region_name: str
    name: str
    lang: str = 'zh'
    tier: str = 'normal'
    flag: str = ''


@app.get('/api/partners')
def list_partners():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM partners').fetchall()
    return [row_to_dict(r) for r in rows]


@app.post('/api/partners', status_code=201)
def create_partner(body: PartnerIn):
    token = generate_token(body.region_id.upper())
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO partners VALUES (?,?,?,?,?,?,?)',
            (token, body.region_id.upper(), body.region_name,
             body.name, body.lang, body.tier, body.flag)
        )
    return {'token': token, **body.dict(), 'region_id': body.region_id.upper()}


@app.put('/api/partners/{token}')
def update_partner(token: str, body: PartnerIn):
    with get_conn() as conn:
        cur = conn.execute(
            '''UPDATE partners SET region_id=?, region_name=?, name=?, lang=?, tier=?, flag=?
               WHERE token=?''',
            (body.region_id.upper(), body.region_name,
             body.name, body.lang, body.tier, body.flag, token)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, 'Partner not found')
    return {'token': token, **body.dict()}


@app.delete('/api/partners/{token}', status_code=204)
def delete_partner(token: str):
    with get_conn() as conn:
        cur = conn.execute('DELETE FROM partners WHERE token=?', (token,))
        if cur.rowcount == 0:
            raise HTTPException(404, 'Partner not found')


# ── Tickets ─────────────────────────────────────────────────────────────────

class TicketIn(BaseModel):
    token: str
    text: str
    merchant: Optional[str] = ''
    impact: str = 'mid'
    scenes: list[str] = []
    biz_type: Optional[str] = None
    lang: Optional[str] = None
    manual: bool = False
    user_summary: Optional[str] = ''


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    cluster_id: Optional[str] = None


@app.get('/api/tickets')
def list_tickets(
    token: Optional[str] = None,
    region: Optional[str] = None,
    status: Optional[str] = None,
    impact: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if token:
        with get_conn() as conn:
            p = conn.execute('SELECT region_id FROM partners WHERE token=?', (token,)).fetchone()
        if p:
            clauses.append('region_id=?')
            params.append(p['region_id'])
    if region and region != 'all':
        clauses.append('region_id=?')
        params.append(region)
    if status and status != 'all':
        clauses.append('status=?')
        params.append(status)
    if impact and impact != 'all':
        clauses.append('impact=?')
        params.append(impact)
    if search:
        clauses.append('(text LIKE ? OR merchant LIKE ? OR id LIKE ?)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    offset = (page - 1) * page_size

    with get_conn() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM tickets {where}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT * FROM tickets {where} ORDER BY time DESC LIMIT ? OFFSET ?',
            params + [page_size, offset]
        ).fetchall()

    return {'total': total, 'page': page, 'page_size': page_size, 'items': [ticket_row(r) for r in rows]}


@app.post('/api/tickets', status_code=201)
def create_ticket(body: TicketIn):
    with get_conn() as conn:
        partner = conn.execute('SELECT * FROM partners WHERE token=?', (body.token,)).fetchone()
    if not partner:
        raise HTTPException(400, 'Invalid token')
    partner = row_to_dict(partner)

    tid = generate_ticket_id(partner['region_id'])
    now = datetime.now(_TZ_CST).strftime('%Y-%m-%d %H:%M')

    with get_conn() as conn:
        conn.execute(
            'INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, partner['name'], partner['region_id'],
             body.text, body.merchant, body.impact,
             json.dumps(body.scenes, ensure_ascii=False),
             body.biz_type, now, 'pending', None, '[]',
             1 if body.manual else 0, body.lang or partner['lang'],
             body.user_summary or '')
        )
    return {'id': tid, 'time': now, 'status': 'pending'}


@app.put('/api/tickets/{ticket_id}')
def update_ticket(ticket_id: str, body: TicketUpdate):
    sets, params = [], []
    if body.status is not None:
        sets.append('status=?')
        params.append(body.status)
    if body.cluster_id is not None:
        sets.append('cluster_id=?')
        params.append(body.cluster_id)
    if not sets:
        raise HTTPException(400, 'Nothing to update')
    params.append(ticket_id)
    with get_conn() as conn:
        cur = conn.execute(f'UPDATE tickets SET {", ".join(sets)} WHERE id=?', params)
        if cur.rowcount == 0:
            raise HTTPException(404, 'Ticket not found')
    return {'ok': True}


# ── Clusters ────────────────────────────────────────────────────────────────

class ClusterUpdate(BaseModel):
    status: Optional[str] = None
    layer: Optional[str] = None
    ai_summary: Optional[str] = None
    related_saas: Optional[list] = None


@app.get('/api/clusters')
def list_clusters(
    region: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if region and region != 'all':
        clauses.append("source_ids LIKE ?")
        params.append(f'%"{region}"%')
    if status and status != 'all':
        clauses.append('status=?')
        params.append(status)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    offset = (page - 1) * page_size

    with get_conn() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM clusters {where}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT * FROM clusters {where} ORDER BY score DESC LIMIT ? OFFSET ?',
            params + [page_size, offset]
        ).fetchall()
        cluster_ids = [r['id'] for r in rows]
        # Bulk-load all tickets for these clusters in two queries
        tickets_by_cluster = {}
        if cluster_ids:
            ph = ','.join(['?'] * len(cluster_ids))
            ct_rows = conn.execute(
                f'SELECT cluster_id, ticket_id FROM cluster_tickets WHERE cluster_id IN ({ph})',
                cluster_ids
            ).fetchall()
            all_tids = [r['ticket_id'] for r in ct_rows]
            ticket_map = {}
            if all_tids:
                tph = ','.join(['?'] * len(all_tids))
                for t in conn.execute(f'SELECT * FROM tickets WHERE id IN ({tph})', all_tids).fetchall():
                    ticket_map[t['id']] = ticket_row(t)
            for ct in ct_rows:
                tickets_by_cluster.setdefault(ct['cluster_id'], [])
                if ct['ticket_id'] in ticket_map:
                    tickets_by_cluster[ct['cluster_id']].append(ticket_map[ct['ticket_id']])

    items = []
    for r in rows:
        d = row_to_dict(r)
        d['source_ids'] = parse_json_field(d.get('source_ids'), [])
        d['partners'] = parse_json_field(d.get('partners'), [])
        d['related_saas'] = parse_json_field(d.get('related_saas'), [])
        d['urgent'] = bool(d.get('urgent', 0))
        d['items'] = tickets_by_cluster.get(d['id'], [])
        items.append(d)

    return {'total': total, 'page': page, 'page_size': page_size, 'items': items}


@app.put('/api/clusters/{cluster_id}')
def update_cluster(cluster_id: str, body: ClusterUpdate):
    sets, params = [], []
    if body.status is not None:
        sets.append('status=?')
        params.append(body.status)
    if body.layer is not None:
        sets.append('layer=?')
        params.append(body.layer)
    if body.ai_summary is not None:
        sets.append('ai_summary=?')
        params.append(body.ai_summary)
    if body.related_saas is not None:
        sets.append('related_saas=?')
        params.append(json.dumps(body.related_saas, ensure_ascii=False))
    if not sets:
        raise HTTPException(400, 'Nothing to update')
    params.append(cluster_id)
    with get_conn() as conn:
        cur = conn.execute(f'UPDATE clusters SET {", ".join(sets)} WHERE id=?', params)
        if cur.rowcount == 0:
            raise HTTPException(404, 'Cluster not found')
    return {'ok': True}


# ── Scoring config ───────────────────────────────────────────────────────────

@app.get('/api/scoring-config')
def get_scoring_config():
    with get_conn() as conn:
        row = conn.execute('SELECT config_json FROM scoring_config WHERE id=1').fetchone()
    if not row:
        raise HTTPException(404, 'No scoring config found')
    return json.loads(row['config_json'])


@app.put('/api/scoring-config')
def save_scoring_config(body: dict):
    with get_conn() as conn:
        existing = conn.execute('SELECT id FROM scoring_config WHERE id=1').fetchone()
        if existing:
            conn.execute('UPDATE scoring_config SET config_json=? WHERE id=1',
                         (json.dumps(body, ensure_ascii=False),))
        else:
            conn.execute('INSERT INTO scoring_config (id, config_json) VALUES (1, ?)',
                         (json.dumps(body, ensure_ascii=False),))
    return {'ok': True}


# ── AI Preview (Requirement Analysis) ────────────────────────────────────────

class PreviewIn(BaseModel):
    text: str
    impact: str = 'mid'
    scenes: list[str] = []
    biz_type: Optional[str] = None
    lang: Optional[str] = 'zh'


def _call_deepseek_preview(text: str, impact: str, scenes: list, biz_type: Optional[str]) -> str:
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise ValueError('DEEPSEEK_API_KEY not set')

    scenes_str = ', '.join(scenes) if scenes else '-'
    biz_str = biz_type or '-'
    impact_str = {'high': '高', 'mid': '中', 'low': '低'}.get(impact, impact)

    prompt = f"""你是一位便利店产品经理。门店用户提交了一条口语化的反馈，请改写成产品经理能快速理解的简短描述。

规则：
1. 保留原意，不编造信息
2. 口语转书面语，用产品术语（如"东西卖不掉"→"部分商品滞销"）
3. 格式：一句话说明场景+问题，一句话说明期望
4. **总字数不超过 80 字**
5. 只输出文本，不要标题、不要分点、不要 markdown

【原始描述】{text}
【门店类型】{biz_str}
【影响程度】{impact_str}"""

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    response = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


@app.post('/api/preview-ticket')
def preview_ticket(body: PreviewIn):
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise HTTPException(500, 'DEEPSEEK_API_KEY not set on the server')
    try:
        summary = _call_deepseek_preview(body.text, body.impact, body.scenes, body.biz_type)
        return {'summary': summary}
    except Exception as e:
        raise HTTPException(500, f'AI 分析失败: {e}')


# ── AI Merge ─────────────────────────────────────────────────────────────────

def _next_cluster_ids(conn, count: int) -> list[str]:
    rows = conn.execute("SELECT id FROM clusters WHERE id LIKE ?", ('#%',)).fetchall()
    nums = []
    for r in rows:
        tail = r['id'][1:]
        if tail.isdigit():
            nums.append(int(tail))
    start = max(nums, default=0) + 1
    return [f'#{start + i:03d}' for i in range(count)]


def _strip_markdown_json(raw: str) -> str:
    """Remove markdown code fences regardless of placement (multiline or inline)."""
    raw = re.sub(r'```[a-z]*', '', raw)
    raw = re.sub(r'```', '', raw)
    return raw.strip()


def _call_deepseek(tickets: list[dict], existing_clusters: list[dict], saas_vendors: list[dict] = None) -> list[dict]:
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise ValueError('DEEPSEEK_API_KEY not set')

    ticket_lines = []
    for t in tickets:
        scenes = ', '.join(t['scenes']) if t['scenes'] else '-'
        text = (t['text'] or '').encode('utf-8', errors='replace').decode('utf-8')
        ticket_lines.append(f"ID: {t['id']} | 区域: {t['region_id']} | Impact: {t['impact']} | Scenes: {scenes} | Text: {text}")

    cluster_lines = []
    for c in existing_clusters:
        rs = c.get('related_saas') or '[]'
        if isinstance(rs, str):
            rs = rs
        cluster_lines.append(f"簇ID: {c['id']} | 标题: {c['summary']} | 归属SaaS: {rs} | 摘要: {(c.get('ai_summary') or '')[:60]}")

    existing_block = ''
    if cluster_lines:
        existing_block = f"""
【已有需求簇（优先归入，不要重复建簇）】
{chr(10).join(cluster_lines)}
"""

    vendor_block = ''
    if saas_vendors:
        vlines = [f"- {v['name']}（{v['industry']}）" for v in saas_vendors]
        vendor_block = f"""
【当前平台已接入的SaaS厂商列表】
{chr(10).join(vlines)}
"""

    prompt = f"""你是一个 SaaS 产品需求分析师，服务对象是国内各区域代理商（华北、华南、华东、华中、西部等）。
工单描述语言为中文。
{existing_block}{vendor_block}
【待归并的新工单】（格式：ID | 区域 | 影响 | 场景 | 描述原文）
{chr(10).join(ticket_lines)}

归并原则（非常重要）：
- 【优先归入已有需求簇】：如果新工单与已有需求簇描述的是同一类功能，必须归入已有簇，不要新建簇。
- 【宁可多归并，不要拆散】：只要功能领域相同，无论措辞差异多大、语言是否相同，都应归为一簇。
- 对于描述模糊或极短的工单，优先与语义最接近的簇合并，不要单独成簇。
- 不同区域反馈同一功能缺失的工单，必须归为一簇。

归并规则：
1. 每条工单必须且只能属于一个需求簇
2. 相似度判断要宽松：功能领域相同即可归并，不要求描述完全一致
3. 归入已有簇时，使用 existing_cluster_id 字段，不要填 summary/layer/impact/ai_summary/related_saas
4. 新建簇时：
   - layer 分类：saas（功能由特定SaaS厂商提供）/ platform（我方平台自建）/ cross（跨层通用）
   - impact 取最高级
   - ai_summary：100-200字中文分析，说明需求场景、业务价值
   - related_saas：若 layer=saas，从【SaaS厂商列表】中选出最匹配的厂商名称数组；若多个行业SaaS都涉及（通用能力）则填 ["通用"]；若 layer!=saas 则填 []
5. 只对真正全新的需求才新建需求簇

只返回合法 JSON 数组，不要 markdown 代码块标记，不要任何其他文字。
归入已有簇的格式：{{"ticket_ids":["ID-0001"],"existing_cluster_id":"#028"}}
新建簇的格式：{{"ticket_ids":["ID-0002","TH-0003"],"summary":"15字以内中文需求标题","layer":"saas","impact":"high","ai_summary":"100-200字中文分析...","related_saas":["厂商名称"]}}"""

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    response = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=4096,
    )
    raw = response.choices[0].message.content.strip()
    raw = _strip_markdown_json(raw)
    return json.loads(raw)


@app.post('/api/merge')
def run_merge():
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise HTTPException(500, 'DEEPSEEK_API_KEY not set on the server')

    with get_conn() as conn:
        pending_rows = conn.execute(
            "SELECT * FROM tickets WHERE cluster_id IS NULL AND status='pending'"
        ).fetchall()
        existing_rows = conn.execute(
            "SELECT id, summary, ai_summary, related_saas FROM clusters WHERE status != 'live' ORDER BY score DESC"
        ).fetchall()
        saas_vendor_rows = conn.execute(
            "SELECT name, industry FROM saas_vendors ORDER BY name"
        ).fetchall()

    if not pending_rows:
        return {'merged_into_existing': 0, 'created_new': 0, 'ticket_count': 0, 'message': '没有待归并的工单'}

    tickets = [ticket_row(r) for r in pending_rows]
    existing_clusters = [dict(r) for r in existing_rows]
    saas_vendors = [dict(r) for r in saas_vendor_rows]

    try:
        clusters_data = _call_deepseek(tickets, existing_clusters, saas_vendors)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f'LLM 返回内容无法解析为 JSON: {e}')
    except Exception as e:
        raise HTTPException(500, str(e))

    if not isinstance(clusters_data, list):
        raise HTTPException(500, 'LLM 返回格式错误，期望 JSON 数组')

    # Separate into: merge into existing vs create new
    merge_into_existing = [c for c in clusters_data if c.get('existing_cluster_id')]
    create_new = [c for c in clusters_data if not c.get('existing_cluster_id')]

    created_count = 0

    with get_conn() as conn:
        # ── 1. Merge new tickets into existing clusters ──────────────────────
        for c in merge_into_existing:
            existing_id = c['existing_cluster_id']
            ticket_ids = c.get('ticket_ids', [])
            matched = [t for t in tickets if t['id'] in ticket_ids]
            if not matched:
                continue
            # Validate cluster actually exists — guard against LLM hallucinated IDs
            exists = conn.execute('SELECT 1 FROM clusters WHERE id=?', (existing_id,)).fetchone()
            if not exists:
                continue

            for tid in ticket_ids:
                conn.execute(
                    'UPDATE tickets SET cluster_id=?, status=? WHERE id=? AND cluster_id IS NULL',
                    (existing_id, 'merged', tid)
                )
                conn.execute(
                    'INSERT INTO cluster_tickets VALUES (?,?) ON CONFLICT DO NOTHING',
                    (existing_id, tid)
                )

            # Recalculate cluster metadata
            all_ticket_rows = conn.execute(
                '''SELECT t.region_id, t.partner_name, t.impact FROM tickets t
                   JOIN cluster_tickets ct ON ct.ticket_id = t.id
                   WHERE ct.cluster_id=?''',
                (existing_id,)
            ).fetchall()

            source_ids = list({r['region_id'] for r in all_ticket_rows if r['region_id']})
            partners   = list({r['partner_name'] for r in all_ticket_rows if r['partner_name']})
            impact_rank = {'high': 3, 'mid': 2, 'low': 1}
            top_impact = max((r['impact'] for r in all_ticket_rows), key=lambda x: impact_rank.get(x, 0), default='mid')

            conn.execute(
                '''UPDATE clusters SET count=?, source_ids=?, partners=?, impact=?
                   WHERE id=?''',
                (len(all_ticket_rows),
                 json.dumps(source_ids, ensure_ascii=False),
                 json.dumps(partners, ensure_ascii=False),
                 top_impact, existing_id)
            )

        # ── 2. Create new clusters ───────────────────────────────────────────
        new_ids = _next_cluster_ids(conn, len(create_new))
        for cid, c in zip(new_ids, create_new):
            ticket_ids = c.get('ticket_ids', [])
            summary    = c.get('summary', '（无标题）')
            layer      = c.get('layer', 'saas')
            impact     = c.get('impact', 'mid')
            ai_summary = c.get('ai_summary', '')

            matched = [t for t in tickets if t['id'] in ticket_ids]
            source_ids   = list({t['region_id'] for t in matched if t['region_id']})
            partners     = list({t['partner_name'] for t in matched if t['partner_name']})
            related_saas = c.get('related_saas', [])
            if not isinstance(related_saas, list):
                related_saas = []

            conn.execute(
                '''INSERT INTO clusters
                   (id, score, urgent, summary, layer, impact, source_ids, partners, count, periods, status, ai_summary, related_saas)
                   VALUES (?,0,0,?,?,?,?,?,?,1,'pending',?,?)
                   ON CONFLICT (id) DO NOTHING''',
                (cid, summary, layer, impact,
                 json.dumps(source_ids, ensure_ascii=False),
                 json.dumps(partners,   ensure_ascii=False),
                 len(matched), ai_summary,
                 json.dumps(related_saas, ensure_ascii=False))
            )
            created_count += 1

            for tid in ticket_ids:
                conn.execute(
                    'UPDATE tickets SET cluster_id=?, status=? WHERE id=? AND cluster_id IS NULL',
                    (cid, 'merged', tid)
                )
                conn.execute(
                    'INSERT INTO cluster_tickets VALUES (?,?) ON CONFLICT DO NOTHING',
                    (cid, tid)
                )

    return {
        'merged_into_existing': len(merge_into_existing),
        'created_new': created_count,
        'ticket_count': len(tickets),
    }


# ── SaaS Vendors ─────────────────────────────────────────────────────────────

SAAS_INDUSTRIES = ['连锁便利店', '独立便利店', '社区超市', '生鲜便利店', '加油站便利店', '校园便利店']

class SaasVendorIn(BaseModel):
    name: str
    industry: str
    code: str
    contact: Optional[str] = ''


@app.get('/api/saas-vendors')
def list_saas_vendors():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM saas_vendors ORDER BY created_at DESC').fetchall()
    return [row_to_dict(r) for r in rows]


@app.post('/api/saas-vendors', status_code=201)
def create_saas_vendor(body: SaasVendorIn):
    code = body.code.upper()
    import random, string as _string
    suffix = ''.join(random.choices(_string.ascii_lowercase + _string.digits, k=8))
    token = f'SV_{suffix}'
    now = datetime.now(_TZ_CST).strftime('%Y-%m-%d %H:%M')
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO saas_vendors (token, name, industry, code, contact, created_at) VALUES (?,?,?,?,?,?)',
            (token, body.name, body.industry, code, body.contact or '', now)
        )
    return {'token': token, 'name': body.name, 'industry': body.industry,
            'code': code, 'contact': body.contact or '', 'created_at': now}


@app.put('/api/saas-vendors/{token}')
def update_saas_vendor(token: str, body: SaasVendorIn):
    with get_conn() as conn:
        cur = conn.execute(
            'UPDATE saas_vendors SET name=?, industry=?, code=?, contact=? WHERE token=?',
            (body.name, body.industry, body.code.upper(), body.contact or '', token)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, 'SaaS vendor not found')
    return {'ok': True}


@app.delete('/api/saas-vendors/{token}', status_code=204)
def delete_saas_vendor(token: str):
    with get_conn() as conn:
        cur = conn.execute('DELETE FROM saas_vendors WHERE token=?', (token,))
        if cur.rowcount == 0:
            raise HTTPException(404, 'SaaS vendor not found')


# ── SaaS Tickets ──────────────────────────────────────────────────────────────

class SaasTicketIn(BaseModel):
    token: str
    text: str
    merchant: Optional[str] = ''
    impact: str = 'mid'
    scenes: list[str] = []
    biz_type: Optional[str] = None
    manual: bool = False


class SaasTicketUpdate(BaseModel):
    status: Optional[str] = None
    saas_cluster_id: Optional[str] = None


def saas_ticket_row(row):
    d = row_to_dict(row)
    d['scenes'] = parse_json_field(d.get('scenes'), [])
    d['attachments'] = parse_json_field(d.get('attachments'), [])
    d['manual'] = bool(d.get('manual', 0))
    return d


def generate_saas_ticket_id(code: str) -> str:
    with get_conn() as conn:
        for _ in range(20):
            tid = f'{code}-{random.randint(1000, 9999)}'
            exists = conn.execute('SELECT 1 FROM saas_tickets WHERE id=?', (tid,)).fetchone()
            if not exists:
                return tid
    raise RuntimeError('Could not generate unique SaaS ticket ID')


@app.get('/api/saas-tickets')
def list_saas_tickets(
    token: Optional[str] = None,
    status: Optional[str] = None,
    impact: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if token:
        with get_conn() as conn:
            v = conn.execute('SELECT * FROM saas_vendors WHERE token=?', (token,)).fetchone()
        if v:
            clauses.append('vendor_token=?')
            params.append(token)
    if status and status != 'all':
        clauses.append('status=?')
        params.append(status)
    if impact and impact != 'all':
        clauses.append('impact=?')
        params.append(impact)
    if search:
        clauses.append('(text LIKE ? OR merchant LIKE ? OR id LIKE ?)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    offset = (page - 1) * page_size

    with get_conn() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM saas_tickets {where}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT * FROM saas_tickets {where} ORDER BY time DESC LIMIT ? OFFSET ?',
            params + [page_size, offset]
        ).fetchall()

    return {'total': total, 'page': page, 'page_size': page_size,
            'items': [saas_ticket_row(r) for r in rows]}


@app.post('/api/saas-tickets', status_code=201)
def create_saas_ticket(body: SaasTicketIn):
    with get_conn() as conn:
        vendor = conn.execute('SELECT * FROM saas_vendors WHERE token=?', (body.token,)).fetchone()
    if not vendor:
        raise HTTPException(400, 'Invalid token')
    vendor = row_to_dict(vendor)

    tid = generate_saas_ticket_id(vendor['code'])
    now = datetime.now(_TZ_CST).strftime('%Y-%m-%d %H:%M')

    with get_conn() as conn:
        conn.execute(
            'INSERT INTO saas_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, vendor['token'], vendor['name'], vendor['industry'],
             body.text, body.merchant, body.impact,
             json.dumps(body.scenes, ensure_ascii=False),
             body.biz_type, now, 'pending', None, '[]',
             1 if body.manual else 0)
        )
    return {'id': tid, 'time': now, 'status': 'pending'}


@app.put('/api/saas-tickets/{ticket_id}')
def update_saas_ticket(ticket_id: str, body: SaasTicketUpdate):
    sets, params = [], []
    if body.status is not None:
        sets.append('status=?')
        params.append(body.status)
    if body.saas_cluster_id is not None:
        sets.append('saas_cluster_id=?')
        params.append(body.saas_cluster_id)
    if not sets:
        raise HTTPException(400, 'Nothing to update')
    params.append(ticket_id)
    with get_conn() as conn:
        cur = conn.execute(f'UPDATE saas_tickets SET {", ".join(sets)} WHERE id=?', params)
        if cur.rowcount == 0:
            raise HTTPException(404, 'SaaS ticket not found')
    return {'ok': True}


# ── SaaS Clusters ─────────────────────────────────────────────────────────────

class SaasClusterUpdate(BaseModel):
    status: Optional[str] = None
    layer: Optional[str] = None
    ai_summary: Optional[str] = None


def saas_cluster_row(row):
    d = row_to_dict(row)
    d['vendor_names'] = parse_json_field(d.get('vendor_names'), [])
    d['urgent'] = bool(d.get('urgent', 0))
    with get_conn() as conn:
        tids = [r['ticket_id'] for r in conn.execute(
            'SELECT ticket_id FROM saas_cluster_tickets WHERE cluster_id=?', (d['id'],)
        ).fetchall()]
        items = []
        for tid in tids:
            t = conn.execute('SELECT * FROM saas_tickets WHERE id=?', (tid,)).fetchone()
            if t:
                items.append(saas_ticket_row(t))
    d['items'] = items
    return d


def _next_saas_cluster_ids(conn, count: int) -> list[str]:
    rows = conn.execute("SELECT id FROM saas_clusters WHERE id LIKE ?", ('$%',)).fetchall()
    nums = []
    for r in rows:
        tail = r['id'][1:]
        if tail.isdigit():
            nums.append(int(tail))
    start = max(nums, default=0) + 1
    return [f'${start + i:03d}' for i in range(count)]


@app.get('/api/saas-clusters')
def list_saas_clusters(
    token: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if token:
        with get_conn() as conn:
            v = conn.execute('SELECT name FROM saas_vendors WHERE token=?', (token,)).fetchone()
        if v:
            clauses.append("vendor_names LIKE ?")
            params.append(f'%"{v["name"]}"%')
    if status and status != 'all':
        clauses.append('status=?')
        params.append(status)

    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    offset = (page - 1) * page_size

    with get_conn() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM saas_clusters {where}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT * FROM saas_clusters {where} ORDER BY score DESC LIMIT ? OFFSET ?',
            params + [page_size, offset]
        ).fetchall()
        cluster_ids = [r['id'] for r in rows]
        tickets_by_cluster = {}
        if cluster_ids:
            ph = ','.join(['?'] * len(cluster_ids))
            ct_rows = conn.execute(
                f'SELECT cluster_id, ticket_id FROM saas_cluster_tickets WHERE cluster_id IN ({ph})',
                cluster_ids
            ).fetchall()
            all_tids = [r['ticket_id'] for r in ct_rows]
            ticket_map = {}
            if all_tids:
                tph = ','.join(['?'] * len(all_tids))
                for t in conn.execute(f'SELECT * FROM saas_tickets WHERE id IN ({tph})', all_tids).fetchall():
                    ticket_map[t['id']] = saas_ticket_row(t)
            for ct in ct_rows:
                tickets_by_cluster.setdefault(ct['cluster_id'], [])
                if ct['ticket_id'] in ticket_map:
                    tickets_by_cluster[ct['cluster_id']].append(ticket_map[ct['ticket_id']])

    items = []
    for r in rows:
        d = row_to_dict(r)
        d['vendor_names'] = parse_json_field(d.get('vendor_names'), [])
        d['urgent'] = bool(d.get('urgent', 0))
        d['items'] = tickets_by_cluster.get(d['id'], [])
        items.append(d)

    return {'total': total, 'page': page, 'page_size': page_size, 'items': items}


@app.put('/api/saas-clusters/{cluster_id}')
def update_saas_cluster(cluster_id: str, body: SaasClusterUpdate):
    sets, params = [], []
    if body.status is not None:
        sets.append('status=?')
        params.append(body.status)
    if body.layer is not None:
        sets.append('layer=?')
        params.append(body.layer)
    if body.ai_summary is not None:
        sets.append('ai_summary=?')
        params.append(body.ai_summary)
    if not sets:
        raise HTTPException(400, 'Nothing to update')
    params.append(cluster_id)
    with get_conn() as conn:
        cur = conn.execute(f'UPDATE saas_clusters SET {", ".join(sets)} WHERE id=?', params)
        if cur.rowcount == 0:
            raise HTTPException(404, 'SaaS cluster not found')
    return {'ok': True}


# ── SaaS AI Merge ─────────────────────────────────────────────────────────────

def _call_deepseek_saas(tickets: list[dict], existing_clusters: list[dict]) -> list[dict]:
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise ValueError('DEEPSEEK_API_KEY not set')

    ticket_lines = []
    for t in tickets:
        scenes = ', '.join(t['scenes']) if t['scenes'] else '-'
        ticket_lines.append(
            f"ID: {t['id']} | 厂商: {t['vendor_name']} | 行业: {t['industry']} "
            f"| 影响: {t['impact']} | 场景: {scenes} | 需求: {t['text']}"
        )

    cluster_lines = []
    for c in existing_clusters:
        cluster_lines.append(f"簇ID: {c['id']} | 标题: {c['summary']} | 摘要: {(c.get('ai_summary') or '')[:80]}")

    existing_block = ''
    if cluster_lines:
        existing_block = f"""
【已有需求簇（优先归入，不要重复建簇）】
{chr(10).join(cluster_lines)}
"""

    prompt = f"""你是一个 SaaS 产品需求分析师，服务对象是国内便利店行业（连锁便利店、独立便利店、社区超市等）。工单描述均为中文。
{existing_block}
【待归并的新工单】（格式：ID | 厂商 | 行业 | 影响 | 场景 | 需求描述）
{chr(10).join(ticket_lines)}

便利店场景分类（归并时参考）：
- 商品场景：商品管理、效期管理、选品、定价、促销
- 智能补货场景：库存预警、自动补货、销量预测、保质期管理
- 采购入库：供应商管理、采购订单、送货验收、入库登记
- 店内操作：价签管理、盘点、陈列、温度监控
- 店内POS：收银、自助收银、聚合支付、小票打印
- O2O线上销售：外卖平台对接、小程序商城、团购、自提

归并原则（非常重要）：
- 【优先归入已有需求簇】：如果新工单与已有需求簇描述的是同一类功能，必须归入已有簇，不要新建簇。
- 【宁可多归并，不要拆散】：只要功能领域相同，无论措辞差异多大，都应归为一簇。
- 不同厂商反馈同一功能缺失的工单，必须归为一簇。

归并规则：
1. 每条工单必须且只能属于一个需求簇
2. 相似度判断要宽松：功能领域相同即可归并
3. 归入已有簇时，使用 existing_cluster_id 字段填写已有簇ID，不要填 summary/layer/impact/ai_summary
4. 新建簇时：layer 分类 saas/platform/cross，impact 取最高级，ai_summary 100-200字中文分析
5. 只对真正全新的需求才新建需求簇

只返回合法 JSON 数组，不要 markdown 代码块标记，不要任何其他文字。
归入已有簇的格式：{{"ticket_ids":["MT-0001"],"existing_cluster_id":"$028"}}
新建簇的格式：{{"ticket_ids":["MT-0002","ELE-0003"],"summary":"15字以内中文需求标题","layer":"saas","impact":"high","ai_summary":"100-200字中文分析..."}}"""

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    response = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=4096,
    )
    raw = response.choices[0].message.content.strip()
    raw = _strip_markdown_json(raw)
    return json.loads(raw)


@app.post('/api/saas-merge')
def run_saas_merge():
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise HTTPException(500, 'DEEPSEEK_API_KEY not set on the server')

    with get_conn() as conn:
        pending_rows = conn.execute(
            "SELECT * FROM saas_tickets WHERE saas_cluster_id IS NULL AND status='pending'"
        ).fetchall()
        existing_rows = conn.execute(
            "SELECT id, summary, ai_summary FROM saas_clusters WHERE status != 'live' ORDER BY score DESC"
        ).fetchall()

    if not pending_rows:
        return {'merged_into_existing': 0, 'created_new': 0, 'ticket_count': 0, 'message': '没有待归并的SaaS工单'}

    tickets = [saas_ticket_row(r) for r in pending_rows]
    existing_clusters = [dict(r) for r in existing_rows]

    try:
        clusters_data = _call_deepseek_saas(tickets, existing_clusters)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f'LLM 返回内容无法解析为 JSON: {e}')
    except Exception as e:
        raise HTTPException(500, str(e))

    if not isinstance(clusters_data, list):
        raise HTTPException(500, 'LLM 返回格式错误，期望 JSON 数组')

    merge_into_existing = [c for c in clusters_data if c.get('existing_cluster_id')]
    create_new = [c for c in clusters_data if not c.get('existing_cluster_id')]
    created_count = 0

    with get_conn() as conn:
        for c in merge_into_existing:
            existing_id = c['existing_cluster_id']
            ticket_ids = c.get('ticket_ids', [])
            matched = [t for t in tickets if t['id'] in ticket_ids]
            if not matched:
                continue
            exists = conn.execute('SELECT 1 FROM saas_clusters WHERE id=?', (existing_id,)).fetchone()
            if not exists:
                continue
            for tid in ticket_ids:
                conn.execute(
                    'UPDATE saas_tickets SET saas_cluster_id=?, status=? WHERE id=? AND saas_cluster_id IS NULL',
                    (existing_id, 'merged', tid)
                )
                conn.execute(
                    'INSERT INTO saas_cluster_tickets VALUES (?,?) ON CONFLICT DO NOTHING',
                    (existing_id, tid)
                )
            all_ticket_rows = conn.execute(
                '''SELECT t.vendor_name, t.impact FROM saas_tickets t
                   JOIN saas_cluster_tickets ct ON ct.ticket_id = t.id
                   WHERE ct.cluster_id=?''', (existing_id,)
            ).fetchall()
            vendor_names = list({r['vendor_name'] for r in all_ticket_rows if r['vendor_name']})
            impact_rank = {'high': 3, 'mid': 2, 'low': 1}
            top_impact = max((r['impact'] for r in all_ticket_rows), key=lambda x: impact_rank.get(x, 0), default='mid')
            conn.execute(
                'UPDATE saas_clusters SET count=?, vendor_names=?, impact=? WHERE id=?',
                (len(all_ticket_rows), json.dumps(vendor_names, ensure_ascii=False), top_impact, existing_id)
            )

        new_ids = _next_saas_cluster_ids(conn, len(create_new))
        for cid, c in zip(new_ids, create_new):
            ticket_ids = c.get('ticket_ids', [])
            summary    = c.get('summary', '（无标题）')
            layer      = c.get('layer', 'saas')
            impact     = c.get('impact', 'mid')
            ai_summary = c.get('ai_summary', '')
            matched = [t for t in tickets if t['id'] in ticket_ids]
            vendor_names = list({t['vendor_name'] for t in matched if t['vendor_name']})
            conn.execute(
                '''INSERT INTO saas_clusters
                   (id, score, urgent, summary, layer, impact, vendor_names, count, periods, status, ai_summary)
                   VALUES (?,0,0,?,?,?,?,?,1,'pending',?)
                   ON CONFLICT (id) DO NOTHING''',
                (cid, summary, layer, impact,
                 json.dumps(vendor_names, ensure_ascii=False), len(matched), ai_summary)
            )
            created_count += 1
            for tid in ticket_ids:
                conn.execute(
                    'UPDATE saas_tickets SET saas_cluster_id=?, status=? WHERE id=? AND saas_cluster_id IS NULL',
                    (cid, 'merged', tid)
                )
                conn.execute(
                    'INSERT INTO saas_cluster_tickets VALUES (?,?) ON CONFLICT DO NOTHING',
                    (cid, tid)
                )

    return {
        'merged_into_existing': len(merge_into_existing),
        'created_new': created_count,
        'ticket_count': len(tickets),
    }


@app.get('/')
def root():
    return RedirectResponse(url='/需求看板.html')


# ── Serve frontend static files (must be last) ───────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(__file__), '..')
app.mount('/', StaticFiles(directory=_frontend_dir, html=True), name='frontend')
