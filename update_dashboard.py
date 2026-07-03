import os
import json
import re
import urllib.request
import urllib.error
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
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_text(prop):
    if not prop:
        return ''
    if isinstance(prop, dict):
        if prop.get('type') == 'title':
            return ''.join(t.get('plain_text','') for t in prop.get('title',[]))
        if prop.get('type') == 'rich_text':
            raw = ''.join(t.get('plain_text','') for t in prop.get('rich_text',[]))
            return strip_html(raw)
        if prop.get('type') == 'select':
            return (prop.get('select') or {}).get('name','')
        if prop.get('type') == 'status':
            return (prop.get('status') or {}).get('name','')
        if prop.get('type') == 'date':
            return (prop.get('date') or {}).get('start','')
    return ''

def fetch_meetings():
    url = f'https://api.notion.com/v1/databases/{DB_ID}/query'
    data = {'page_size': 100, 'sorts': [{'property': 'Data', 'direction': 'descending'}]}
    result = notion_request(url, 'POST', data)
    meetings = []
    for page in result.get('results', []):
        props = page.get('properties', {})
        title = get_text(props.get('Título') or props.get('title', {}))
        if not title:
            title = page.get('id', '')
        meetings.append({
            'id': page['id'].replace('-',''),
            'title': title,
            'date': get_text(props.get('Data', {})),
            'project': get_text(props.get('Projeto', {})),
            'status': get_text(props.get('Status', {})),
            'summary': strip_html(get_text(props.get('Resumo IA', {}))),
            'actionItems': strip_html(get_text(props.get('Action Items', {}))),
            'transcript': strip_html(get_text(props.get('Transcrição', {}))),
            'url': page.get('url', '')
        })
    return meetings

def fmt_date(iso):
    if not iso:
        return '—'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return iso

def meetings_to_js(meetings):
    lines = []
    for m in meetings:
        def esc(s):
            return (s or '').replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\r', '')
        lines.append(
            "  {id:'" + esc(m['id']) + "',"
            "title:'" + esc(m['title']) + "',"
            "date:'" + esc(m['date']) + "',"
            "project:'" + esc(m['project']) + "',"
            "status:'" + esc(m['status']) + "',"
            "summary:'" + esc(m['summary'][:300]) + "',"
            "actionItems:'" + esc(m['actionItems'][:300]) + "',"
            "transcript:'" + esc(m['transcript'][:200]) + "',"
            "url:'" + esc(m['url']) + "'}"
        )
    return '[\n' + ',\n'.join(lines) + '\n]'

def build_kpis(meetings):
    total = len(meetings)
    now = datetime.now(timezone.utc)
    week = sum(1 for m in meetings if m['date'] and (now - datetime.fromisoformat(m['date'].replace('Z','+00:00'))).days <= 7 if 'T' in m['date'])
    projects = len(set(m['project'] for m in meetings if m['project']))
    done = sum(1 for m in meetings if m['status'] == 'Concluída')
    rate = f"{int(done/total*100)}%" if total else "0%"
    proj_names = ', '.join(sorted(set(m['project'] for m in meetings if m['project']))) or '—'
    return total, week, projects, rate, proj_names, done

def main():
    print("Buscando reuniões do Notion...")
    meetings = fetch_meetings()
    print(f"Encontradas {len(meetings)} reuniões")
    
    total, week, projects, rate, proj_names, done = build_kpis(meetings)
    meetings_js = meetings_to_js(meetings)
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Update meetings data
    html = re.sub(r'var MEETINGS = \[[\s\S]*?\];', f'var MEETINGS = {meetings_js};', html)
    
    # Update KPIs
    html = re.sub(r'(<div class="kpi"><div class="kpi-label">Total de reuniões</div><div class="kpi-value">)[\d]+(<\/div>)', f'\\g<1>{total}\\2', html)
    html = re.sub(r'(<div class="kpi"><div class="kpi-label">Esta semana</div><div class="kpi-value">)[\d]+(<\/div>)', f'\\g<1>{week}\\2', html)
    html = re.sub(r'(<div class="kpi gold"><div class="kpi-label">Projetos ativos</div><div class="kpi-value">)[\d]+(<\/div>)', f'\\g<1>{projects}\\2', html)
    html = re.sub(r'(<div class="kpi green"><div class="kpi-label">Taxa de conclusão</div><div class="kpi-value">)[^<]+(</div>)', f'\\g<1>{rate}\\2', html)
    html = re.sub(r'(<div class="kpi gold">.*?<div class="kpi-sub">)[^<]+(</div>)', f'\\g<1>{proj_names}\\2', html, flags=re.DOTALL)
    html = re.sub(r'(<div class="kpi green">.*?<div class="kpi-sub">)[^<]+(</div>)', f'\\g<1>{done} de {total} concluídas\\2', html, flags=re.DOTALL)

    # Update last sync info
    html = re.sub(r'Última atualização: [\d\/: ]+', f'Última atualização: {updated}', html)
    if 'Última atualização:' not in html:
        html = html.replace('GRUPO HOLSA · Central de Inteligência · Uso interno e confidencial',
                           f'GRUPO HOLSA · Central de Inteligência · Uso interno e confidencial · Última atualização: {updated}')

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard atualizado: {total} reuniões, {week} esta semana, taxa {rate}")

if __name__ == '__main__':
    main()
