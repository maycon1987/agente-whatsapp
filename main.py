from fastapi import FastAPI, Request
from supabase import create_client
import os

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
def home():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.form()

    numero = data.get("From")
    mensagem = data.get("Body")

    print(numero, mensagem)

    # salvar contato
    contato = supabase.table("contatos").upsert({
        "telefone": numero
    }).execute()

    contato_id = contato.data[0]["id"]

    # criar conversa
    conversa = supabase.table("conversas").insert({
        "contato_id": contato_id,
        "numero_whatsapp": numero
    }).execute()

    conversa_id = conversa.data[0]["id"]

    # salvar mensagem cliente
    supabase.table("mensagens").insert({
        "conversa_id": conversa_id,
        "texto": mensagem,
        "quem_enviou": "cliente"
    }).execute()

    # resposta automática
    resposta = "Olá! Recebi sua mensagem 👍 Em breve um atendente vai falar com você."

    # salvar resposta
    supabase.table("mensagens").insert({
        "conversa_id": conversa_id,
        "texto": resposta,
        "quem_enviou": "bot"
    }).execute()

    return f"<Response><Message>{resposta}</Message></Response>"
