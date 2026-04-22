import os
from fastapi import FastAPI, Form, Response
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

app = FastAPI()

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"]
)

claude = anthropic.Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"]
)

def perguntar_claude(nome: str, mensagem: str) -> str:
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=f"""Voce e um assistente virtual simpatico chamado Robo.
        Voce esta conversando com {nome} via WhatsApp.
        Responda de forma curta e amigavel, maximo 3 frases.""",
        messages=[
            {"role": "user", "content": mensagem}
        ]
    )
    return response.content[0].text

@app.get("/")
async def root():
    return {"status": "Bot rodando!"}

@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(...)
):
    telefone = From
    mensagem = Body.strip()

    resultado = supabase.table("contatos").select("*").eq("telefone", telefone).execute()

    resp = MessagingResponse()

    if not resultado.data:
        supabase.table("contatos").insert({"telefone": telefone, "nome": None}).execute()
        resp.message("Ola! Seja bem-vindo! Qual e o seu nome?")

    else:
        contato = resultado.data[0]

        if not contato.get("nome"):
            supabase.table("contatos").update({"nome": mensagem}).eq("telefone", telefone).execute()
            resp.message(f"Prazer, {mensagem}! Como posso te ajudar?")

        else:
            nome = contato["nome"]
            resposta_ia = perguntar_claude(nome, mensagem)
            resp.message(resposta_ia)

    return Response(content=str(resp), media_type="application/xml")
