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


def strip_html(text):
    if not text:
        return ''
    # Remove blocos inteiros de style/script/head
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head[\s\S]*?</head>', '', text, flags=re.IGNORECASE)
    # Remove todas as tags HTML
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decodifica entidades HTML
    replacements = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
        '&#39;': "'", '&nbsp;': ' ', '&apos;': "'"
    }
    for ent, char in replacements.items():
        text = text.replace(ent, char)
    # Limpa espaços
    text = re.sub(r'\s+', ' ', text).strip()
    # Detecta e remove CSS residual (linhas com { } e ;)
    lines = text.split('.')
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Pula linhas que parecem CSS: têm { } com ; dentro
        if re.search(r'\{[^}]*;[^}]*\}', line):
            continue
        # Pula linhas que são claramente propriedades CSS soltas
        if re.match(r'^[\w-]+\s*:\s*[^:]+;', line):
            continue
        if len(line) > 15:
            clean_lines.append(line)
    if clean_lines:
        return '. '.join(clean_lines[:5]).strip()
    return text


def clean_summary(text):
    """Detecta transcrições brutas ou gravações curtas e substitui por mensagem amigável."""
    if not text:
        return ''
    lower = text.lower()
    short_patterns = [
        'a transcricao e breve',
        'nao e necessario resumo',
        'a transcrição é breve',
        'não é necessário resumo',
        'speaker 1',
        'speaker 2',
        '00:00:0',
    ]
    if any(p in lower for p in short_patterns):
        return '⏱ Gravação muito curta para gerar resumo.'
    return text


def get_rich_text(prop):
    """Extrai texto puro de propriedade rich_text ou title do Notion."""
    if not prop:
        return ''
    items = prop.get('rich_text') or prop.get('title') or []
    parts = []
    for item in items:
        content = item.get('plain_text') or item.get('text', {}).get('content', '')
        parts.append(content)
    return strip_html(' '.join(parts))


def get_select(prop):
    if not prop:
        return ''
    sel = prop.get('select')
    return sel.get('name', '') if sel else ''


def get_date(prop):
    if not prop:
        return ''
    date = prop.get('date')
    if not date:
        return ''
    return date.get('start', '')


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

            # Título — tenta vários nomes comuns
            title = ''
            for key in ['Nome', 'Name', 'Título', 'Title', 'Reunião']:
                if key in props:
                    title = get_rich_text(props[key])
                    if title:
                        break
            if not title:
                # Pega o primeiro campo tipo title
                for key, val in props.items():
                    if val.get('type') == 'title':
                        title = get_rich_text(val)
                        break

            # Data
            date_str = ''
            for key in ['Data', 'Date', 'Criado em', 'Created']:
                if key in props:
                    date_str = get_date(props[key])
                    if date_str:
                        break
            if not date_str:
                date_str = page.get('created_time', '')[:10]

            # Status
            status = ''
            for key in ['Status', 'Estado']:
                if key in props:
                    status = get_select(props[key])
                    if status:
                        break

            # Projeto
            project = ''
            for key in ['Projeto', 'Project', 'Categoria']:
                if key in props:
                    project = get_select(props[key])
                    if project:
                        break

            # Resumo — campos reais do Notion HOLSA
            summary = ''
            for key in ['Resumo IA', 'Resumo', 'Summary', 'Notas', 'Notes']:
                if key in props:
                    raw = get_rich_text(props[key])
                    if raw:
                        summary = clean_summary(raw)
                        break

            # Action Items
            actions = ''
            for key in ['Action Items', 'Ações', 'Próximos Passos', 'Next Steps', 'Tarefas']:
                if key in props:
                    raw = get_rich_text(props[key])
                    if raw:
                        actions = clean_summary(raw)
                        break

            meetings.append({
                'id': page_id,
                'title': title or f'Reunião {date_str}',
                'date': date_str,
                'status': status or 'Pendente',
                'project': project or '',
                'summary': summary,
                'actions': actions,
            })

        if not data.get('has_more'):
            break
        cursor = data.get('next_cursor')

    # Ordena por data decrescente
    meetings.sort(key=lambda m: m['date'], reverse=True)
    return meetings


def meetings_to_js(meetings):
    return json.dumps(meetings, ensure_ascii=False, indent=2)


def main():
    print("Buscando reuniões do Notion...")
    meetings = fetch_meetings()
    total = len(meetings)
    print(f"Total: {total} reuniões encontradas")

    # KPIs
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

    projects = len(set(m['project'] for m in meetings if m['project']))
    done = sum(1 for m in meetings if m['status'].lower() in ['concluida', 'concluída', 'done', 'completed'])
    rate = f"{int(done / total * 100)}%" if total else "0%"
    updated = datetime.now().strftime('%d/%m/%Y %H:%M')
    meetings_js = meetings_to_js(meetings)

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Injeta dados das reuniões
    html = re.sub(r'var MEETINGS = \[[\s\S]*?\];', f'var MEETINGS = {meetings_js};', html)

    # Atualiza timestamp no rodapé/header
    html = re.sub(
        r'(GRUPO HOLSA\s*·\s*Central de Inteligência\s*·\s*)([^<\n]*)',
        rf'\1Atualizado: {updated}',
        html
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ Dashboard atualizado: {total} reuniões | {week} esta semana | taxa {rate}")


if __name__ == '__main__':
    main()
