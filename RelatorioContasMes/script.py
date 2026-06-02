import os
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
from urllib.parse import urljoin
import datetime
from datetime import date
import imaplib
import email
from email.header import decode_header
import io
try:
    import fitz  # PyMuPDF (versões mais antigas)
except ImportError:
    import pymupdf as fitz  # PyMuPDF (versões novas usam 'pymupdf')
import cv2   # OpenCV - decodifica QR Code (sem dependência de sistema)
import numpy as np

# ============================================================
#  DADOS FIXOS
# ============================================================
ALUGUEL = 531.00
INTERNET = 50.00
CHAT = 7.00
UC = "92147"
CPF_ENERGIA = "24350729615"     # CPF do titular da conta de energia
SENHA_PDF_INTER = "181998"      # 6 primeiros dígitos do CPF do cartão Inter
PIX_NUBANK = "vendinha13@gmail.com"   # chave PIX fixa do Nubank (fatura não traz QR Code)
# Compras de terceiros na fatura do Inter: nome da pessoa -> palavras que identificam as compras dela.
# O que não bater com ninguém entra na "minha parte". Adicione/edite à vontade.
GASTOS_PESSOAS = {
    "Avó": ["RDSAUDE", "RAIA DROGASIL", "DROGASIL", "DROGA RAIA"],
    "Arthur": ["LATAM", "LATAM AIR"],
    "Kamily": ["DLOCAL"],
}
# Assinaturas compartilhadas (aparecem no PDF detalhado do Nubank)
# ChatGPT: você paga uma parte fixa; o resto é pra dividir.
CHATGPT_COMPARTILHADO = True      # False = ChatGPT é só seu (não separa, fica no total)
CHATGPT_MINHA_PARTE = 10.00       # sua parte fixa do ChatGPT (em reais)
# Claude.Ai: dividido igualmente entre N pessoas.
CLAUDE_COMPARTILHADO = True       # False = Claude é só seu (não separa, fica no total da fatura)
CLAUDE_NUM_PESSOAS = 2            # entre quantas pessoas dividir igualmente

# ============================================================
#  SECRETS DO GITHUB
# ============================================================
WHATSAPP_PHONE = os.environ.get('WHATSAPP_PHONE')
CALLMEBOT_APIKEY = os.environ.get('CALLMEBOT_APIKEY')
EMAIL_CONTAS = os.environ.get('EMAIL_CONTAS')              # hugormwcontas@gmail.com
EMAIL_CONTAS_SENHA = os.environ.get('EMAIL_CONTAS_SENHA')  # senha de app

MESES = {'jan':'01','fev':'02','mar':'03','abr':'04','mai':'05','jun':'06',
         'jul':'07','ago':'08','set':'09','out':'10','nov':'11','dez':'12'}


# ============================================================
#  ENERGIA - PORTAL ELFSM
# ============================================================
def obter_fatura_energia():
    session = requests.Session()
    url_login = "https://portal.elfsm.com.br/portal2/segunda_via_facil.php"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Referer': url_login
    }
    try:
        resp_get = session.get(url_login, headers=headers, timeout=30)
        soup_get = BeautifulSoup(resp_get.text, 'html.parser')
        form = soup_get.find('form')
        post_url = urljoin(url_login, form.get('action')) if form else url_login

        payload = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
        payload.update({btn.get('name'): btn.get('value', '') for btn in form.find_all('button') if btn.get('name')})
        payload.update({'cd_un_consumidora': UC, 'nr_cgc_cpf': CPF_ENERGIA})

        response = session.post(post_url, data=payload, headers=headers, timeout=30)

        if "Não existem contas a exibir" in response.text:
            return "Sem vencimento", 0.0, None

        soup = BeautifulSoup(response.text, 'html.parser')
        tbody = soup.find('tbody')
        if not tbody:
            return "Erro Site", 0.0, None

        linha = None
        for tr in tbody.find_all('tr'):
            if tr.find_all('td'):
                linha = tr; break
        if not linha:
            return "Sem contas", 0.0, None

        colunas = linha.find_all('td')
        vencimento = colunas[2].text.strip()
        valor = float(colunas[3].text.strip().replace('R$', '').replace('.', '').replace(',', '.').strip())

        pix = None
        for inp in linha.find_all('input'):
            if inp.get('value', '').startswith('000201'):
                pix = inp.get('value').strip(); break

        link = None
        a = linha.find('a', href=True)
        if a:
            link = a['href']

        return vencimento, valor, {'pix': pix, 'link': link}
    except Exception as e:
        print(f"Erro ao obter energia: {e}")
        return "Erro", 0.0, None


