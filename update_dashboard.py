import os
import json
import re
import urllib.request
from datetime import datetime, timezone

NOTION_TOKEN = os.environ.get('NOTION_TOKEN', '')
DB_ID = '39164917ccf180a8b745f6b8bcec71fc'

def notion_request(url, method='GET', data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', f'Bearer {NOTION_TOKEN}')
    req.add_header('Notion-Version', '2022-06-28')
    req.add_header('Content-Type', 'application/json')
    if data:
        req.data = json.dumps(data).encode()
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def strip_html(text):
    if not text:
        return ''
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    text = re.sub(r'\s+', ' ', text).strip()
    if '{' in text and ';' in text:
        lines = [l.strip() for l in re.split(r'[.!?]', text) if len(l.strip()) > 20 and '{' not in l]
        text = '. '.join(lines[:3]).strip()
    return text[:400]

def get_text(prop):
    if not prop:
        return ''
    t = prop.get('type', '')
    if t == 'title':
        return ''.join(x.get('plain_text', '') for x in prop.get('title', []))
    if t == 'rich_text':
        raw = ''.join(x.get('plain_text', '') for x in prop.get('rich_text', []))
        return strip_html(raw)
    if t == 'select':
        return (prop.get('select') or {}).get('name', '')
    if t == 'status':
        return (prop.get('status') or {}).get('name', '')
    if t == 'date':
        return (prop.get('date') or {}).get('start', '')
    return ''

def fetch_meetings():
    url = f'https://api.notion.com/v1/databases/{DB_ID}/query'
    data = {'page_size': 100, 'sorts': [{'property': 'Data', 'direction': 'descending'}]}
    result = notion_request(url, 'POST', data)
    meetings = []
    for page in result.get('results', []):
        props = page.get('properties', {})
        title = get_text(props.get('Titulo') or props.get('Título') or props.get('title', {}))
        if not title:
            title = page.get('id', '')
        meetings.append({
            'id': page['id'],  # Keep full UUID with dashes
            'title': title,
            'date': get_text(props.get('Data', {})),
            'project': get_text(props.get('Projeto', {})),
            'status': get_text(props.get('Status', {})),
            'summary': get_text(props.get('Resumo IA', {})),
            'actionItems': get_text(props.get('Action Items', {})),
            'transcript': strip_html(get_text(props.get('Transcricao') or props.get('Transcrição', {}))),
            'url': page.get('url', '').replace('https://www.notion.so/', 'https://app.notion.com/p/').replace('-', '')
        })
    return meetings

def esc(s):
    return (s or '').replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\r', '').replace('"', '&quot;')

def meetings_to_js(meetings):
    lines = []
    for m in meetings:
        lines.append(
            "  {id:'" + esc(m['id']) + "',"
            "title:'" + esc(m['title']) + "',"
            "date:'" + esc(m['date']) + "',"
            "project:'" + esc(m['project']) + "',"
            "status:'" + esc(m['status']) + "',"
            "summary:'" + esc(m['summary']) + "',"
            "actionItems:'" + esc(m['actionItems']) + "',"
            "transcript:'" + esc(m['transcript'][:200]) + "',"
            "url:'" + esc(m['url']) + "'}"
        )
    return '[\n' + ',\n'.join(lines) + '\n]'

def main():
    print("Buscando reunioes do Notion...")
    meetings = fetch_meetings()
    print(f"Encontradas {len(meetings)} reunioes")

    total = len(meetings)
    now = datetime.now(timezone.utc)
    week = 0
    for m in meetings:
        if m['date'] and 'T' in m['date']:
            try:
                dt = datetime.fromisoformat(m['date'].replace('Z', '+00:00'))
                if (now - dt).days <= 7:
                    week += 1
            except:
                pass
    projects = len(set(m['project'] for m in meetings if m['project']))
    done = sum(1 for m in meetings if m['status'] in ['Concluida', 'Concluída'])
    rate = f"{int(done/total*100)}%" if total else "0%"
    proj_names = ', '.join(sorted(set(m['project'] for m in meetings if m['project']))) or '—'
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')
    meetings_js = meetings_to_js(meetings)

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(r'var MEETINGS = \[[\s\S]*?\];', f'var MEETINGS = {meetings_js};', html)
    html = html.replace('GRUPO HOLSA \u00b7 Central de Intelig\u00eancia \u00b7 Uso interno e confidencial',
                        f'GRUPO HOLSA \u00b7 Central de Intelig\u00eancia \u00b7 Atualizado: {updated}')

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard atualizado: {total} reunioes, {week} esta semana, taxa {rate}")

if __name__ == '__main__':
    main()
