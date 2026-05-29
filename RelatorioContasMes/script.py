import os
import requests
from bs4 import BeautifulSoup
import smtplib
from email.message import EmailMessage
import re
import urllib.parse
from urllib.parse import urljoin
import datetime
from pdf2image import convert_from_bytes
from pyzbar.pyzbar import decode

# --- DADOS FIXOS ---
ALUGUEL = 531.00
INTERNET = 50.00
CHAT = 7.00
UC = "92147"
CPF = "24350729615"
EMAIL_DESTINO = "hugormilkewagemacher@gmail.com"

# --- PEGA DOS SECRETS DO GITHUB ---
EMAIL_REMETENTE = os.environ.get('EMAIL_REMETENTE')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
WHATSAPP_PHONE = os.environ.get('WHATSAPP_PHONE')
CALLMEBOT_APIKEY = os.environ.get('CALLMEBOT_APIKEY')

def extrair_pix_do_pdf(pdf_content):
    try:
        if not pdf_content: return None
        images = convert_from_bytes(pdf_content, dpi=300)
        for img in images:
            decoded_objects = decode(img)
            for obj in decoded_objects:
                dados = obj.data.decode('utf-8')
                if "000201" in dados: return dados
        return "PIX não encontrado no QR Code."
    except: return "Erro ao processar PIX."

def obter_fatura_energia():
    session = requests.Session()
    url_login = "https://portal.elfsm.com.br/portal2/segunda_via_facil.php"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': url_login}
    
    resp_get = session.get(url_login, headers=headers)
    soup_get = BeautifulSoup(resp_get.text, 'html.parser')
    form = soup_get.find('form')
    post_url = urljoin(url_login, form.get('action')) if form else url_login
    
    payload = {input.get('name'): input.get('value', '') for input in form.find_all('input') if input.get('name')}
    payload.update({btn.get('name'): btn.get('value', '') for btn in form.find_all('button') if btn.get('name')})
    payload.update({'cd_un_consumidora': UC, 'nr_cgc_cpf': CPF})
    
    response = session.post(post_url, data=payload, headers=headers)
    
    if "Não existem contas a exibir" in response.text:
        return datetime.datetime.now().strftime("%m/%Y"), "Sem vencimento", 0.0, None

    soup = BeautifulSoup(response.text, 'html.parser')
    tbody = soup.find('tbody')
    if not tbody: return datetime.datetime.now().strftime("%m/%Y"), "Erro Site", 0.0, None
        
    colunas = tbody.find_all('tr')[1].find_all('td')
    mes_ano = re.sub(r'\s+', '', colunas[0].text)
    vencimento = colunas[2].text.strip()
    valor_energia = float(colunas[3].text.strip().replace('R$', '').replace('.', '').replace(',', '.').strip())
    
    pdf_content = None
    link_tag = colunas[4].find('a')
    if link_tag:
        res_pdf = session.get(urljoin(url_login, link_tag['href']), headers=headers)
        if res_pdf.status_code == 200: pdf_content = res_pdf.content
        
    return mes_ano, vencimento, valor_energia, pdf_content

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

def enviar_relatorio(mes_ano, vencimento, valor_energia, pdf_content):
    pix = extrair_pix_do_pdf(pdf_content)
    
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
    if pix: corpo_completo += f"\nPIX COPIA E COLA ENERGIA:\n{pix}\n"
    corpo_completo += "\nBoleto em anexo no e-mail." if pdf_content else "\nSem boleto pendente."

    # --- MENSAGEM 2: APENAS VALORES (DIRETO PARA O RODOLFO) ---
    corpo_rodolfo = f"""Aluguel: R$ {ALUGUEL:.2f}
Internet: R$ {INTERNET:.2f}
Chat: R$ {CHAT:.2f}
Energia: R$ {energia_meia:.2f}"""

    # Disparos WhatsApp
    enviar_whatsapp(corpo_completo)
    enviar_whatsapp(corpo_rodolfo)

    # Disparo E-mail
    msg = EmailMessage()
    msg['Subject'] = f"Relatório Mensal de Contas - {mes_ano}"
    msg['From'] = EMAIL_REMETENTE
    msg['To'] = EMAIL_DESTINO
    msg.set_content(corpo_completo)
    
    if pdf_content:
        nome_arquivo = f"fatura_energia_{mes_ano.replace('/','_')}.pdf"
        msg.add_attachment(pdf_content, maintype='application', subtype='pdf', filename=nome_arquivo)
        
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_REMETENTE, EMAIL_PASSWORD)
        smtp.send_message(msg)
        print("E-mail enviado com sucesso!")

if __name__ == "__main__":
    m, v, val, p = obter_fatura_energia()
    enviar_relatorio(m, v, val, p)