# ============================================================
#  CARTÕES - LEITURA VIA IMAP (GMAIL)
# ============================================================
def conectar_gmail():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_CONTAS, EMAIL_CONTAS_SENHA)
    mail.select("inbox")
    return mail


def decodificar_assunto(msg):
    s = ""
    for t, enc in decode_header(msg.get("Subject", "")):
        s += t.decode(enc or 'utf-8', errors='ignore') if isinstance(t, bytes) else t
    return s


def buscar_por_assunto(mail, palavra_chave):
    status, dados = mail.search(None, "ALL")
    if status != "OK" or not dados[0]:
        return None
    for msg_id in reversed(dados[0].split()):
        status, msg_data = mail.fetch(msg_id, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        if palavra_chave.lower() in decodificar_assunto(msg).lower():
            return msg
    return None


def extrair_texto_corpo(msg):
    corpo = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in disp:
                try: corpo += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except: pass
            elif ctype == "text/html" and "attachment" not in disp:
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    corpo += "\n" + BeautifulSoup(html, 'html.parser').get_text(separator=' ')
                except: pass
    else:
        try: corpo = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except: pass
    return re.sub(r'\s+', ' ', corpo).strip()


def extrair_texto_pdf(msg, senha=None):
    """Retorna (texto, pdf_bytes_originais)."""
    from pypdf import PdfReader
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        nome = part.get_filename()
        if nome and nome.lower().endswith('.pdf'):
            pdf_bytes = part.get_payload(decode=True)
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                if reader.is_encrypted:
                    if reader.decrypt(senha or "") == 0:
                        print(f"    Senha do PDF incorreta.")
                        return None, pdf_bytes
                texto = ""
                for p in reader.pages:
                    texto += (p.extract_text() or "") + " "
                return re.sub(r'\s+', ' ', texto).strip(), pdf_bytes
            except Exception as e:
                print(f"    Erro ao ler PDF: {e}")
                return None, pdf_bytes
    return None, None


def extrair_pix_do_qr(pdf_bytes, senha=None):
    """Renderiza o PDF (PyMuPDF) e procura um PIX (000201...) nos QR Codes (OpenCV)."""
    if not pdf_bytes:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.needs_pass and senha:
            doc.authenticate(senha)
        detector = cv2.QRCodeDetector()
        for dpi in (300, 400):
            for page in doc:
                pm = page.get_pixmap(dpi=dpi)
                img = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pm.n == 4 else cv2.COLOR_RGB2BGR)
                ok, decs, _, _ = detector.detectAndDecodeMulti(img)
                if ok:
                    for s in decs:
                        if s.startswith("000201"):
                            doc.close(); return s
                s, _, _ = detector.detectAndDecode(img)
                if s and s.startswith("000201"):
                    doc.close(); return s
        doc.close()
    except Exception as e:
        print(f"    Erro ao ler QR Code: {e}")
    return None


def extrair_linha_digitavel(texto):
    """Procura a linha digitável do boleto no texto."""
    if not texto:
        return None
    m = re.search(r'\d{5}\.\d{5}\s*\d{5}\.\d{6}\s*\d{5}\.\d{6}\s*\d\s*\d{14}', texto)
    if m:
        return re.sub(r'\s+', ' ', m.group(0)).strip()
    return None


def parse_valor(texto, ancoras=None):
    if not texto:
        return None
    pad = r'(\d{1,3}(?:\.\d{3})*,\d{2})'
    if ancoras:
        for ancora in ancoras:
            m = re.search(ancora + r'\s*R?\$?\s*' + pad, texto, re.IGNORECASE)
            if m:
                return float(m.group(1).replace('.', '').replace(',', '.'))
    matches = re.findall(r'R?\$?\s*' + pad, texto)
    if matches:
        return max(float(m.replace('.', '').replace(',', '.')) for m in matches)
    return None


