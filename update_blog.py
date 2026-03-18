#!/usr/bin/env python3
"""
Atualiza os cards do blog Estratégia MED no index.html.
Rodado diariamente pelo GitHub Actions.
"""

import os
import re
import json
import urllib.request
import urllib.error
from datetime import datetime

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SYSTEM_PROMPT = """Você é um assistente especializado em residência médica no Brasil.
Use web_search para buscar artigos REAIS e RECENTES do blog do Estratégia MED (med.estrategia.com/portal).
Retorne APENAS um array JSON válido, sem texto antes ou depois, sem blocos markdown.

Formato exato:
[
  {
    "title": "Título real do artigo",
    "summary": "Resumo em 2 frases diretas e informativas.",
    "category": "residencia",
    "url": "https://med.estrategia.com/portal/..."
  }
]

Regras:
- category deve ser exatamente: residencia | revalida | carreira
- Retorne entre 4 e 6 artigos
- Use apenas artigos que realmente existam no portal
- url deve ser a URL completa e real do artigo
"""

def call_api(messages, tools=None):
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "web-search-2025-03-05",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_articles():
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    user_msg = "Busque os artigos mais recentes do blog Estratégia MED em med.estrategia.com/portal sobre residência médica, revalida e carreira médica."

    messages = [{"role": "user", "content": user_msg}]

    # Turno 1
    data = call_api(messages, tools)

    # Turno 2 se necessário (tool_use)
    if data.get("stop_reason") == "tool_use":
        messages.append({"role": "assistant", "content": data["content"]})
        tool_block = next((b for b in data["content"] if b["type"] == "tool_use"), None)
        tool_results = [b for b in data["content"] if b.get("type") == "web_search_tool_result"]
        result_text = json.dumps(tool_results) if tool_results else "Busca realizada."
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_block["id"],
                "content": result_text if isinstance(result_text, str) else json.dumps(result_text),
            }]
        })
        data = call_api(messages, tools)

    # Extrai texto
    raw = "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")
    return parse_articles(raw)


def parse_articles(raw):
    s = re.sub(r"```[\w]*\n?", "", raw).strip()

    # Tenta parse direto
    for attempt in [s, s[s.find("["):s.rfind("]")+1] if "[" in s else ""]:
        if not attempt:
            continue
        try:
            result = json.loads(attempt)
            if isinstance(result, list) and result:
                return result
        except json.JSONDecodeError:
            pass

    # Fallback regex campo a campo
    titles    = re.findall(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    summaries = re.findall(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    cats      = re.findall(r'"category"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    urls      = re.findall(r'"url"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)

    if not titles:
        raise ValueError(f"Nenhum artigo encontrado. Resposta bruta:\n{raw[:500]}")

    return [
        {
            "title":    titles[i],
            "summary":  summaries[i] if i < len(summaries) else "",
            "category": cats[i] if i < len(cats) else "residencia",
            "url":      urls[i] if i < len(urls) else None,
        }
        for i in range(len(titles))
    ]


CATEGORY_LABEL = {
    "residencia": "Residência Médica",
    "revalida":   "Revalida",
    "carreira":   "Carreira",
}

def esc(s):
    if not s:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def build_cards(articles):
    updated_at = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    lines = [f'    <div class="blog-grid" id="blog-output">']
    for a in articles:
        cat   = a.get("category", "residencia")
        label = CATEGORY_LABEL.get(cat, "Notícia")
        url   = a.get("url") or ""
        link  = (f'        <a class="blog-card-link" href="{esc(url)}" '
                 f'target="_blank" rel="noopener">Ler artigo →</a>')
        lines.append(f"""      <div class="blog-card">
        <span class="blog-card-tag" data-cat="{esc(cat)}">{esc(label)}</span>
        <h4>{esc(a.get("title",""))}</h4>
        <p>{esc(a.get("summary",""))}</p>
        {link if url else ""}
      </div>""")
    lines.append(f'      <p style="grid-column:1/-1;font-size:11px;color:var(--muted);text-align:right;margin-top:8px">Atualizado em {updated_at}</p>')
    lines.append("    </div>")
    return "\n".join(lines)


def inject_cards(html, cards_html):
    pattern = r"<!-- BLOG_START -->.*?<!-- BLOG_END -->"
    replacement = f"<!-- BLOG_START -->\n{cards_html}\n    <!-- BLOG_END -->"
    new_html, count = re.subn(pattern, replacement, html, flags=re.DOTALL)
    if count == 0:
        raise ValueError("Marcadores BLOG_START/BLOG_END não encontrados no HTML.")
    return new_html


def main():
    print("Buscando artigos...")
    articles = get_articles()
    print(f"  {len(articles)} artigos encontrados.")

    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    cards_html = build_cards(articles)
    new_html   = inject_cards(html, cards_html)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print("index.html atualizado com sucesso.")
    for a in articles:
        print(f"  [{a.get('category')}] {a.get('title','')[:60]}")


if __name__ == "__main__":
    main()
