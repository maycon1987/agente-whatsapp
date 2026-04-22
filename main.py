from fastapi import FastAPI, Request
from fastapi.responses import Response
import os
import csv
import re
import unicodedata
from twilio.twiml.messaging_response import MessagingResponse
from anthropic import Anthropic

app = FastAPI()

# ================================
# CONFIG
# ================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ================================
# DEBUG
# ================================
print("========== DEBUG ==========")
print("ARQUIVOS:", os.listdir())
print("===========================")

# ================================
# FUNÇÕES AUXILIARES
# ================================
def normalizar_texto(texto):
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto

def para_float(valor):
    if valor is None:
        return None

    valor = str(valor).strip()
    if not valor:
        return None

    try:
        return float(valor.replace(".", "").replace(",", "."))
    except:
        try:
            return float(valor.replace(",", "."))
        except:
            return None

def formatar_reais(valor):
    try:
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(valor)

def extrair_medidas(texto):
    texto = normalizar_texto(texto)

    # 18x14,5x8,5
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)", texto)
    if match:
        return (
            float(match.group(1).replace(",", ".")),
            float(match.group(2).replace(",", ".")),
            float(match.group(3).replace(",", "."))
        )

    return None

def extrair_quantidade_do_nome(nome_produto):
    """
    Exemplos:
    'Caixa ... - 25unds' -> 25
    'Caixa ... - 1un' -> 1
    """
    nome = normalizar_texto(nome_produto)
    match = re.search(r"-\s*(\d+)\s*(un|unds|unidade|unidades)", nome)
    if match:
        return int(match.group(1))
    return None

def limpar_nome_base(nome_produto):
    nome = str(nome_produto).strip()
    nome = re.sub(r"\s*-\s*\d+\s*(un|unds|unidade|unidades)\s*$", "", nome, flags=re.IGNORECASE)
    return nome.strip()

