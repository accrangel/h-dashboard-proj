import os
import re
import json
import requests
from datetime import datetime, timezone

NOTION_TOKEN = os.environ.get('NOTION_TOKEN', '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')
REUNIOES_DB  = '39164917ccf180a8b745f6b8bcec71fc'
PROJETOS_DB  = 'e7aa48d0a5c6494987a2e8c95820da45'
GROQ_KEY     = os.environ.get('GROQ_KEY', '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')

HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

SHORT_PATTERNS = ['a transcri', 'speaker 1', 'speaker 2', '00:00:0', 'nao e necessario']

def is_short(text):
    lower = text.lower()
    return any(p in lower for p in SHORT_PATTERNS)

def strip_html(text):
    if not text: return ''
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[\s\S]*?</head>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    for ent, ch in [('&amp;','&'),('&lt;','<'),('&gt;','>'),('&quot;','"'),('&#39;',"'"),('&nbsp;',' ')]:
        text = text.replace(ent, ch)
    return re.sub(r'\s+', ' ', text).strip()

def get_plain(prop):
    if not prop: return ''
    items = prop.get('rich_text') or prop.get('title') or []
    return strip_html(' '.join(i.get('plain_text','') for i in items))

def get_select(prop):
    if not prop: return ''
    sel = prop.get('select') or prop.get('status')
    return sel.get('name','') if sel else ''

def get_date(prop):
    if not prop: return ''
    d = prop.get('date')
    return d.get('start','') if d else ''

def get_relation_ids(prop):
    if not prop: return []
    return [r.get('id','') for r in prop.get('relation', [])]

def identify_project_with_ai(title, transcription, project_names):
    """Usa Groq para identificar projeto mencionado na reunião."""
    if not project_names or not (title or transcription):
        return None
    text = f"Título: {title}\nTranscrição: {(transcription or '')[:500]}"
    prompt = f"""Analise o texto abaixo e identifique qual projeto está sendo discutido.
Projetos existentes: {', '.join(project_names)}

Texto:
{text}

Responda APENAS com o nome exato do projeto da lista acima se identificado com alta confiança, ou "NENHUM" se não for possível identificar. Nada mais."""
    try:
        r = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_KEY}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile', 'max_tokens': 50,
                  'messages': [{'role': 'user', 'content': prompt}]},
            timeout=10
        )
        answer = r.json()['choices'][0]['message']['content'].strip()
        if answer != 'NENHUM' and answer in project_names:
            return answer
    except Exception as e:
        print(f'Groq error: {e}')
    return None

def fetch_projetos():
    url = f'https://api.notion.com/v1/databases/{PROJETOS_DB}/query'
    projetos = []
    cursor = None
    while True:
        payload = {'page_size': 100}
        if cursor: payload['start_cursor'] = cursor
        r = requests.post(url, headers=HEADERS, json=payload)
        r.raise_for_status()
        data = r.json()
        for page in data.get('results', []):
            props = page.get('properties', {})
            projetos.append({
                'id': page['id'],
                'nome': get_plain(props.get('Nome')),
                'status': get_select(props.get('Status')),
                'area': get_select(props.get('Área')),
                'responsavel': get_plain(props.get('Responsável')),
                'descricao': get_plain(props.get('Descrição')),
                'reunioes': get_relation_ids(props.get('Reuniões')),
            })
        if not data.get('has_more'): break
        cursor = data.get('next_cursor')
    return projetos

