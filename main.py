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
        model="claude-opus-4-20250514",
        max_tokens=500,
        system=f"""Você é um assistente virtual simpático e prestativo chamado Robo. 
        Você está conversando com {nome} via WhatsApp.
        Responda de forma curta e amigável, máximo 3 frases.""",
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

    resultado = supabase.table("contatos")\
        .select("*")\
        .eq("telefone", telefone)\
        .execute()

    resp = MessagingResponse()

    if not resultado.data:
        supabase.table("contatos