def _ano_inferido(dia, mes):
    hoje = date.today()
    try:
        cand = date(hoje.year, mes, dia)
    except ValueError:
        return hoje.year
    return hoje.year + 1 if (hoje - cand).days > 60 else hoje.year


def parse_vencimento(texto):
    if not texto:
        return None
    m = re.search(r'[Vv]enc\w*[:\s]+(\d{2}/\d{2}(?:/\d{4})?)', texto)
    if m: return m.group(1)
    m = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})', texto, re.IGNORECASE)
    if m and m.group(2).lower()[:3] in MESES:
        return f"{int(m.group(1)):02d}/{MESES[m.group(2).lower()[:3]]}/{m.group(3)}"
    m = re.search(r'dia\s+(\d{1,2})\s+de\s+([a-zç]+)', texto, re.IGNORECASE)
    if m and m.group(2).lower()[:3] in MESES:
        d = int(m.group(1)); mes = int(MESES[m.group(2).lower()[:3]])
        return f"{d:02d}/{mes:02d}/{_ano_inferido(d, mes)}"
    m = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)', texto, re.IGNORECASE)
    if m and m.group(2).lower()[:3] in MESES:
        d = int(m.group(1)); mes = int(MESES[m.group(2).lower()[:3]])
        return f"{d:02d}/{mes:02d}/{_ano_inferido(d, mes)}"
    m = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
    if m: return m.group(1)
    return None


def extrair_assinatura_nubank(texto, nome_merchant):
    """Extrai assinatura + IOF de uma assinatura internacional no PDF do Nubank (ChatGPT, Claude, etc)."""
    if not texto:
        return None
    m_esc = re.escape(nome_merchant)
    val = r'(\d{1,3}(?:\.\d{3})*,\d{2})'
    iof = 0.0
    m = re.search(r'IOF de\s*"?' + m_esc + r'"?\s*R\$\s*' + val, texto, re.IGNORECASE)
    if m:
        iof = float(m.group(1).replace('.', '').replace(',', '.'))
    # linha da compra: pega o ÚLTIMO valor antes da próxima data (ignora a cotação do dólar)
    m = re.search(m_esc + r'\s+(?:USD|BRL).*?(?=\d{1,2}\s+[A-Z]{3}\b)', texto, re.IGNORECASE | re.DOTALL)
    assinatura = None
    if m:
        valores = re.findall(val, m.group(0))
        if valores:
            assinatura = float(valores[-1].replace('.', '').replace(',', '.'))
    if assinatura is None:
        return None
    return {'assinatura': assinatura, 'iof': iof, 'total': assinatura + iof}


def analisar_compras_inter(texto, gastos_pessoas):
    """Separa compras por pessoa. O que não bater com ninguém é 'minha parte'. Ignora pagamentos/estornos."""
    if not texto:
        return {}, 0.0, []
    padrao = r'(\d{1,2}\s+de\s+[a-z]{3}\.?\s+\d{4})\s+(.+?)\s*-\s*(\+\s*)?R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})'
    por_pessoa = {nome: {'total': 0.0, 'itens': []} for nome in gastos_pessoas}
    total_meu = 0.0
    itens_meus = []
    for m in re.finditer(padrao, texto, re.IGNORECASE):
        loja = m.group(2).strip()
        if bool(m.group(3)) or 'PAGAMENTO' in loja.upper():
            continue  # estorno/pagamento não é compra
        valor = float(m.group(4).replace('.', '').replace(',', '.'))
        loja_limpa = re.sub(r'\s*\(Parcela.*?\)', '', loja, flags=re.IGNORECASE).strip()
        dono = None
        for nome, palavras in gastos_pessoas.items():
            if any(p.upper() in loja.upper() for p in palavras):
                dono = nome
                break
        if dono:
            por_pessoa[dono]['total'] += valor
            por_pessoa[dono]['itens'].append((loja_limpa, valor))
        else:
            total_meu += valor
            itens_meus.append((loja_limpa, valor))
    return por_pessoa, total_meu, itens_meus