def fetch_reunioes(projetos):
    url = f'https://api.notion.com/v1/databases/{REUNIOES_DB}/query'
    reunioes = []
    cursor = None
    projeto_map = {p['id']: p['nome'] for p in projetos}
    projeto_names = [p['nome'] for p in projetos if p['nome']]

    while True:
        payload = {'page_size': 100}
        if cursor: payload['start_cursor'] = cursor
        r = requests.post(url, headers=HEADERS, json=payload)
        r.raise_for_status()
        data = r.json()

        for page in data.get('results', []):
            props = page.get('properties', {})
            page_id = page['id']

            title = ''
            for k in ['Título', 'Nome', 'Title', 'Name']:
                if k in props:
                    title = get_plain(props[k])
                    if title: break
            if not title:
                for k, v in props.items():
                    if v.get('type') == 'title':
                        title = get_plain(v); break

            date_str = get_date(props.get('Data')) or page.get('created_time','')[:10]
            status = get_select(props.get('Status')) or 'Processando'

            # Projeto via relation
            proj_ids = get_relation_ids(props.get('Projeto'))
            projeto_nome = projeto_map.get(proj_ids[0], '') if proj_ids else ''
            projeto_id = proj_ids[0] if proj_ids else ''

            # Resumo
            summary = ''
            transcricao = get_plain(props.get('Transcrição', {}))
            for k in ['Resumo IA', 'Resumo', 'Summary']:
                if k in props:
                    raw = get_plain(props[k])
                    if raw:
                        if is_short(raw):
                            summary = transcricao if transcricao and not is_short(transcricao) else '\u23f1 Gravacao muito curta para gerar resumo.'
                        else:
                            summary = raw
                        break

            # Action Items
            actions = ''
            for k in ['Action Items', 'Acoes']:
                if k in props:
                    raw = get_plain(props[k])
                    if raw and not is_short(raw):
                        actions = raw; break

            # Auto-identificar projeto via IA se não tiver
            if not projeto_id and projeto_names:
                identified = identify_project_with_ai(title, transcricao or summary, projeto_names)
                if identified:
                    projeto_nome = identified
                    match = next((p for p in projetos if p['nome'] == identified), None)
                    if match:
                        projeto_id = match['id']
                        # Vincula no Notion
                        try:
                            requests.patch(
                                f'https://api.notion.com/v1/pages/{page_id}',
                                headers=HEADERS,
                                json={'properties': {'Projeto': {'relation': [{'id': projeto_id}]}}}
                            )
                            print(f'  Auto-vinculado: {title} → {projeto_nome}')
                        except Exception as e:
                            print(f'  Erro ao vincular: {e}')

            reunioes.append({
                'id': page_id,
                'title': title or f'Reuniao {date_str}',
                'date': date_str,
                'status': status,
                'projeto_id': projeto_id,
                'projeto': projeto_nome,
                'summary': summary,
                'actions': actions,
                'sem_projeto': not bool(projeto_id),
            })

        if not data.get('has_more'): break
        cursor = data.get('next_cursor')

    reunioes.sort(key=lambda m: m['date'], reverse=True)
    return reunioes

def main():
    print('Buscando projetos...')
    projetos = fetch_projetos()
    print(f'  {len(projetos)} projetos')

    print('Buscando reunioes...')
    reunioes = fetch_reunioes(projetos)
    total = len(reunioes)
    print(f'  {total} reunioes')

    now = datetime.now(timezone.utc)

    # Semana corrigida
    week = 0
    for m in reunioes:
        if m['date']:
            try:
                dt = datetime.fromisoformat(m['date'].replace('Z','+00:00'))
                if not dt.tzinfo: dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).days <= 7: week += 1
            except: pass

    done = sum(1 for m in reunioes if m['status'].lower() in ['concluída','concluida','done','completed'])
    sem_projeto = sum(1 for m in reunioes if m['sem_projeto'])
    proj_ativos = [p for p in projetos if p['status'] == 'Ativo']
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')

    reunioes_js = json.dumps(reunioes, ensure_ascii=False, indent=2)
    projetos_js = json.dumps(projetos, ensure_ascii=False, indent=2)

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(r'var MEETINGS = \[[\s\S]*?\];', f'var MEETINGS = {reunioes_js};', html)
    html = re.sub(r'var PROJECTS = \[[\s\S]*?\];', f'var PROJECTS = {projetos_js};', html)
    html = re.sub(
        r'(GRUPO HOLSA\s*·\s*Central de Intelig[^\n<]*)',
        f'GRUPO HOLSA · Central de Inteligencia · Atualizado: {updated}',
        html
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Dashboard atualizado: {total} reunioes | {week} esta semana | {done} concluidas | {sem_projeto} sem projeto | {len(proj_ativos)} projetos ativos')

if __name__ == '__main__':
    main()
