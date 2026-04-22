import os
from fastapi import FastAPI, Form, Response
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

app = FastAPI()

# =========================
# SUPABASE
# =========================
supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"]
)

# =========================
# CLAUDE
# =========================
claude = anthropic.Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"]
)

def perguntar_claude(nome: str, mensagem: str) -> str:
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                f"Voce e um atendente humano via WhatsApp chamado Robo. "
                f"Voce esta conversando com {nome}. "
                f"NUNCA se apresente toda hora. "
                f"Nao repita frases. "
                f"Seja direto, natural e humano. "
                f"Respostas curtas, como conversa real."
            ),
            messages=[
                {"role": "user", "content": mensagem}
            ]
        )
        return response.content[0].text.strip()

    except Exception as e:
        print("ERRO CLAUDE:", e)
        return "Recebi sua mensagem! Ja vou te ajudar."

# =========================
# TESTE
# =========================
@app.get("/")
async def root():
    return {"status": "Bot rodando!"}

# =========================
# WEBHOOK WHATSAPP
# =========================
@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(...)
):
    telefone = From
    mensagem = Body.strip()

    print("MSG RECEBIDA:", telefone, mensagem)

    resp = MessagingResponse()

    try:
        # =========================
        # BUSCA CONTATO
        # =========================
        resultado = (
            supabase.table("contatos")
            .select("*")
            .eq("telefone", telefone)
            .execute()
        )

        # =========================
        # NOVO CONTATO
        # =========================
        if not resultado.data:
            print("NOVO CONTATO")

            supabase.table("contatos").insert({
                "telefone": telefone,
                "nome": None
            }).execute()

            resp.message("Olá! Seja bem-vindo 👋 Qual é o seu nome?")
            return Response(content=str(resp), media_type="application/xml")

        contato = resultado.data[0]
        nome = contato.get("nome")

        # =========================
        # SALVAR NOME
        # =========================
        if not nome:
            print("SALVANDO NOME")

            supabase.table("contatos").update({
                "nome": mensagem
            }).eq("telefone", telefone).execute()

            resp.message(f"Prazer, {mensagem}! 😊 Como posso te ajudar?")
            return Response(content=str(resp), media_type="application/xml")

        # =========================
        # IA RESPONDE
        # =========================
        print("USANDO IA")

        resposta_ia = perguntar_claude(nome, mensagem)

        resp.message(resposta_ia)
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL:", e)

        resp.message("Tive um probleminha aqui 😅 mas já estou corrigindo!")
        return Response(content=str(resp), media_type="application/xml")
