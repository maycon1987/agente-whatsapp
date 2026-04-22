import os
from fastapi import FastAPI, Request, Form, Response
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"]
)

@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(...)
):
    telefone = From
    mensagem = Body.strip()

    # Busca contato no banco
    resultado = supabase.table("contatos")\
        .select("*")\
        .eq("telefone", telefone)\
        .execute()

    resp = MessagingResponse()

    if not resultado.data:
        # Primeiro contato — salva e pergunta o nome
        supabase.table("contatos")\
            .insert({"telefone": telefone, "nome": None})\
            .execute()
        resp.message("Olá! 👋 Seja bem-vindo! Qual é o seu nome?")

    else:
        contato = resultado.data[0]

        if not contato.get("nome"):
            # Ainda não tem nome — salva o nome que veio
            supabase.table("contatos")\
                .update({"nome": mensagem})\
                .eq("telefone", telefone)\
                .execute()
            resp.message(f"Prazer, {mensagem}! 😊 Como posso te ajudar?")

        else:
            # Já tem nome — responde normalmente
            nome = contato["nome"]
            resp.message(f"Oi {nome}! Recebi sua mensagem: '{mensagem}' 😊")

    return Response(content=str(resp), media_type="application/xml")
