import os
import pandas as pd
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

# =========================
# CLIENTES
# =========================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

claude = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY
)

# =========================
# CARREGAR PLANILHA
# =========================
ARQUIVO_PRODUTOS = "produtos.xlsx"

def carregar_produtos():
    try:
        df = pd.read_excel(ARQUIVO_PRODUTOS)

        # Limpa nomes das colunas
        df.columns = [str(col).strip() for col in df.columns]

        # Garante colunas esperadas
        for col in [
            "Código (SKU)",
            "Descrição",
            "Preço",
            "Largura embalagem",
            "Altura embalagem",
            "Comprimento embalagem"
        ]:
            if col not in df.columns:
                df[col] = None

        # Normaliza texto
        df["Descrição"] = df["Descrição"].fillna("").astype(str)
        df["Código (SKU)"] = df["Código (SKU)"].fillna("").astype(str)

        return df

    except Exception as e:
        print("ERRO AO CARREGAR PLANILHA:", e)
        return pd.DataFrame()

# carrega uma vez ao iniciar
df_produtos = carregar_produtos()

# =========================
# FUNÇÃO: BUSCAR PRODUTO NA PLANILHA
# =========================
def buscar_produto_planilha(texto_cliente: str):
    global df_produtos

    if df_produtos.empty:
        return None

    termo = texto_cliente.strip().lower()

    # busca por descrição
    resultados = df_produtos[
        df_produtos["Descrição"].str.lower().str.contains(termo, na=False)
    ]

    # se não achar por descrição, tenta por SKU
    if resultados.empty:
        resultados = df_produtos[
            df_produtos["Código (SKU)"].str.lower().str.contains(termo, na=False)
        ]

    # se ainda não achar, tenta por palavras soltas
    if resultados.empty:
        palavras = [p for p in termo.split() if len(p) >= 3]

        if palavras:
            filtro = pd.Series([True] * len(df_produtos))
            for palavra in palavras:
                filtro = filtro & df_produtos["Descrição"].str.lower().str.contains(palavra, na=False)
            resultados = df_produtos[filtro]

    if resultados.empty:
        return None

    produto = resultados.iloc[0]

    return {
        "sku": str(produto.get("Código (SKU)", "")).strip(),
        "descricao": str(produto.get("Descrição", "")).strip(),
        "preco": produto.get("Preço"),
        "largura": produto.get("Largura embalagem"),
        "altura": produto.get("Altura embalagem"),
        "comprimento": produto.get("Comprimento embalagem")
    }

# =========================
# FUNÇÃO: CLAUDE
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
                f"Se o cliente perguntar por caixas, embalagens, medidas, tamanhos, preco ou quantidade, "
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
# ROTA TESTE
# =========================
@app.get("/")
async def root():
    return {"status": "Bot rodando!"}

# =========================
# ROTA RECARREGAR PLANILHA
# =========================
@app.get("/recarregar-produtos")
async def recarregar_produtos():
    global df_produtos
    df_produtos = carregar_produtos()
    return {
        "status": "ok",
        "total_produtos": len(df_produtos)
    }

# =========================
# WEBHOOK
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
        # busca contato
        resultado = (
            supabase.table("contatos")
            .select("*")
            .eq("telefone", telefone)
            .execute()
        )

        contato = None

        if resultado.data and len(resultado.data) > 0:
            contato = resultado.data[0]

        # novo contato
        if not contato:
            supabase.table("contatos").insert({
                "telefone": telefone,
                "nome": None
            }).execute()

            resp.message("Olá! Seja bem-vindo. Qual é o seu nome?")
            return Response(content=str(resp), media_type="application/xml")

        nome = contato.get("nome")

        # salva nome
        if not nome:
            supabase.table("contatos").update({
                "nome": mensagem
            }).eq("telefone", telefone).execute()

            resp.message(f"Prazer, {mensagem}! Como posso te ajudar hoje?")
            return Response(content=str(resp), media_type="application/xml")

        # busca produto na planilha
        produto = buscar_produto_planilha(mensagem)

        if produto:
            descricao = produto["descricao"]
            preco = produto["preco"]
            largura = produto["largura"]
            altura = produto["altura"]
            comprimento = produto["comprimento"]

            resposta = (
                f"Tenho sim! {descricao}. "
                f"Preço: R$ {preco}. "
                f"Medidas da embalagem: {comprimento} x {largura} x {altura}. "
                f"Quantas unidades você precisa?"
            )

            resp.message(resposta)
            return Response(content=str(resp), media_type="application/xml")

        # fallback para IA
        resposta_ia = perguntar_claude(nome, mensagem)
        resp.message(resposta_ia)
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL NO WEBHOOK:", e)
        resp.message("Tive um probleminha interno agora, mas já estou corrigindo. Pode me mandar novamente?")
        return Response(content=str(resp), media_type="application/xml")
