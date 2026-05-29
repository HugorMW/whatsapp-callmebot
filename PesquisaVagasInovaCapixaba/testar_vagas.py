import requests
from bs4 import BeautifulSoup
import urllib.parse
import datetime
import time

URL_VAGAS = "http://solucoes.inovacapixaba.es.gov.br:8081/vagas/"
PALAVRAS_CHAVE = ["assistente", "analista"]

WHATSAPP_PHONE = input("Seu número WhatsApp (com código do país, ex: 5527999999999): ").strip()
CALLMEBOT_APIKEY = input("Sua API Key do CallMeBot: ").strip()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


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
            print(f"Erro: {e}")
            break
        soup = BeautifulSoup(r.text, 'html.parser')
        vagas_pagina = extrair_vagas_da_pagina(soup)
        if not vagas_pagina:
            print(f"  → Nenhuma vaga na página {pagina}, encerrando.")
            break
        todas.extend(vagas_pagina)
        print(f"  → {len(vagas_pagina)} vagas na página {pagina}")

        # Verifica próxima página pelo número da página atual + 1
        proxima = soup.find('a', class_='page-link', href=lambda h: h and f'page={pagina + 1}' in h)
        if not proxima:
            print(f"  → Não há página {pagina + 1}, encerrando.")
            break
        pagina += 1

    return todas


def enviar_whatsapp(mensagem):
    texto_codificado = urllib.parse.quote(mensagem)
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={WHATSAPP_PHONE}&text={texto_codificado}&apikey={CALLMEBOT_APIKEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        print(f"  Status: {r.status_code}")
    except Exception as e:
        print(f"  Erro: {e}")


def montar_e_enviar_resumo_semanal(todas_vagas, apenas_preview=False):
    hoje = datetime.date.today()
    data_formatada = hoje.strftime("%d/%m/%Y")

    # Cabeçalho — enviado primeiro
    cabecalho = (
        f"📋 *Resumo Semanal de Vagas | iNOVA Capixaba*\n"
        f"*Segunda-feira, {data_formatada}*\n\n"
        f"*Total de vagas disponíveis: {len(todas_vagas)}*"
    )

    # Divide as vagas em blocos de 5 para não cortar
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

    # Rodapé — enviado por último
    mensagens.append(f"🌐 Todas as vagas:\n{URL_VAGAS}")

    # Preview no terminal
    print("\n--- PRÉVIA DAS MENSAGENS ---")
    for i, m in enumerate(mensagens, 1):
        print(f"\n[Mensagem {i}]")
        print(m)
        print(f"({len(m)} caracteres)")
    print("----------------------------\n")

    if not apenas_preview:
        print(f"Enviando {len(mensagens)} mensagens...")
        for i, m in enumerate(mensagens, 1):
            print(f"  Enviando mensagem {i}/{len(mensagens)}...")
            enviar_whatsapp(m)
            if i < len(mensagens):
                time.sleep(3)  # Pausa entre mensagens para não ser bloqueado
        print("Todas enviadas!")


# --- EXECUÇÃO ---
print("\n🔍 Buscando vagas no site...\n")
todas_vagas = buscar_todas_vagas()
print(f"\nTotal encontrado: {len(todas_vagas)} vagas")

montar_e_enviar_resumo_semanal(todas_vagas, apenas_preview=True)

enviar = input("Deseja enviar as mensagens agora? (s/n): ").strip().lower()
if enviar == 's':
    montar_e_enviar_resumo_semanal(todas_vagas, apenas_preview=False)

print("\nFim do teste.")