import os, re, json, requests
from datetime import datetime, timezone

NOTION_TOKEN  = os.environ.get('NOTION_TOKEN', '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')
REUNIOES_DB   = '39164917ccf180a8b745f6b8bcec71fc'
PROJETOS_DB   = 'e7aa48d0a5c6494987a2e8c95820da45'
ATIVIDADES_DB = '1cc60a6d29fb4c049f8a5332de2fa1db'
GROQ_KEY      = os.environ.get('GROQ_KEY', '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')

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

def date(prop):
    if not prop: return ''
    d = prop.get('date')
    return d.get('start','') if d else ''

def rel_ids(prop):
    if not prop: return []
    return [r['id'] for r in prop.get('relation', [])]

def query_db(db_id):
    url = f'https://api.notion.com/v1/databases/{db_id}/query'
    rows, cursor = [], None
    print(f'  Querying {db_id[:8]}...')
    while True:
        payload = {'page_size': 100}
        if cursor: payload['start_cursor'] = cursor
        r = requests.post(url, headers=H, json=payload)
        if r.status_code != 200:
            print(f'  ERRO {r.status_code}: {r.text[:200]}')
            return []
        data = r.json()
        if data.get('object') == 'error':
            print(f'  NOTION ERRO: {data.get("code")} - {data.get("message")}')
            return []
        rows.extend(data.get('results', []))
        print(f'  -> {len(rows)} registros até agora')
        if not data.get('has_more'): break
        cursor = data.get('next_cursor')
    return rows

def suggest_title_ai(transcricao, resumo):
    """Sugere título via Groq a partir da transcrição/resumo."""
    content = transcricao or resumo or ''
    if not content or is_short(content): return ''
    content = content[:800]
    try:
        r = requests.post('https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_KEY}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile', 'max_tokens': 30,
                  'messages': [{'role': 'user', 'content': f'Com base neste conteúdo de reunião, crie um título curto e descritivo (máximo 8 palavras, sem aspas, em português): {content}'}]},
            timeout=8)
        return r.json()['choices'][0]['message']['content'].strip().strip('"').strip("'")
    except: return ''

def extract_speakers(transcricao):
    """Extrai lista de speakers da transcrição."""
    if not transcricao: return []
    speakers = list(dict.fromkeys(re.findall(r'Speaker \d+', transcricao)))
    return speakers

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
        'reunioes_ids': rel_ids(p['properties'].get('Reuniões')),
    } for p in rows]

def fetch_atividades():
    rows = query_db(ATIVIDADES_DB)
    now = datetime.now(timezone.utc)
    atividades = []
    for a in rows:
        props = a['properties']
        prazo_str = date(props.get('Prazo'))
        status = sel(props.get('Status')) or 'Não iniciada'
        proj_ids = rel_ids(props.get('Projeto'))

        # Calcular dias parada
        dias_parada = None
        if status in ('Bloqueada', 'Aguardando'):
            try:
                updated = datetime.fromisoformat(a.get('last_edited_time','').replace('Z','+00:00'))
                if not updated.tzinfo: updated = updated.replace(tzinfo=timezone.utc)
                dias_parada = (now - updated).days
            except: pass

        # Prazo vencido
        prazo_vencido = False
        if prazo_str and status not in ('Concluída',):
            try:
                prazo_dt = datetime.fromisoformat(prazo_str)
                if not prazo_dt.tzinfo: prazo_dt = prazo_dt.replace(tzinfo=timezone.utc)
                prazo_vencido = prazo_dt < now
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
            'depende_de': plain(props.get('Depende de')),
            'aguardando': plain(props.get('O que está aguardando')),
            'observacoes': plain(props.get('Observações')),
            'reunioes_ids': rel_ids(props.get('Reuniões')),
            'dias_parada': dias_parada,
        })
    return atividades

