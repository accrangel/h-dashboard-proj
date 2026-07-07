import os, re, json, requests, hashlib
from datetime import datetime, timezone

NOTION_TOKEN  = os.environ.get('NOTION_TOKEN', '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')
REUNIOES_DB   = '39164917ccf180a8b745f6b8bcec71fc'
PROJETOS_DB   = 'e7aa48d0a5c6494987a2e8c95820da45'
ATIVIDADES_DB = '1cc60a6d29fb4c049f8a5332de2fa1db'
HISTORICO_DB  = '0967906a07b648679003d264b924b81a'
GROQ_KEY      = os.environ.get('GROQ_KEY', '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')
SNAPSHOT_FILE = 'snapshot.json'

H = {'Authorization': f'Bearer {NOTION_TOKEN}', 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'}
SHORT = ['a transcri', 'speaker 1', 'speaker 2', '00:00:0', 'nao e necessario']

def is_short(t): return any(p in (t or '').lower() for p in SHORT)

def strip(t):
    if not t: return ''
    t = re.sub(r'<style[\s\S]*?</style>', '', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    for a, b in [('&amp;','&'),('&lt;','<'),('&gt;','>'),('&quot;','"'),('&#39;',"'"),('&nbsp;',' ')]:
        t = t.replace(a, b)
    return re.sub(r'\s+', ' ', t).strip()

def plain(prop):
    if not prop: return ''
    items = prop.get('rich_text') or prop.get('title') or []
    return strip(' '.join(i.get('plain_text','') for i in items))

def sel(prop):
    if not prop: return ''
    s = prop.get('select') or prop.get('status')
    return s.get('name','') if s else ''

def date_val(prop):
    if not prop: return ''
    d = prop.get('date')
    return d.get('start','') if d else ''

def rel_ids(prop):
    if not prop: return []
    return [r['id'] for r in prop.get('relation', [])]

def query_db(db_id):
    url = f'https://api.notion.com/v1/databases/{db_id}/query'
    rows, cursor = [], None
    while True:
        payload = {'page_size': 100}
        if cursor: payload['start_cursor'] = cursor
        r = requests.post(url, headers=H, json=payload)
        if r.status_code != 200:
            print(f'  ERRO {r.status_code} em {db_id[:8]}: {r.text[:150]}')
            return []
        data = r.json()
        if data.get('object') == 'error':
            print(f'  NOTION ERRO: {data.get("message")}')
            return []
        rows.extend(data.get('results', []))
        if not data.get('has_more'): break
        cursor = data.get('next_cursor')
    return rows

def registrar_historico(entidade, entidade_id, entidade_nome, campo, valor_ant, valor_novo, origem='Sistema'):
    if valor_ant == valor_novo: return
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    descricao = f'{entidade_nome}: {campo} alterado'
    props = {
        'Descrição': {'title': [{'text': {'content': descricao[:100]}}]},
        'Entidade': {'select': {'name': entidade}},
        'Entidade ID': {'rich_text': [{'text': {'content': entidade_id}}]},
        'Entidade Nome': {'rich_text': [{'text': {'content': entidade_nome[:200]}}]},
        'Campo': {'rich_text': [{'text': {'content': campo}}]},
        'Valor anterior': {'rich_text': [{'text': {'content': str(valor_ant)[:500]}}]},
        'Valor novo': {'rich_text': [{'text': {'content': str(valor_novo)[:500]}}]},
        'Alterado por': {'select': {'name': origem}},
        'Data': {'date': {'start': now}},
    }
    try:
        requests.post('https://api.notion.com/v1/pages', headers=H,
            json={'parent': {'database_id': HISTORICO_DB}, 'properties': props})
    except Exception as e:
        print(f'  Erro ao registrar histórico: {e}')

def load_snapshot():
    try:
        if os.path.exists(SNAPSHOT_FILE):
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
    except: pass
    return {}

def save_snapshot(data):
    try:
        with open(SNAPSHOT_FILE, 'w') as f:
            json.dump(data, f)
    except: pass

def detect_changes(snapshot, current_items, entity_type, tracked_fields):
    for item in current_items:
        eid = item['id']
        nome = item.get('nome') or item.get('title') or ''
        prev = snapshot.get(eid, {})
        for field in tracked_fields:
            v_new = str(item.get(field, '') or '')
            v_old = str(prev.get(field, '') or '')
            if v_old and v_new != v_old:
                registrar_historico(entity_type, eid, nome, field, v_old, v_new, 'Notion')
        snapshot[eid] = {f: str(item.get(f,'') or '') for f in tracked_fields}

def groq_call(prompt, max_tokens=80):
    try:
        r = requests.post('https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_KEY}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile', 'max_tokens': max_tokens,
                  'messages': [{'role': 'user', 'content': prompt}]}, timeout=10)
        return r.json()['choices'][0]['message']['content'].strip()
    except: return ''

def fetch_historico():
    rows = query_db(HISTORICO_DB)
    hist = []
    for r in rows:
        p = r['properties']
        hist.append({
            'id': r['id'],
            'descricao': plain(p.get('Descrição')),
            'entidade': sel(p.get('Entidade')),
            'entidade_id': plain(p.get('Entidade ID')),
            'entidade_nome': plain(p.get('Entidade Nome')),
            'campo': plain(p.get('Campo')),
            'valor_anterior': plain(p.get('Valor anterior')),
            'valor_novo': plain(p.get('Valor novo')),
            'alterado_por': sel(p.get('Alterado por')),
            'data': date_val(p.get('Data')),
            'created': r.get('created_time','')[:10],
        })
    hist.sort(key=lambda x: x.get('created',''), reverse=True)
    return hist[:200]

def fetch_projetos():
    rows = query_db(PROJETOS_DB)
    return [{
        'id': p['id'],
        'nome': plain(p['properties'].get('Nome')),
        'status': sel(p['properties'].get('Status')),
        'area': sel(p['properties'].get('Área')),
        'responsavel': plain(p['properties'].get('Responsável')),
        'descricao': plain(p['properties'].get('Descrição')),
        'atividades_ids': rel_ids(p['properties'].get('Atividades')),
    } for p in rows]

def fetch_atividades():
    rows = query_db(ATIVIDADES_DB)
    now = datetime.now(timezone.utc)
    atividades = []
    for a in rows:
        props = a['properties']
        prazo_str = date_val(props.get('Prazo'))
        status = sel(props.get('Status')) or 'Não iniciada'
        proj_ids = rel_ids(props.get('Projeto'))
        dias_parada = None
        if status in ('Bloqueada', 'Aguardando'):
            try:
                updated = datetime.fromisoformat(a.get('last_edited_time','').replace('Z','+00:00'))
                if not updated.tzinfo: updated = updated.replace(tzinfo=timezone.utc)
                dias_parada = (now - updated).days
            except: pass
        prazo_vencido = False
        dias_atraso = 0
        if prazo_str and status not in ('Concluída',):
            try:
                prazo_dt = datetime.fromisoformat(prazo_str)
                if not prazo_dt.tzinfo: prazo_dt = prazo_dt.replace(tzinfo=timezone.utc)
                if prazo_dt < now:
                    prazo_vencido = True
                    dias_atraso = (now - prazo_dt).days
            except: pass
        atividades.append({
            'id': a['id'],
            'nome': plain(props.get('Nome')),
            'status': status,
            'projeto_id': proj_ids[0] if proj_ids else '',
            'responsavel': plain(props.get('Responsável')),
            'participantes': plain(props.get('Participantes')),
            'prazo': prazo_str,
            'prazo_vencido': prazo_vencido,
            'dias_atraso': dias_atraso,
            'depende_de': plain(props.get('Depende de')),
            'aguardando': plain(props.get('O que está aguardando')),
            'observacoes': plain(props.get('Observações')),
            'reunioes_ids': rel_ids(props.get('Reuniões')),
            'dias_parada': dias_parada,
            'pai_id': rel_ids(props.get('Atividade pai'))[0] if rel_ids(props.get('Atividade pai')) else '',
            'sub_ids': rel_ids(props.get('Sub-atividades')),
            'last_edited': a.get('last_edited_time','')[:10],
        })
    # Deduplicar por nome+projeto (manter mais recente)
    seen = {}
    for a in atividades:
        key = (a['nome'].lower().strip(), a['projeto_id'])
        if key not in seen or a['last_edited'] > seen[key]['last_edited']:
            seen[key] = a
    return list(seen.values())

def fetch_reunioes(projetos, atividades):
    rows = query_db(REUNIOES_DB)
    proj_map = {p['id']: p['nome'] for p in projetos}
    proj_names = [p['nome'] for p in projetos if p['nome']]
    reunioes = []
    for page in rows:
        props = page['properties']
        pid = page['id']
        titulo_editado = plain(props.get('Título editado'))
        transcricao = plain(props.get('Transcrição',''))
        resumo_raw = plain(props.get('Resumo IA',''))
        if is_short(resumo_raw):
            resumo = transcricao if transcricao and not is_short(transcricao) else ''
            resumo_display = resumo[:300] if resumo else '⏱ Gravação muito curta.'
        else:
            resumo = resumo_raw
            resumo_display = resumo
        titulo_raw = plain(props.get('Título'))
        titulo_ia = ''
        if not titulo_editado and (transcricao or resumo):
            titulo_ia = groq_call(f'Crie um título curto (máximo 8 palavras, sem aspas, em português) para esta reunião: {(transcricao or resumo)[:600]}', 30)
            if titulo_ia and not titulo_editado:
                try:
                    requests.patch(f'https://api.notion.com/v1/pages/{pid}', headers=H,
                        json={'properties': {'Título editado': {'rich_text': [{'text': {'content': titulo_ia}}]}}})
                except: pass
        titulo_display = titulo_editado or titulo_ia or titulo_raw
        date_str = date_val(props.get('Data')) or page.get('created_time','')[:10]
        status = sel(props.get('Status')) or 'Processando'
        proj_ids = rel_ids(props.get('Projeto'))
        projeto_id = proj_ids[0] if proj_ids else ''
        projeto_nome = proj_map.get(projeto_id, '')
        if not projeto_id and proj_names and (transcricao or resumo):
            content = (transcricao or resumo or '')[:500]
            if content and not is_short(content):
                ans = groq_call(f'Projetos: {", ".join(proj_names)}. Texto: {content}. Qual projeto? Só o nome exato ou NENHUM.', 20)
                if ans and ans != 'NENHUM' and ans in proj_names:
                    match = next((p for p in projetos if p['nome'] == ans), None)
                    if match:
                        projeto_id = match['id']
                        projeto_nome = match['nome']
                        try:
                            requests.patch(f'https://api.notion.com/v1/pages/{pid}', headers=H,
                                json={'properties': {'Projeto': {'relation': [{'id': projeto_id}]}}})
                        except: pass
        speakers = list(dict.fromkeys(re.findall(r'Speaker \d+', transcricao or '')))
        participantes_str = plain(props.get('Participantes',''))
        participantes = [p.strip() for p in participantes_str.split(',') if p.strip()] if participantes_str else []
        ativ_ids = [a['id'] for a in atividades if pid in a.get('reunioes_ids', [])]
        reunioes.append({
            'id': pid,
            'title': titulo_display,
            'titulo_editado': titulo_editado,
            'titulo_ia': titulo_ia,
            'date': date_str,
            'status': status,
            'projeto_id': projeto_id,
            'projeto': projeto_nome,
            'summary': resumo_display,
            'actions': plain(props.get('Action Items','')),
            'transcricao': transcricao[:500] if transcricao else '',
            'participantes': participantes,
            'speakers': speakers,
            'sem_projeto': not bool(projeto_id),
            'atividades_ids': ativ_ids,
            'last_edited': page.get('last_edited_time','')[:10],
        })
    reunioes.sort(key=lambda m: m['date'], reverse=True)
    return reunioes

def compute_kpis(projetos, atividades, reunioes):
    now = datetime.now(timezone.utc)
    ativos = [p for p in projetos if p['status'] == 'Ativo']
    r_total = len(reunioes)
    r_week = 0
    for m in reunioes:
        if m['date']:
            try:
                dt = datetime.fromisoformat(m['date'].replace('Z','+00:00'))
                if not dt.tzinfo: dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).days <= 7: r_week += 1
            except: pass
    r_concluidas = sum(1 for m in reunioes if 'conclu' in m['status'].lower())
    r_taxa = round(r_concluidas / r_total * 100) if r_total else 0
    a_total = len(atividades)
    a_concluidas = sum(1 for a in atividades if a['status'] == 'Concluída')
    a_andamento = sum(1 for a in atividades if a['status'] == 'Em andamento')
    a_atrasadas = [a for a in atividades if a['prazo_vencido'] and a['status'] != 'Concluída']
    a_bloqueadas = [a for a in atividades if a['status'] in ('Bloqueada', 'Aguardando')]
    a_sem_prazo = sum(1 for a in atividades if not a['prazo'] and a['status'] not in ('Concluída',))
    sla = round(a_concluidas / a_total * 100) if a_total else 0
    workload = {}
    for a in atividades:
        if a['responsavel'] and a['status'] != 'Concluída':
            workload[a['responsavel']] = workload.get(a['responsavel'], 0) + 1
    top_workload = sorted(workload.items(), key=lambda x: x[1], reverse=True)[:3]
    lead_times = []
    for a in atividades:
        if a['status'] == 'Concluída' and a['prazo']:
            try:
                prazo = datetime.fromisoformat(a['prazo'].replace('Z','+00:00'))
                if not prazo.tzinfo: prazo = prazo.replace(tzinfo=timezone.utc)
                edited = datetime.fromisoformat((a['last_edited']+'T00:00:00').replace('Z','+00:00'))
                if not edited.tzinfo: edited = edited.replace(tzinfo=timezone.utc)
                lead_times.append(abs((prazo - edited).days))
            except: pass
    lead_time_medio = round(sum(lead_times) / len(lead_times)) if lead_times else 0
    velocidade = round(a_concluidas / 4) if a_concluidas else 0
    return {
        'reunioes': {'total': r_total, 'semana': r_week, 'concluidas': r_concluidas, 'taxa': r_taxa, 'sem_projeto': sum(1 for m in reunioes if m['sem_projeto'])},
        'projetos': {'total': len(projetos), 'ativos': len(ativos)},
        'atividades': {'total': a_total, 'concluidas': a_concluidas, 'andamento': a_andamento, 'sem_prazo': a_sem_prazo,
                       'atrasadas': len(a_atrasadas), 'bloqueadas': len(a_bloqueadas),
                       'atrasadas_detail': [{'id': a['id'], 'nome': a['nome'], 'responsavel': a['responsavel'], 'dias_atraso': a['dias_atraso'], 'observacoes': a['observacoes'], 'projeto_id': a['projeto_id'], 'status': a['status']} for a in a_atrasadas],
                       'bloqueadas_detail': [{'id': a['id'], 'nome': a['nome'], 'responsavel': a['responsavel'], 'dias_parada': a['dias_parada'], 'aguardando': a['aguardando'], 'projeto_id': a['projeto_id']} for a in a_bloqueadas]},
        'metricas': {'sla': sla, 'lead_time': lead_time_medio, 'velocidade': velocidade, 'workload': top_workload},
    }