def obter_fatura_cartao(mail, nome, palavra_chave, fonte, ancoras, senha_pdf=None):
    print(f"Buscando fatura {nome}...")
    msg = buscar_por_assunto(mail, palavra_chave)
    if not msg:
        print(f"  Nenhuma fatura {nome} encontrada.")
        return {'nome': nome, 'valor': None, 'vencimento': None,
                'pix': None, 'boleto': None, 'analise': None, 'chatgpt': None, 'claude': None}

    pix = boleto = analise = chatgpt = claude = None
    texto_corpo = extrair_texto_corpo(msg)
    texto_pdf, pdf_bytes = extrair_texto_pdf(msg, senha=senha_pdf)

    # valor/vencimento: Nubank vem do corpo do e-mail; Inter/Viaon vêm do PDF
    texto_valor = texto_corpo if fonte == 'corpo' else (texto_pdf or texto_corpo)
    valor = parse_valor(texto_valor, ancoras)
    vencimento = parse_vencimento(texto_valor)

    if nome == "Nubank":
        # Assinaturas compartilhadas no PDF detalhado anexo
        chatgpt = extrair_assinatura_nubank(texto_pdf, "Openai *Chatgpt Subscr")
        claude = extrair_assinatura_nubank(texto_pdf, "Claude.Ai Subscription")
    elif nome == "Inter":
        boleto = extrair_linha_digitavel(texto_pdf)
        pix = extrair_pix_do_qr(pdf_bytes, senha=senha_pdf)
        if texto_pdf:
            por_pessoa, total_meu, itens_meus = analisar_compras_inter(texto_pdf, GASTOS_PESSOAS)
            analise = {'por_pessoa': por_pessoa, 'total_meu': total_meu, 'itens_meus': itens_meus}
    elif nome == "Viaon":
        pix = extrair_pix_do_qr(pdf_bytes, senha=senha_pdf)

    print(f"  {nome}: valor={valor} venc={vencimento} pix={'sim' if pix else 'não'} "
          f"boleto={'sim' if boleto else 'não'} chatgpt={'sim' if chatgpt else 'não'} claude={'sim' if claude else 'não'}")
    return {'nome': nome, 'valor': valor, 'vencimento': vencimento,
            'pix': pix, 'boleto': boleto, 'analise': analise, 'chatgpt': chatgpt, 'claude': claude}


def obter_todas_faturas_cartao():
    if not EMAIL_CONTAS or not EMAIL_CONTAS_SENHA:
        print("Aviso: Credenciais de e-mail das contas não configuradas.")
        return []
    try:
        mail = conectar_gmail()
    except Exception as e:
        print(f"Erro ao conectar no Gmail: {e}")
        return []

    cartoes = [
        obter_fatura_cartao(mail, "Nubank", "fatura fechou", "corpo",
                            ancoras=[r'fechou no valor de', r'valor da fatura', r'Total da sua fatura']),
        obter_fatura_cartao(mail, "Inter", "fatura cart", "pdf",
                            ancoras=[r'Total da sua fatura', r'VALOR DO DOCUMENTO', r'VALOR COBRADO', r'FATURA ATUAL'],
                            senha_pdf=SENHA_PDF_INTER),
        obter_fatura_cartao(mail, "Viaon", "fatura viaon", "pdf",
                            ancoras=[r'Valor do Documento', r'Valor Cobrado']),
    ]
    try: mail.logout()
    except: pass
    return cartoes


# ============================================================
#  WHATSAPP
# ============================================================
def enviar_whatsapp(mensagem):
    if not WHATSAPP_PHONE or not CALLMEBOT_APIKEY:
        print("Aviso: Credenciais do WhatsApp não configuradas.")
        return
    url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={urllib.parse.quote(mensagem)}&apikey={CALLMEBOT_APIKEY}"
    try:
        r = requests.get(url, timeout=15)
        print("WhatsApp enviado!" if r.status_code == 200 else f"Erro WhatsApp: {r.status_code}")
    except Exception as e:
        print(f"Erro de conexão WhatsApp: {e}")


