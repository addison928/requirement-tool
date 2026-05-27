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
        print('✅ Database initialized successfully')
    except Exception as e:
        # Log but don't crash — static files still served; API calls will fail gracefully
        print(f'❌ Database init failed: {e}', flush=True)


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
    return d


def cluster_row(row):
    d = row_to_dict(row)
    d['source_ids'] = parse_json_field(d.get('source_ids'), [])
    d['partners'] = parse_json_field(d.get('partners'), [])
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


def generate_token(country_id: str) -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f'{country_id}_{suffix}'


def generate_ticket_id(country_id: str) -> str:
    with get_conn() as conn:
        for _ in range(20):
            tid = f'{country_id}-{random.randint(1000, 9999)}'
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
        by_country = conn.execute(
            'SELECT country_id, COUNT(*) as cnt FROM tickets GROUP BY country_id ORDER BY cnt DESC'
        ).fetchall()
        by_layer = conn.execute(
            'SELECT layer, COUNT(*) as cnt FROM clusters GROUP BY layer'
        ).fetchall()
    return {
        'total_tickets': total_tickets,
        'total_clusters': total_clusters,
        'by_country': [dict(r) for r in by_country],
        'by_layer': [dict(r) for r in by_layer],
    }


# ── Partners ────────────────────────────────────────────────────────────────

class PartnerIn(BaseModel):
    country_id: str
    flag: str
    country_name: str
    name: str
    lang: str = 'en'
    tier: str = 'normal'


@app.get('/api/partners')
def list_partners():
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM partners').fetchall()
    return [row_to_dict(r) for r in rows]


@app.post('/api/partners', status_code=201)
def create_partner(body: PartnerIn):
    token = generate_token(body.country_id.upper())
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO partners VALUES (?,?,?,?,?,?,?)',
            (token, body.country_id.upper(), body.flag, body.country_name,
             body.name, body.lang, body.tier)
        )
    return {'token': token, **body.dict(), 'country_id': body.country_id.upper()}