def main():
    print('Buscando dados...')
    snapshot = load_snapshot()
    projetos = fetch_projetos()
    atividades = fetch_atividades()
    reunioes = fetch_reunioes(projetos, atividades)
    historico = fetch_historico()
    print(f'  {len(projetos)} projetos | {len(atividades)} atividades | {len(reunioes)} reunioes | {len(historico)} historico')
    detect_changes(snapshot.get('projetos',{}), projetos, 'Projeto', ['status','responsavel','area','descricao'])
    detect_changes(snapshot.get('atividades',{}), atividades, 'Atividade', ['status','responsavel','prazo','aguardando','observacoes'])
    detect_changes(snapshot.get('reunioes',{}), reunioes, 'Reunião', ['status','projeto_id'])
    save_snapshot({'projetos': {p['id']: {f: str(p.get(f,'') or '') for f in ['status','responsavel','area','descricao']} for p in projetos},
                   'atividades': {a['id']: {f: str(a.get(f,'') or '') for f in ['status','responsavel','prazo','aguardando','observacoes']} for a in atividades},
                   'reunioes': {m['id']: {f: str(m.get(f,'') or '') for f in ['status','projeto_id']} for m in reunioes}})
    kpis = compute_kpis(projetos, atividades, reunioes)
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')
    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    html = re.sub(r'var MEETINGS\s*=\s*\[[\s\S]*?\];', lambda _: 'var MEETINGS = ' + json.dumps(reunioes, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var PROJECTS\s*=\s*\[[\s\S]*?\];', lambda _: 'var PROJECTS = ' + json.dumps(projetos, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var TASKS\s*=\s*\[[\s\S]*?\];', lambda _: 'var TASKS = ' + json.dumps(atividades, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var HISTORICO\s*=\s*\[[\s\S]*?\];', lambda _: 'var HISTORICO = ' + json.dumps(historico, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var KPIS\s*=\s*\{[\s\S]*?\};', lambda _: 'var KPIS = ' + json.dumps(kpis, ensure_ascii=False) + ';', html)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Dashboard atualizado: {updated}')

if __name__ == '__main__':
    main()