# ============================================================
#  RELATÓRIO
# ============================================================
def brl(v):
    """Formata valor no padrão brasileiro: 1458.43 -> R$ 1.458,43"""
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def enviar_relatorio(venc_energia, valor_energia, energia_extra, cartoes):
    mes_ano = datetime.date.today().strftime("%m/%Y")
    energia_meia = valor_energia / 2
    total_estimado = ALUGUEL + INTERNET + CHAT + energia_meia

    # ===== BLOCO 1: CASA (pro Rodolfo) =====
    msg_casa = (
        f"\U0001F3E0 Contas da Casa \u2014 {mes_ano}\n\n"
        f"Enviar pro Rodolfo:\n"
        f"- Aluguel: {brl(ALUGUEL)}\n"
        f"- Internet: {brl(INTERNET)}\n"
        f"- Chat: {brl(CHAT)}\n"
        f"- Energia: {brl(energia_meia)} (vence {venc_energia})\n"
        f"\u27A1\uFE0F TOTAL: {brl(total_estimado)}\n\n"
        f"(Energia cheia: {brl(valor_energia)})"
    )
    if energia_extra and energia_extra.get('link'):
        msg_casa += f"\n\nFatura energia:\n{energia_extra['link']}"
    enviar_whatsapp(msg_casa)

    # ===== BLOCO 2: CARTOES (totais + quem te deve) =====
    L = [f"\U0001F4B3 Cart\u00f5es \u2014 {mes_ano}\n", "Voc\u00ea paga:"]
    for c in cartoes:
        if c['valor'] is not None:
            v = c['vencimento']
            L.append(f"- {c['nome']}: {brl(c['valor'])}" + (f" (vence {v})" if v else ""))
        else:
            L.append(f"- {c['nome']}: nao encontrada")

    # A cobrar - Inter por pessoa
    for c in cartoes:
        if c['nome'] == "Inter" and c.get('analise'):
            a = c['analise']
            pcv = [(n, d) for n, d in a['por_pessoa'].items() if d['total'] > 0]
            if pcv:
                L.append("\nA cobrar (Inter):")
                for n, d in pcv:
                    L.append(f"- {n}: {brl(d['total'])}")
            if a['total_meu'] > 0:
                L.append(f"- Minha parte: {brl(a['total_meu'])}")
                for loja, val in a['itens_meus']:
                    L.append(f"   \u00b7 {loja}: {brl(val)}")

    # Assinaturas - Nubank (ChatGPT e Claude)
    ass = []
    for c in cartoes:
        if c['nome'] != "Nubank":
            continue
        if CHATGPT_COMPARTILHADO and c.get('chatgpt'):
            cg = c['chatgpt']
            resto = cg['total'] - CHATGPT_MINHA_PARTE
            ass.append(f"- ChatGPT: total {brl(cg['total'])} \u2192 cobrar {brl(resto)} (sua parte {brl(CHATGPT_MINHA_PARTE)})")
        if CLAUDE_COMPARTILHADO and c.get('claude'):
            cl = c['claude']
            minha = cl['total'] / CLAUDE_NUM_PESSOAS if CLAUDE_NUM_PESSOAS else cl['total']
            ass.append(f"- Claude: total {brl(cl['total'])} \u2192 voc\u00ea {brl(minha)}, cobrar {brl(cl['total']-minha)}")
    if ass:
        L.append("\nAssinaturas (Nubank):")
        L.extend(ass)
    enviar_whatsapp("\n".join(L))

    # ===== BLOCO 3+: PIX / pagamentos (cada um separado pra copiar facil) =====
    if energia_extra and energia_extra.get('pix'):
        enviar_whatsapp(f"\U0001F511 PIX Energia:\n{energia_extra['pix']}")
    for c in cartoes:
        if c.get('pix'):
            enviar_whatsapp(f"\U0001F511 PIX {c['nome']}:\n{c['pix']}")
        elif c.get('boleto'):
            enviar_whatsapp(f"\U0001F511 Boleto {c['nome']}:\n{c['boleto']}")
        elif c['nome'] == "Nubank" and c['valor'] is not None and PIX_NUBANK:
            enviar_whatsapp(f"\U0001F511 PIX Nubank (chave): {PIX_NUBANK} \u2014 {brl(c['valor'])}")


# ============================================================
#  EXECUÇÃO
# ============================================================
if __name__ == "__main__":
    print("=== Relatório de Contas + Faturas ===")
    venc_energia, valor_energia, energia_extra = obter_fatura_energia()
    print(f"Energia: venc={venc_energia} valor={valor_energia}")
    cartoes = obter_todas_faturas_cartao()
    enviar_relatorio(venc_energia, valor_energia, energia_extra, cartoes)
    print("Concluído.")