def fetch_reunioes(projetos, atividades):
    rows = query_db(REUNIOES_DB)
    proj_map = {p['id']: p['nome'] for p in projetos}
    proj_names = [p['nome'] for p in projetos if p['nome']]
    reunioes = []

    for page in rows:
        props = page['properties']
        pid = page['id']

        # Título
        titulo_raw = plain(props.get('Título'))
        titulo_editado = plain(props.get('Título editado'))
        transcricao = plain(props.get('Transcrição',''))
        resumo_raw = plain(props.get('Resumo IA',''))

        # Resumo limpo
        if is_short(resumo_raw):
            resumo = transcricao if transcricao and not is_short(transcricao) else ''
            resumo_display = resumo[:300] if resumo else '⏱ Gravação muito curta.'
        else:
            resumo = resumo_raw
            resumo_display = resumo

        # Título sugerido por IA se não tiver título editado
        titulo_ia = ''
        if not titulo_editado and (transcricao or resumo):
            titulo_ia = suggest_title_ai(transcricao, resumo)

        titulo_display = titulo_editado or titulo_ia or titulo_raw

        # Speakers
        speakers = extract_speakers(transcricao)

        # Data
        date_str = date(props.get('Data')) or page.get('created_time','')[:10]

        # Status
        status = sel(props.get('Status')) or 'Processando'

        # Projeto
        proj_ids = rel_ids(props.get('Projeto'))
        projeto_id = proj_ids[0] if proj_ids else ''
        projeto_nome = proj_map.get(projeto_id, '')

        # Auto-identificar projeto via IA se não tiver
        if not projeto_id and proj_names:
            content = (transcricao or resumo or '')[:500]
            if content and not is_short(content):
                try:
                    r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {GROQ_KEY}', 'Content-Type': 'application/json'},
                        json={'model': 'llama-3.3-70b-versatile', 'max_tokens': 20,
                              'messages': [{'role': 'user', 'content': f'Projetos: {", ".join(proj_names)}. Texto: {content}. Qual projeto? Responda só o nome exato ou NENHUM.'}]},
                        timeout=8)
                    ans = r.json()['choices'][0]['message']['content'].strip()
                    if ans != 'NENHUM' and ans in proj_names:
                        match = next((p for p in projetos if p['nome'] == ans), None)
                        if match:
                            projeto_id = match['id']
                            projeto_nome = match['nome']
                            requests.patch(f'https://api.notion.com/v1/pages/{pid}', headers=H,
                                json={'properties': {'Projeto': {'relation': [{'id': projeto_id}]}}})
                            print(f'  Auto-vinculado: {titulo_display} → {projeto_nome}')
                except: pass

        # Salvar título IA no Notion se não tinha
        if titulo_ia and not titulo_editado:
            try:
                requests.patch(f'https://api.notion.com/v1/pages/{pid}', headers=H,
                    json={'properties': {'Título editado': {'rich_text': [{'text': {'content': titulo_ia}}]}}})
            except: pass

        # Participantes
        participantes_str = plain(props.get('Participantes',''))
        participantes = [p.strip() for p in participantes_str.split(',') if p.strip()] if participantes_str else []

        # Atividades vinculadas
        ativ_ids = [a['id'] for a in atividades if pid in a.get('reunioes_ids', [])]

        reunioes.append({
            'id': pid,
            'titulo_raw': titulo_raw,
            'titulo_editado': titulo_editado,
            'titulo_ia': titulo_ia,
            'title': titulo_display,
            'date': date_str,
            'status': status,
            'projeto_id': projeto_id,
            'projeto': projeto_nome,
            'summary': resumo_display,
            'actions': plain(props.get('Action Items','')),
            'transcricao': transcricao,
            'participantes': participantes,
            'speakers': speakers,
            'sem_projeto': not bool(projeto_id),
            'atividades_ids': ativ_ids,
        })

    reunioes.sort(key=lambda m: m['date'], reverse=True)
    return reunioes

def main():
    print('Token:', NOTION_TOKEN[:20]+'...')
    print('Buscando projetos...')
    projetos = fetch_projetos()
    print(f'  {len(projetos)} projetos encontrados')
    print('Buscando atividades...')
    atividades = fetch_atividades()
    print(f'  {len(atividades)} atividades encontradas')
    print('Buscando reunioes...')
    reunioes = fetch_reunioes(projetos, atividades)
    print(f'  {len(reunioes)} reunioes encontradas')

    now = datetime.now(timezone.utc)
    week = 0
    for m in reunioes:
        if m['date']:
            try:
                dt = datetime.fromisoformat(m['date'].replace('Z','+00:00'))
                if not dt.tzinfo: dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).days <= 7: week += 1
            except: pass

    done = sum(1 for m in reunioes if 'conclu' in m['status'].lower())
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(r'var MEETINGS\s*=\s*\[[\s\S]*?\];',
        lambda _: 'var MEETINGS = ' + json.dumps(reunioes, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var PROJECTS\s*=\s*\[[\s\S]*?\];',
        lambda _: 'var PROJECTS = ' + json.dumps(projetos, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'var TASKS\s*=\s*\[[\s\S]*?\];',
        lambda _: 'var TASKS = ' + json.dumps(atividades, ensure_ascii=False, indent=2) + ';', html)
    html = re.sub(r'(GRUPO HOLSA\s*·\s*Central de Intelig[^\n<]*)',
        f'GRUPO HOLSA · Central de Inteligencia · Atualizado: {updated}', html)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Dashboard atualizado: {len(reunioes)} reunioes | {week} esta semana | {done} concluidas | {len(projetos)} projetos | {len(atividades)} atividades')

if __name__ == '__main__':
    main()
