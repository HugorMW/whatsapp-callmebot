import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json
import datetime
import time

# --- CONFIGURAÇÕES ---
URL_VAGAS = "http://solucoes.inovacapixaba.es.gov.br:8081/vagas/"
PALAVRAS_CHAVE = ["assistente", "analista"]
ARQUIVO_ESTADO = "vagas_conhecidas.json"

# --- MESMOS SECRETS DO RelatorioContasMes ---
WHATSAPP_PHONE = os.environ.get('WHATSAPP_PHONE')
CALLMEBOT_APIKEY = os.environ.get('CALLMEBOT_APIKEY')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def carregar_vagas_conhecidas():
    if os.path.exists(ARQUIVO_ESTADO):
        with open(ARQUIVO_ESTADO, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def salvar_vagas_conhecidas(vagas_ids):
    with open(ARQUIVO_ESTADO, 'w', encoding='utf-8') as f:
        json.dump(list(vagas_ids), f, ensure_ascii=False, indent=2)


def extrair_vagas_da_pagina(soup):
    vagas = []
    cards = soup.find_all('div', class_='card')
    for card in cards:
        titulo_tag = card.find('h5', class_='card-title')
        if not titulo_tag:
            continue
        titulo = titulo_tag.get_text(strip=True)
        link_tag = card.find('a', href=True)
        href = link_tag['href'] if link_tag else ""
        link = urllib.parse.urljoin(URL_VAGAS, href)
        partes = [p for p in href.split('/') if p.isdigit()]
        vaga_id = partes[0] if partes else href
        paragrafos = card.find_all('p')
        municipio = paragrafos[1].get_text(strip=True) if len(paragrafos) > 1 else ""
        salario = ""
        for p in paragrafos:
            forte = p.find('strong')
            if forte and 'Salário' in forte.get_text():
                salario = p.get_text(strip=True).replace('Salário:', '').strip()
        vagas.append({
            'id': vaga_id, 'titulo': titulo,
            'municipio': municipio, 'salario': salario, 'link': link,
        })
    return vagas


def buscar_todas_vagas():
    todas = []
    pagina = 1
    while True:
        url = f"{URL_VAGAS}?page={pagina}&cargo=&unidade=&municipio="
        print(f"Buscando página {pagina}...")
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"Erro ao acessar página {pagina}: {e}")
            break
        soup = BeautifulSoup(r.text, 'html.parser')
        vagas_pagina = extrair_vagas_da_pagina(soup)
        if not vagas_pagina:
            break
        todas.extend(vagas_pagina)
        print(f"  → {len(vagas_pagina)} vagas na página {pagina}")
        proxima = soup.find('a', class_='page-link', href=lambda h: h and f'page={pagina + 1}' in h)
        if not proxima:
            break
        pagina += 1
    return todas


def enviar_whatsapp(mensagem):
    if not WHATSAPP_PHONE or not CALLMEBOT_APIKEY:
        print("Aviso: Credenciais do WhatsApp não configuradas.")
        return
    texto_codificado = urllib.parse.quote(mensagem)
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={WHATSAPP_PHONE}&text={texto_codificado}&apikey={CALLMEBOT_APIKEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            print("  WhatsApp enviado com sucesso!")
        else:
            print(f"  Erro WhatsApp: Status {r.status_code}")
    except Exception as e:
        print(f"  Erro de conexão WhatsApp: {e}")


def enviar_resumo_semanal(todas_vagas):
    hoje = datetime.date.today()
    data_formatada = hoje.strftime("%d/%m/%Y")

    cabecalho = (
        f"📋 *Resumo Semanal de Vagas | iNOVA Capixaba*\n"
        f"*Segunda-feira, {data_formatada}*\n\n"
        f"*Total de vagas disponíveis: {len(todas_vagas)}*"
    )

    BLOCO = 5
    blocos = [todas_vagas[i:i+BLOCO] for i in range(0, len(todas_vagas), BLOCO)]
    total_blocos = len(blocos)

    mensagens = [cabecalho]
    for idx, bloco in enumerate(blocos, 1):
        inicio = (idx - 1) * BLOCO + 1
        msg = f"📋 *Vagas ({idx}/{total_blocos})*\n\n"
        for i, v in enumerate(bloco, inicio):
            msg += f"*{i}. {v['titulo']}*\n"
            linha = ""
            if v['municipio']:
                linha += f"📍 {v['municipio']}"
            if v['salario']:
                linha += f" | 💰 {v['salario']}"
            if linha:
                msg += linha + "\n"
            msg += "\n"
        mensagens.append(msg)

    mensagens.append(f"🌐 Todas as vagas:\n{URL_VAGAS}")

    print(f"Enviando resumo semanal em {len(mensagens)} mensagens...")
    for i, msg in enumerate(mensagens, 1):
        print(f"  Enviando mensagem {i}/{len(mensagens)}...")
        enviar_whatsapp(msg)
        if i < len(mensagens):
            time.sleep(3)


def enviar_alerta_novas_vagas(novas_vagas):
    msg = f"🚨 *{len(novas_vagas)} Nova(s) Vaga(s) - Assistente/Analista!*\n\n"
    for i, v in enumerate(novas_vagas, 1):
        msg += f"*{i}. {v['titulo']}*\n"
        if v['municipio']:
            msg += f"📍 {v['municipio']}\n"
        if v['salario']:
            msg += f"💰 {v['salario']}\n"
        if v['link']:
            msg += f"🔗 {v['link']}\n"
        msg += "\n"
    msg += f"🌐 {URL_VAGAS}"
    enviar_whatsapp(msg)


if __name__ == "__main__":
    print("Iniciando monitoramento de vagas - iNOVA Capixaba...")

    hoje = datetime.date.today()
    is_segunda = hoje.weekday() == 0  # 0 = segunda-feira

    vagas_conhecidas_ids = carregar_vagas_conhecidas()
    print(f"IDs já conhecidos: {len(vagas_conhecidas_ids)}")

    todas_vagas = buscar_todas_vagas()
    print(f"Total de vagas no site: {len(todas_vagas)}")

    if not todas_vagas:
        print("Nenhuma vaga encontrada ou site inacessível. Encerrando.")
        exit(0)

    # Segunda-feira: envia resumo com todas as vagas
    if is_segunda:
        print("É segunda-feira! Enviando resumo semanal...")
        enviar_resumo_semanal(todas_vagas)

    # Todo dia: verifica novas vagas de assistente/analista
    novas_vagas = [
        v for v in todas_vagas
        if any(p in v['titulo'].lower() for p in PALAVRAS_CHAVE)
        and v['id'] not in vagas_conhecidas_ids
    ]
    print(f"Novas vagas relevantes: {len(novas_vagas)}")

    if novas_vagas:
        print("Novas vagas encontradas! Enviando alerta...")
        enviar_alerta_novas_vagas(novas_vagas)
        vagas_conhecidas_ids.update(v['id'] for v in novas_vagas)
        salvar_vagas_conhecidas(vagas_conhecidas_ids)
        print("Estado atualizado.")
    else:
        print("Nenhuma vaga nova de assistente/analista.")

    print("Monitoramento concluído.")
