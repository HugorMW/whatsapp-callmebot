import os
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
from urllib.parse import urljoin
import datetime

# --- DADOS FIXOS ---
ALUGUEL = 531.00
INTERNET = 50.00
CHAT = 7.00
UC = "92147"
CPF = "24350729615"

# --- PEGA DOS SECRETS DO GITHUB ---
WHATSAPP_PHONE = os.environ.get('WHATSAPP_PHONE')
CALLMEBOT_APIKEY = os.environ.get('CALLMEBOT_APIKEY')


def obter_fatura_energia():
    session = requests.Session()
    url_login = "https://portal.elfsm.com.br/portal2/segunda_via_facil.php"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Referer': url_login
    }

    resp_get = session.get(url_login, headers=headers)
    soup_get = BeautifulSoup(resp_get.text, 'html.parser')
    form = soup_get.find('form')
    post_url = urljoin(url_login, form.get('action')) if form else url_login

    payload = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
    payload.update({btn.get('name'): btn.get('value', '') for btn in form.find_all('button') if btn.get('name')})
    payload.update({'cd_un_consumidora': UC, 'nr_cgc_cpf': CPF})

    response = session.post(post_url, data=payload, headers=headers)

    if "Não existem contas a exibir" in response.text:
        return datetime.datetime.now().strftime("%m/%Y"), "Sem vencimento", 0.0, None, None

    soup = BeautifulSoup(response.text, 'html.parser')
    tbody = soup.find('tbody')
    if not tbody:
        return datetime.datetime.now().strftime("%m/%Y"), "Erro Site", 0.0, None, None

    # Pega a PRIMEIRA linha que realmente contém dados (<td>), ignorando o cabeçalho (<th>)
    linha_dados = None
    for tr in tbody.find_all('tr'):
        if tr.find_all('td'):
            linha_dados = tr
            break

    if not linha_dados:
        return datetime.datetime.now().strftime("%m/%Y"), "Sem contas", 0.0, None, None

    colunas = linha_dados.find_all('td')
    mes_ano = re.sub(r'\s+', '', colunas[0].text)
    vencimento = colunas[2].text.strip()
    valor_energia = float(
        colunas[3].text.strip().replace('R$', '').replace('.', '').replace(',', '.').strip()
    )

    # PIX vem direto no HTML, dentro de um <input value="...">
    pix = None
    pix_input = linha_dados.find('input', {'name': re.compile(r'pix', re.I)})
    if pix_input and pix_input.get('value'):
        pix = pix_input.get('value').strip()
    else:
        # fallback: procura qualquer input cujo value comece com o padrão PIX
        for inp in linha_dados.find_all('input'):
            val = inp.get('value', '')
            if val.startswith('000201'):
                pix = val.strip()
                break

    # Link da fatura (última coluna com <a>)
    link_fatura = None
    link_tag = linha_dados.find('a', href=True)
    if link_tag:
        link_fatura = link_tag['href']

    return mes_ano, vencimento, valor_energia, pix, link_fatura


def enviar_whatsapp(mensagem):
    if not WHATSAPP_PHONE or not CALLMEBOT_APIKEY:
        print("Aviso: Credenciais do WhatsApp não configuradas.")
        return

    texto_codificado = urllib.parse.quote(mensagem)
    url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={texto_codificado}&apikey={CALLMEBOT_APIKEY}"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"Sucesso no WhatsApp: {response.text}")
        else:
            print(f"Erro no WhatsApp: Status {response.status_code}")
    except Exception as e:
        print(f"Erro de conexão WhatsApp: {e}")


def enviar_relatorio(mes_ano, vencimento, valor_energia, pix, link_fatura):
    energia_meia = valor_energia / 2
    total_estimado = ALUGUEL + INTERNET + CHAT + energia_meia
    aluguel_total = ALUGUEL * 2
    internet_total = INTERNET * 2
    total_geral = aluguel_total + internet_total + valor_energia + CHAT

    # --- MENSAGEM 1: RELATÓRIO COMPLETO ---
    corpo_completo = f"""Contas de Casas {mes_ano}:

Enviar para Rodolfo:
- Aluguel: R$ {ALUGUEL:.2f}
- Internet: R$ {INTERNET:.2f}
- Chat: R$ {CHAT:.2f}
- Energia (Venc.: {vencimento}): R$ {energia_meia:.2f}

---------------------------------
TOTAL ESTIMADO: R$ {total_estimado:.2f}
---------------------------------

Totais das Contas:
- Aluguel Total: R$ {aluguel_total:.2f}
- Internet Total: R$ {internet_total:.2f}
- Energia Total: R$ {valor_energia:.2f}
- Chat: R$ {CHAT:.2f}

TOTAL GERAL: R$ {total_geral:.2f}
---------------------------------
"""
    if link_fatura:
        corpo_completo += f"\nFatura da energia:\n{link_fatura}\n"

    # --- MENSAGEM 2: APENAS VALORES (DIRETO PARA O RODOLFO) ---
    corpo_rodolfo = f"""Aluguel: R$ {ALUGUEL:.2f}
Internet: R$ {INTERNET:.2f}
Chat: R$ {CHAT:.2f}
Energia: R$ {energia_meia:.2f}"""

    # --- MENSAGEM 3: PIX (separada para facilitar copiar e colar) ---
    # Disparos WhatsApp
    enviar_whatsapp(corpo_completo)
    enviar_whatsapp(corpo_rodolfo)

    if pix:
        enviar_whatsapp(f"PIX COPIA E COLA ENERGIA:\n{pix}")


if __name__ == "__main__":
    mes_ano, vencimento, valor_energia, pix, link_fatura = obter_fatura_energia()
    print(f"Mês/Ano: {mes_ano} | Vencimento: {vencimento} | Valor: {valor_energia}")
    print(f"PIX encontrado: {'Sim' if pix else 'Não'}")
    print(f"Link fatura: {link_fatura}")

    if valor_energia > 0:
        enviar_relatorio(mes_ano, vencimento, valor_energia, pix, link_fatura)
    else:
        print("Sem conta pendente. Nada a enviar.")
        # Se quiser ser avisado mesmo quando não há conta, descomente:
        # enviar_whatsapp(f"Sem conta de energia pendente em {mes_ano}.")
