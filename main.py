from fastapi import FastAPI, Request
from fastapi.responses import Response
import os
import csv
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
# FUNÇÃO: LER PRODUTOS CSV
# ================================
def carregar_produtos():
    produtos = []

    try:
        with open("produtos.csv", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                produtos.append(row)
    except Exception as e:
        print("ERRO AO LER CSV:", e)

    return produtos

# ================================
# FUNÇÃO: BUSCAR PRODUTO
# ================================
def buscar_produto(texto_usuario, produtos):
    texto_usuario = texto_usuario.lower().strip()

    for p in produtos:
        descricao = (p.get("Descrição") or "").lower()
        sku = (p.get("Código (SKU)") or "").lower()

        if texto_usuario in descricao or texto_usuario in sku:
            return p

    return None

# ================================
# FUNÇÃO: IA (CLAUDE)
# ================================
def gerar_resposta(mensagem, produto=None):
    try:
        contexto = ""

        if produto:
            contexto = f"""
Produto encontrado:
Nome: {produto.get('Descrição')}
Preço: {produto.get('Preço')}
Estoque: {produto.get('Estoque')}
Largura embalagem: {produto.get('Largura embalagem')}
Altura embalagem: {produto.get('Altura embalagem')}
Comprimento embalagem: {produto.get('Comprimento embalagem')}
"""

        prompt = f"""
Você é um vendedor especialista em WhatsApp.

{contexto}

Mensagem do cliente:
{mensagem}

Responda de forma natural, curta e como vendedor.
Se houver produto encontrado, use os dados reais dele.
"""

        resposta = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        return resposta.content[0].text

    except Exception as e:
        print("ERRO CLAUDE:", e)
        return "Recebi sua mensagem! Pode me falar mais detalhes do produto que você precisa?"

# ================================
# WEBHOOK TWILIO
# ================================
@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()
    mensagem = form.get("Body", "")
    telefone = form.get("From", "")

    print("MENSAGEM:", mensagem)
    print("TELEFONE:", telefone)

    produtos = carregar_produtos()
    produto = buscar_produto(mensagem, produtos)

    resposta_texto = gerar_resposta(mensagem, produto)

    twilio_response = MessagingResponse()
    twilio_response.message(resposta_texto)

    return Response(content=str(twilio_response), media_type="application/xml")

# ================================
# TESTE ROOT
# ================================
@app.get("/")
def home():
    return {"status": "ok"}

# ================================
# TESTE DA PLANILHA
# ================================
@app.get("/debug-produtos")
def debug_produtos():
    produtos = carregar_produtos()
    return {
        "total_produtos": len(produtos),
        "primeiro_produto": produtos[0] if produtos else None
    }
