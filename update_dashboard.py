import os
import re
import json
import requests
from datetime import datetime, timezone

NOTION_TOKEN = os.environ.get('NOTION_TOKEN', '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')
DATABASE_ID = '39164917ccf180a8b745f6b8bcec71fc'

HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

SHORT_PATTERNS = [
    'a transcri',
    'speaker 1',
    'speaker 2',
    '00:00:0',
    'nao e necessario',
]

def is_short_recording(text):
    lower = text.lower()
    return any(p in lower for p in SHORT_PATTERNS)

def strip_html(text):
    if not text:
        return ''
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[\s\S]*?</head>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    for ent, char in [('&amp;','&'),('&lt;','<'),('&gt;','>'),('&quot;','"'),('&#39;',"'"),('&nbsp;',' ')]:
        text = text.replace(ent, char)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_plain(prop):
    if not prop:
        return ''
    items = prop.get('rich_text') or prop.get('title') or []
    parts = [item.get('plain_text') or item.get('text', {}).get('content', '') for item in items]
    return strip_html(' '.join(parts))

def get_select(prop):
    if not prop:
        return ''
    sel = prop.get('select')
    return sel.get('name', '') if sel else ''

def get_date(prop):
    if not prop:
        return ''
    d = prop.get('date')
    return d.get('start', '') if d else ''

def fetch_meetings():
    url = f'https://api.notion.com/v1/databases/{DATABASE_ID}/query'
    meetings = []
    cursor = None
    while True:
        payload = {'page_size': 100}
        if cursor:
            payload['start_cursor'] = cursor
        resp = requests.post(url, headers=HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get('results', []):
            props = page.get('properties', {})
            page_id = page.get('id', '')

            # Titulo
            title = ''
            for k in ['Nome', 'Name', 'Titulo', 'Title', 'Reuniao']:
                if k in props:
                    title = get_plain(props[k])
                    if title: break
            if not title:
                for k, v in props.items():
                    if v.get('type') == 'title':
                        title = get_plain(v)
                        break

            # Data
            date_str = ''
            for k in ['Data', 'Date', 'Criado em', 'Created']:
                if k in props:
                    date_str = get_date(props[k])
                    if date_str: break
            if not date_str:
                date_str = page.get('created_time', '')[:10]

            # Status
            status = ''
            for k in ['Status', 'Estado']:
                if k in props:
                    status = get_select(props[k])
                    if status: break

            # Projeto
            project = ''
            for k in ['Projeto', 'Project', 'Categoria']:
                if k in props:
                    project = get_select(props[k])
                    if project: break

            # Resumo — tenta Resumo IA primeiro, depois outros
            summary = ''
            for k in ['Resumo IA', 'Resumo', 'Summary', 'Notas', 'Notes']:
                if k in props:
                    raw = get_plain(props[k])
                    if raw:
                        if is_short_recording(raw):
                            summary = '\u23f1 Gravacao muito curta para gerar resumo.'
                        else:
                            summary = raw
                        break

            # Action Items
            actions = ''
            for k in ['Action Items', 'Acoes', 'Proximos Passos', 'Next Steps', 'Tarefas']:
                if k in props:
                    raw = get_plain(props[k])
                    if raw:
                        if is_short_recording(raw):
                            actions = ''
                        else:
                            actions = raw
                        break

            meetings.append({
                'id': page_id,
                'title': title or f'Reuniao {date_str}',
                'date': date_str,
                'status': status or 'Pendente',
                'project': project or '',
                'summary': summary,
                'actions': actions,
            })

        if not data.get('has_more'):
            break
        cursor = data.get('next_cursor')

    meetings.sort(key=lambda m: m['date'], reverse=True)
    return meetings

def main():
    print('Buscando reunioes do Notion...')
    meetings = fetch_meetings()
    total = len(meetings)
    print(f'Total: {total} reunioes')

    week = 0
    now = datetime.now(timezone.utc)
    for m in meetings:
        if m['date']:
            try:
                dt = datetime.fromisoformat(m['date'].replace('Z', '+00:00'))
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).days <= 7:
                    week += 1
            except Exception:
                pass

    done = sum(1 for m in meetings if m['status'].lower() in ['concluida', 'concluida', 'done', 'completed'])
    rate = f"{int(done / total * 100)}%" if total else "0%"
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')
    meetings_js = json.dumps(meetings, ensure_ascii=False, indent=2)

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(r'var MEETINGS = \[[\s\S]*?\];', f'var MEETINGS = {meetings_js};', html)
    html = re.sub(
        r'(GRUPO HOLSA\s*·\s*Central de Intelig[^\n<]*)',
        f'GRUPO HOLSA · Central de Inteligencia · Atualizado: {updated}',
        html
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Dashboard atualizado: {total} reunioes | {week} esta semana | taxa {rate}')

if __name__ == '__main__':
    main()
