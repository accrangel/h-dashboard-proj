
Claude terminou a resposta
1783180456347_image.png
✅ Worker deployado com sucesso em https://holsa-notion-proxy.holsa.workers.dev.

Agora suba o index.html no GitHub substituindo o atual. Depois acesse o dashboard, clique em Sincronizar e me avisa o resultado.

1783180521380_image.png
🎉 Funcionou! "Sincronização iniciada — aguarde ~30s"

O botão Sincronizar agora funciona sem token exposto. Aguarde os 30s e me manda como ficou o dashboard depois — especialmente se o resumo das reuniões curtas aparece como "⏱ Gravação muito curta para gerar resumo."

1783180570283_image.png
O Sincronizar está funcionando perfeitamente — "Notion sincronizado" verde ✅

O resumo ainda mostra Speaker 1 00:00:01... porque o update_dashboard.py com a correção do clean_summary ainda não foi aplicado nessa sincronização — o Actions está rodando com a versão antiga do script.

Você subiu o update_dashboard.py novo na raiz do repositório? Se sim, pode ter sido sobrescrito. Vá no GitHub, clique no update_dashboard.py e confirma se tem a função clean_summary no início do arquivo.

1783180665763_image.png
O script está correto no GitHub. O problema é que o texto "Speaker 1 00:00:01..." não está no campo Resumo do Notion — está no campo Transcrição, que o script também lê como fallback quando o Resumo está vazio.

Veja: "Speaker 1 00:00:08 Teste de áudio, 1, 2, 3, 4" — isso é transcrição bruta, não resumo.

Preciso ajustar o script para não usar o campo Transcrição como fallback para o resumo. Deixa eu corrigir:


Remover Transcrição do fallback do resumo
Remover Transcrição do fallback do resumo
Mas antes de gerar, preciso saber exatamente quais campos existem no Notion. Deixa eu verificar:


Usou a integração Notion, ferramentas carregadas
Usou a integração Notion, ferramentas carregadas
Agora entendi tudo. Os campos no Notion são Resumo IA e Action Items — não Resumo e Summary. O script está procurando pelo nome errado e caindo no fallback da Transcrição. Vou corrigir:


Editou um arquivo, leu um arquivo
Editou um arquivo, leu um arquivo
Suba esse update_dashboard.py no GitHub substituindo o atual, depois clique em Sincronizar no dashboard. Dessa vez vai funcionar — o script agora busca o campo Resumo IA que é o nome real no Notion.


Update dashboard
PY 





Claude é uma IA e pode cometer erros. Por favor, verifique as respostas.
Update dashboard · PY
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
 
 
SHORT_RECORDING_PATTERNS = [
    'a transcrição é breve',
    'não é necessário resumo',
    'transcrição original do áudio',
    'speaker 1',
    'speaker 2',
    'gravação muito curta',
]
 
def clean_summary(text):
    """Detecta textos gerados para gravações curtas e substitui por mensagem amigável."""
    if not text:
        return ''
    lower = text.lower()
    matches = sum(1 for p in SHORT_RECORDING_PATTERNS if p in lower)
    if matches >= 2:
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
 
