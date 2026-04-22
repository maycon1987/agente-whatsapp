from fastapi import FastAPI, Request
from fastapi.responses import Response
import os
import csv
from twilio.twiml.messaging_response import MessagingResponse
import requests
from anthropic import Anthropic

app = FastAPI()

# ================================
# CONFIG
# ================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ================================
# DEBUG (VER ARQUIVOS NO RAILWAY)
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
        with open("produtos.csv", encoding="utf-8") as f:
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
    texto_usuario = texto_usuario.lower()

    for p in produtos:
        descricao = (p.get("Descrição") or "").lower()

        if texto_usuario in descricao:
            return p

    return None

# ================================
# FUNÇÃO: IA (CLAUDE)
# ================================

def gerar_resposta(mensagem, produto=None):
    contexto = ""

    if produto:
        contexto = f"""
Produto encontrado:
Nome: {produto.get('Descrição')}
Preço: {produto.get('Preço')}
Estoque: {produto.get('Estoque')}
"""

    prompt = f"""
Você é um vendedor especialista em WhatsApp.

{contexto}

Mensagem do cliente:
{mensagem}

Responda de forma natural, como vendedor, tentando vender.
"""

    resposta = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return resposta.content[0].text

# ================================
# WEBHOOK TWILIO
# ================================

@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()
    mensagem = form.get("Body", "")
    telefone = form.get("From", "")

    print("MENSAGEM:", mensagem)

    # carregar produtos
    produtos = carregar_produtos()

    # buscar produto
    produto = buscar_produto(mensagem, produtos)

    # gerar resposta
    resposta_texto = gerar_resposta(mensagem, produto)

    # resposta Twilio
    twilio_response = MessagingResponse()
    twilio_response.message(resposta_texto)

    return Response(content=str(twilio_response), media_type="application/xml")

# ================================
# TESTE ROOT
# ================================

@app.get("/")
def home():
    return {"status": "ok"}