@app.put('/api/partners/{token}')
def update_partner(token: str, body: PartnerIn):
    with get_conn() as conn:
        cur = conn.execute(
            '''UPDATE partners SET country_id=?, flag=?, country_name=?, name=?, lang=?, tier=?
               WHERE token=?''',
            (body.country_id.upper(), body.flag, body.country_name,
             body.name, body.lang, body.tier, token)
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


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    cluster_id: Optional[str] = None


@app.get('/api/tickets')
def list_tickets(
    token: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
    impact: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if token:
        with get_conn() as conn:
            p = conn.execute('SELECT country_id FROM partners WHERE token=?', (token,)).fetchone()
        if p:
            clauses.append('country_id=?')
            params.append(p['country_id'])
    if country and country != 'all':
        clauses.append('country_id=?')
        params.append(country)
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

    tid = generate_ticket_id(partner['country_id'])
    now = datetime.now(_TZ_CST).strftime('%Y-%m-%d %H:%M')

    with get_conn() as conn:
        conn.execute(
            'INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, partner['flag'], partner['name'], partner['country_id'],
             body.text, body.merchant, body.impact,
             json.dumps(body.scenes, ensure_ascii=False),
             body.biz_type, now, 'pending', None, '[]',
             1 if body.manual else 0, body.lang or partner['lang'])
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


@app.get('/api/clusters')
def list_clusters(
    country: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
):
    clauses, params = [], []
    if country and country != 'all':
        clauses.append("source_ids LIKE ?")
        params.append(f'%"{country}"%')
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

    return {'total': total, 'page': page, 'page_size': page_size, 'items': [cluster_row(r) for r in rows]}


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


# ── AI Merge ─────────────────────────────────────────────────────────────────

def _next_cluster_ids(conn, count: int) -> list[str]:
    rows = conn.execute("SELECT id FROM clusters WHERE id LIKE '#%'").fetchall()
    nums = []
    for r in rows:
        tail = r[0][1:]
        if tail.isdigit():
            nums.append(int(tail))
    start = max(nums, default=0) + 1
    return [f'#{start + i:03d}' for i in range(count)]


def _call_deepseek(tickets: list[dict], existing_clusters: list[dict]) -> list[dict]:
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        raise ValueError('DEEPSEEK_API_KEY not set')

    ticket_lines = []
    for t in tickets:
        scenes = ', '.join(t['scenes']) if t['scenes'] else '-'
        text = (t['text'] or '').encode('utf-8', errors='replace').decode('utf-8')
        ticket_lines.append(f"ID: {t['id']} | Country: {t['country_id']} | Impact: {t['impact']} | Scenes: {scenes} | Text: {text}")

    cluster_lines = []
    for c in existing_clusters:
        cluster_lines.append(f"簇ID: {c['id']} | 标题: {c['summary']} | 摘要: {(c.get('ai_summary') or '')[:80]}")

    existing_block = ''
    if cluster_lines:
        existing_block = f"""
【已有需求簇（优先归入，不要重复建簇）】
{chr(10).join(cluster_lines)}
"""

    prompt = f"""你是一个 SaaS 产品需求分析师，服务对象是海外代理商（泰国、印尼、意大利、法国、柬埔寨、马来西亚等）。
工单描述语言可能为泰语、印尼语、意大利语、法语、英语或中文。
{existing_block}
【待归并的新工单】（格式：ID | 国家 | 影响 | 场景 | 描述原文）
{chr(10).join(ticket_lines)}

归并原则（非常重要）：
- 【优先归入已有需求簇】：如果新工单与已有需求簇描述的是同一类功能，必须归入已有簇，不要新建簇。
- 【宁可多归并，不要拆散】：只要功能领域相同，无论措辞差异多大、语言是否相同，都应归为一簇。
- 对于描述模糊或极短的工单，优先与语义最接近的簇合并，不要单独成簇。
- 不同国家反馈同一功能缺失的工单，必须归为一簇。

归并规则：
1. 每条工单必须且只能属于一个需求簇
2. 相似度判断要宽松：功能领域相同即可归并，不要求描述完全一致
3. 归入已有簇时，使用 existing_cluster_id 字段填写已有簇ID，不要填 summary/layer/impact/ai_summary
4. 新建簇时：layer 分类 saas/platform/cross，impact 取最高级，ai_summary 100-200字中文分析
5. 只对真正全新的需求才新建需求簇

只返回合法 JSON 数组，不要 markdown 代码块标记，不要任何其他文字。
归入已有簇的格式：{{"ticket_ids":["ID-0001"],"existing_cluster_id":"#028"}}
新建簇的格式：{{"ticket_ids":["ID-0002","TH-0003"],"summary":"15字以内中文需求标题","layer":"saas","impact":"high","ai_summary":"100-200字中文分析..."}}"""

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    response = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=4096,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\n?```$', '', raw, flags=re.MULTILINE)
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
            "SELECT id, summary, ai_summary FROM clusters WHERE status != 'live' ORDER BY score DESC"
        ).fetchall()

    if not pending_rows:
        return {'merged_into_existing': 0, 'created_new': 0, 'ticket_count': 0, 'message': '没有待归并的工单'}

    tickets = [ticket_row(r) for r in pending_rows]
    existing_clusters = [dict(r) for r in existing_rows]

    try:
        clusters_data = _call_deepseek(tickets, existing_clusters)
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
                '''SELECT t.country_id, t.partner_name, t.impact FROM tickets t
                   JOIN cluster_tickets ct ON ct.ticket_id = t.id
                   WHERE ct.cluster_id=?''',
                (existing_id,)
            ).fetchall()

            source_ids = list({r['country_id'] for r in all_ticket_rows if r['country_id']})
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
            source_ids = list({t['country_id'] for t in matched if t['country_id']})
            partners   = list({t['partner_name'] for t in matched if t['partner_name']})

            conn.execute(
                '''INSERT INTO clusters
                   (id, score, urgent, summary, layer, impact, source_ids, partners, count, periods, status, ai_summary)
                   VALUES (?,0,0,?,?,?,?,?,?,1,'pending',?)
                   ON CONFLICT (id) DO NOTHING''',
                (cid, summary, layer, impact,
                 json.dumps(source_ids, ensure_ascii=False),
                 json.dumps(partners,   ensure_ascii=False),
                 len(matched), ai_summary)
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


@app.get('/')
def root():
    return RedirectResponse(url='/dashboard.html')


# ── Serve frontend static files (must be last) ───────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(__file__), '..')
app.mount('/', StaticFiles(directory=_frontend_dir, html=True), name='frontend')
