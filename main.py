from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from supabase import create_client
import os

app = FastAPI()

# URL fixa do seu projeto Supabase
SUPABASE_URL = "https://evhatuahmdoobyawmapw.supabase.co"

# Só a chave vem do Railway
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY não configurada no Railway")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
def home():
    return {"status": "ok"}

@app.get("/debug")
def debug():
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_key_ok": bool(SUPABASE_KEY),
    }

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.form()

    numero = data.get("From")
    mensagem = data.get("Body")

    contato = supabase.table("contatos").upsert({
        "telefone": numero
    }).execute()

    contato_id = contato.data[0]["id"]

    conversa = supabase.table("conversas").insert({
        "contato_id": contato_id,
        "numero_whatsapp": numero
    }).execute()

    conversa_id = conversa.data[0]["id"]

    supabase.table("mensagens").insert({
        "conversa_id": conversa_id,
        "texto": mensagem,
        "quem_enviou": "cliente"
    }).execute()

    resposta = "Olá! Recebi sua mensagem. Em breve um atendente vai falar com você."

    supabase.table("mensagens").insert({
        "conversa_id": conversa_id,
        "texto": resposta,
        "quem_enviou": "bot"
    }).execute()

    return PlainTextResponse(
        f"<Response><Message>{resposta}</Message></Response>",
        media_type="application/xml"
    )