# ================================
# LEITURA CSV
# ================================
def carregar_produtos():
    produtos = []

    try:
        with open("produtos.csv", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                produtos.append(row)
    except Exception as e:
        print("ERRO AO LER CSV:", e)

    return produtos

# ================================
# CAMPOS DA PLANILHA
# ================================
def descricao_produto(p):
    return p.get("Descrição", "") or ""

def preco_produto(p):
    return para_float(p.get("Preço"))

def imagem_produto(p):
    return (p.get("URL imagem 1", "") or "").strip()

# ================================
# BUSCA DO PRODUTO BASE
# ================================
def pontuar_produto(texto_usuario, nome_base):
    texto = normalizar_texto(texto_usuario)
    descricao = normalizar_texto(nome_base)

    pontuacao = 0

    # frase inteira
    if texto and texto in descricao:
        pontuacao += 50

    # palavras
    palavras = [p for p in texto.split() if len(p) >= 2]
    for palavra in palavras:
        if palavra in descricao:
            pontuacao += 10

    # medidas
    medidas = extrair_medidas(texto)
    if medidas:
        c, l, a = medidas

        medidas_textos = [
            f"{str(c).replace('.0','')}x{str(l).replace('.0','')}x{str(a).replace('.0','')}",
            f"{str(c).replace('.', ',').replace(',0','')}x{str(l).replace('.', ',').replace(',0','')}x{str(a).replace('.', ',').replace(',0','')}"
        ]

        for mt in medidas_textos:
            if mt in descricao:
                pontuacao += 40
                break

    return pontuacao

def encontrar_melhor_nome_base(mensagem, produtos):
    melhor_base = None
    melhor_pontuacao = 0

    bases_vistas = set()

    for p in produtos:
        nome = descricao_produto(p)
        base = limpar_nome_base(nome)
        base_norm = normalizar_texto(base)

        if base_norm in bases_vistas:
            continue
        bases_vistas.add(base_norm)

        score = pontuar_produto(mensagem, base)

        if score > melhor_pontuacao:
            melhor_pontuacao = score
            melhor_base = base

    if melhor_pontuacao <= 0:
        return None

    print("MELHOR BASE:", melhor_base, "| SCORE:", melhor_pontuacao)
    return melhor_base

# ================================
# AGRUPAR PREÇOS POR FAIXA
# ================================
def montar_tabela_precos(nome_base, produtos):
    """
    Retorna:
    {
      "base": {...},
      "1": {...},
      "25": {...},
      "50": {...},
      "100": {...},
      "250": {...},
      "500": {...},
      "1000": {...}
    }
    """
    tabela = {}

    for p in produtos:
        nome = descricao_produto(p)
        base = limpar_nome_base(nome)

        if normalizar_texto(base) != normalizar_texto(nome_base):
            continue

        qtd = extrair_quantidade_do_nome(nome)

        if qtd is None:
            tabela["base"] = p
        else:
            tabela[str(qtd)] = p

    return tabela

# ================================
# RESPOSTA DE PREÇOS
# ================================
def montar_resposta_precos(nome_base, tabela):
    partes = []
    partes.append(f"Encontrei os valores para {nome_base}:")

    # varejo
    varejo = None

    if "1" in tabela and preco_produto(tabela["1"]) is not None:
        varejo = preco_produto(tabela["1"])
    elif "base" in tabela and preco_produto(tabela["base"]) is not None:
        varejo = preco_produto(tabela["base"])

    if varejo is not None:
        partes.append(f"Varejo (1 unidade): R$ {formatar_reais(varejo)}.")

    # atacado
    faixas = [25, 50, 100, 250, 500, 1000]
    linhas_atacado = []

    for faixa in faixas:
        chave = str(faixa)
        if chave in tabela:
            valor_total = preco_produto(tabela[chave])
            if valor_total is not None:
                valor_unit = round(valor_total / faixa, 4)
                linhas_atacado.append(
                    f"{faixa}un: R$ {formatar_reais(valor_total)} no total (R$ {formatar_reais(valor_unit)} por unidade)"
                )

    if linhas_atacado:
        partes.append("Atacado:")
        partes.extend(linhas_atacado)

    partes.append("Se quiser, me diga a quantidade que eu te indico a melhor faixa.")
    return " ".join(partes)

# ================================
# PEGAR IMAGEM
# ================================
def encontrar_imagem_principal(tabela):
    """
    Prioridade:
    1) base
    2) 1un
    3) qualquer faixa
    """
    if "base" in tabela:
        url = imagem_produto(tabela["base"])
        if url:
            return url

    if "1" in tabela:
        url = imagem_produto(tabela["1"])
        if url:
            return url

    for chave in ["25", "50", "100", "250", "500", "1000"]:
        if chave in tabela:
            url = imagem_produto(tabela[chave])
            if url:
                return url

    return None

# ================================
# CLAUDE (fallback)
# ================================
def gerar_resposta_claude(mensagem):
    try:
        prompt = f"""
Você é um vendedor de caixas de papelão no WhatsApp.
Responda de forma curta, natural e objetiva.
Se o cliente não informar medida, peça comprimento, largura e altura.
Mensagem do cliente:
{mensagem}
"""

        resposta = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}]
        )

        return resposta.content[0].text.strip()

    except Exception as e:
        print("ERRO CLAUDE:", e)
        return "Para eu achar o modelo mais próximo, me passe o comprimento, largura e altura. Exemplo: 18x14,5x8,5."

# ================================
# WEBHOOK
# ================================
@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()
    mensagem = (form.get("Body") or "").strip()
    telefone = (form.get("From") or "").strip()

    print("MENSAGEM:", mensagem)
    print("TELEFONE:", telefone)

    produtos = carregar_produtos()
    twilio_response = MessagingResponse()

    try:
        nome_base = encontrar_melhor_nome_base(mensagem, produtos)

        if nome_base:
            tabela = montar_tabela_precos(nome_base, produtos)
            resposta_texto = montar_resposta_precos(nome_base, tabela)

            msg = twilio_response.message(resposta_texto)

            # envia imagem junto, se existir
            url_imagem = encontrar_imagem_principal(tabela)
            if url_imagem:
                print("IMAGEM ENCONTRADA:", url_imagem)
                msg.media(url_imagem)
            else:
                print("SEM IMAGEM PARA ESTE PRODUTO")

            return Response(content=str(twilio_response), media_type="application/xml")

        # fallback se não achou produto
        resposta_texto = (
            "Para eu encontrar o modelo mais próximo, me passe o comprimento, largura e altura. "
            "Exemplo: 18x14,5x8,5."
        )

        twilio_response.message(resposta_texto)
        return Response(content=str(twilio_response), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL NO WEBHOOK:", e)
        twilio_response.message(
            "Tive um probleminha interno agora. Me manda o comprimento, largura e altura da caixa que você precisa."
        )
        return Response(content=str(twilio_response), media_type="application/xml")

# ================================
# TESTES
# ================================
@app.get("/")
def home():
    return {"status": "ok"}

@app.get("/debug-produtos")
def debug_produtos():
    produtos = carregar_produtos()
    return {
        "total_produtos": len(produtos),
        "primeiro_produto": produtos[0] if produtos else None
    }
