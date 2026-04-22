import os
import requests
from fastapi import FastAPI, Form, Response
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

app = FastAPI()

# =========================
# VARIÁVEIS DE AMBIENTE
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TINY_API_KEY = os.getenv("TINY_API_KEY")

# =========================
# CLIENTES
# =========================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

claude = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY
)

# =========================
# FUNÇÃO: BUSCAR PRODUTO NO TINY
# =========================
def buscar_produto_tiny(termo_busca: str):
    """
    Busca produto no Tiny pelo texto enviado pelo cliente.
    Retorna dict com nome, preco e codigo se encontrar.
    Retorna None se não encontrar.
    """
    if not TINY_API_KEY:
        print("ERRO: TINY_API_KEY não configurada.")
        return None

    url = "https://api.tiny.com.br/api2/produtos.pesquisa.php"

    params = {
        "token": TINY_API_KEY,
        "formato": "json",
        "pesquisa": termo_busca
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        print("RETORNO TINY:", data)

        retorno = data.get("retorno", {})
        produtos = retorno.get("produtos", [])

        if not produtos:
            return None

        produto = produtos[0].get("produto", {})

        return {
            "nome": produto.get("nome"),
            "preco": produto.get("preco"),
            "codigo": produto.get("codigo")
        }

    except Exception as e:
        print("ERRO AO CONSULTAR TINY:", e)
        return None

# =========================
# FUNÇÃO: PERGUNTAR AO CLAUDE
# =========================
def perguntar_claude(nome: str, mensagem: str) -> str:
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                f"Voce e um vendedor especialista em WhatsApp chamado Robo. "
                f"Voce conversa com {nome}. "
                f"Seu objetivo e ajudar e vender. "
                f"Nao se apresente toda hora. "
                f"Nao repita frases. "
                f"Seja natural, humano, direto e curto. "
                f"Se o cliente falar de caixas, embalagens, medidas, tamanhos, preco ou quantidade, "
                f"conduza a conversa para entender a necessidade e fechar a venda."
            ),
            messages=[
                {"role": "user", "content": mensagem}
            ]
        )

        return response.content[0].text.strip()

    except Exception as e:
        print("ERRO CLAUDE:", e)
        return "Recebi sua mensagem e já vou te ajudar."

# =========================
# ROTA DE TESTE
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
    telefone = From.strip()
    mensagem = Body.strip()

    print("===================================")
    print("MENSAGEM RECEBIDA")
    print("Telefone:", telefone)
    print("Mensagem:", mensagem)
    print("===================================")

    resp = MessagingResponse()

    try:
        # =========================
        # BUSCAR CONTATO
        # =========================
        resultado = (
            supabase.table("contatos")
            .select("*")
            .eq("telefone", telefone)
            .execute()
        )

        contato = None

        if resultado.data and len(resultado.data) > 0:
            contato = resultado.data[0]

        # =========================
        # NOVO CONTATO
        # =========================
        if not contato:
            print("NOVO CONTATO - criando no Supabase")

            supabase.table("contatos").insert({
                "telefone": telefone,
                "nome": None
            }).execute()

            resp.message("Olá! Seja bem-vindo. Qual é o seu nome?")
            return Response(content=str(resp), media_type="application/xml")

        nome = contato.get("nome")

        # =========================
        # SE AINDA NÃO TEM NOME
        # =========================
        if not nome:
            print("SALVANDO NOME:", mensagem)

            supabase.table("contatos").update({
                "nome": mensagem
            }).eq("telefone", telefone).execute()

            resp.message(f"Prazer, {mensagem}! Como posso te ajudar hoje?")
            return Response(content=str(resp), media_type="application/xml")

        # =========================
        # TENTAR BUSCAR PRODUTO NO TINY
        # =========================
        produto = buscar_produto_tiny(mensagem)

        if produto:
            nome_produto = produto.get("nome", "Produto")
            preco_produto = produto.get("preco", "sob consulta")

            resposta = (
                f"Tenho sim! {nome_produto} por R$ {preco_produto}. "
                f"Quantas unidades você precisa?"
            )

            print("RESPOSTA VIA TINY:", resposta)
            resp.message(resposta)
            return Response(content=str(resp), media_type="application/xml")

        # =========================
        # SE NÃO ACHAR PRODUTO, USA CLAUDE
        # =========================
        resposta_ia = perguntar_claude(nome, mensagem)

        print("RESPOSTA VIA CLAUDE:", resposta_ia)
        resp.message(resposta_ia)
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL NO WEBHOOK:", e)
        resp.message("Tive um probleminha interno agora, mas já estou corrigindo. Pode me mandar novamente?")
        return Response(content=str(resp), media_type="application/xml")
