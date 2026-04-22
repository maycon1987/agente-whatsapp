import os
import csv
import re
import unicodedata
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
# FUNÇÕES ÚTEIS
# =========================
def normalizar_texto(texto: str) -> str:
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto

def limpar_valor(valor):
    if valor is None:
        return ""
    return str(valor).strip()

def extrair_medidas_do_texto(texto: str):
    """
    Tenta achar medidas tipo:
    30x20x15
    30 x 20 x 15
    """
    texto_norm = normalizar_texto(texto)
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)", texto_norm)
    if not match:
        return None

    def to_float(v):
        return float(v.replace(",", "."))

    return (
        to_float(match.group(1)),
        to_float(match.group(2)),
        to_float(match.group(3)),
    )

def para_float(valor):
    if valor is None:
        return None
    valor = str(valor).strip().replace(".", "").replace(",", ".")
    try:
        return float(valor)
    except:
        try:
            # se já vier em formato normal
            return float(str(valor).strip())
        except:
            return None

# =========================
# CARREGAR PRODUTOS CSV
# =========================
def carregar_produtos():
    produtos = []

    caminhos_teste = [
        "produtos.csv",
        "./produtos.csv",
        "/app/produtos.csv"
    ]

    arquivo_encontrado = None

    for caminho in caminhos_teste:
        if os.path.exists(caminho):
            arquivo_encontrado = caminho
            break

    if not arquivo_encontrado:
        print("ERRO: produtos.csv não encontrado.")
        return produtos

    try:
        with open(arquivo_encontrado, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # normaliza cabeçalhos
                row_normalizado = {}
                for chave, valor in row.items():
                    row_normalizado[normalizar_texto(chave)] = limpar_valor(valor)

                produtos.append(row_normalizado)

        print(f"CSV carregado com sucesso. Total de produtos: {len(produtos)}")

    except Exception as e:
        print("ERRO AO LER CSV:", e)

    return produtos

PRODUTOS = carregar_produtos()

# =========================
# BUSCAR PRODUTO NO CSV
# =========================
def buscar_produto_csv(mensagem_usuario: str):
    """
    Busca primeiro por medida (30x20x15).
    Se não achar, busca por palavras na descrição / SKU.
    """
    texto = normalizar_texto(mensagem_usuario)

    if not PRODUTOS:
        return None

    # ---------------------------------
    # 1) TENTAR BUSCAR POR MEDIDAS
    # ---------------------------------
    medidas = extrair_medidas_do_texto(texto)
    if medidas:
        comp_msg, larg_msg, alt_msg = medidas

        for p in PRODUTOS:
            comp = para_float(p.get("comprimento embalagem"))
            larg = para_float(p.get("largura embalagem"))
            alt = para_float(p.get("altura embalagem"))

            if comp is None or larg is None or alt is None:
                continue

            # compara exatamente
            if comp == comp_msg and larg == larg_msg and alt == alt_msg:
                return p

            # também tenta ordem alternativa comum
            if (
                {comp, larg, alt} == {comp_msg, larg_msg, alt_msg}
            ):
                return p

    # ---------------------------------
    # 2) TENTAR BUSCAR POR DESCRIÇÃO / SKU
    # ---------------------------------
    palavras = [p for p in texto.split() if len(p) >= 3]

    melhor_produto = None
    melhor_pontuacao = 0

    for p in PRODUTOS:
        descricao = normalizar_texto(p.get("descricao"))
        sku = normalizar_texto(p.get("codigo (sku)"))
        categoria = normalizar_texto(p.get("categoria"))
        marca = normalizar_texto(p.get("marca"))

        campo_busca = f"{descricao} {sku} {categoria} {marca}"

        pontuacao = 0
        for palavra in palavras:
            if palavra in campo_busca:
                pontuacao += 1

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_produto = p

    if melhor_pontuacao > 0:
        return melhor_produto

    return None

# =========================
# MONTAR RESPOSTA DO PRODUTO
# =========================
def montar_resposta_produto(produto):
    descricao = produto.get("descricao", "Produto")
    preco = produto.get("preco", "")
    estoque = produto.get("estoque", "")
    sku = produto.get("codigo (sku)", "")

    largura = produto.get("largura embalagem", "")
    altura = produto.get("altura embalagem", "")
    comprimento = produto.get("comprimento embalagem", "")

    partes = []

    partes.append(f"Tenho sim! {descricao}.")

    medidas_ok = largura or altura or comprimento
    if medidas_ok:
        partes.append(
            f"Medidas da embalagem: {comprimento} x {largura} x {altura}."
        )

    if preco:
        partes.append(f"Preço: R$ {preco}.")

    if estoque:
        partes.append(f"Estoque atual: {estoque}.")

    if sku:
        partes.append(f"Código: {sku}.")

    partes.append("Quantas unidades você precisa?")

    return " ".join(partes)

# =========================
# CLAUDE
# =========================
def perguntar_claude(nome: str, mensagem: str) -> str:
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            system=(
                f"Voce e um vendedor especialista em WhatsApp chamado Robo. "
                f"Voce conversa com {nome}. "
                f"Seu objetivo e ajudar e vender. "
                f"Nao se apresente toda hora. "
                f"Nao repita frases. "
                f"Seja natural, direto, curto e humano. "
                f"Se o cliente perguntar sobre embalagens, caixas, medidas, preco ou quantidade, "
                f"conduza para venda com perguntas objetivas."
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
    return {"status": "ok"}

# =========================
# ROTA TESTE CSV
# =========================
@app.get("/debug-produtos")
async def debug_produtos():
    return {
        "total_produtos": len(PRODUTOS),
        "primeiro_produto": PRODUTOS[0] if PRODUTOS else None
    }

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
        # -------------------------
        # BUSCAR CONTATO
        # -------------------------
        resultado = (
            supabase.table("contatos")
            .select("*")
            .eq("telefone", telefone)
            .execute()
        )

        contato = None
        if resultado.data and len(resultado.data) > 0:
            contato = resultado.data[0]

        # -------------------------
        # NOVO CONTATO
        # -------------------------
        if not contato:
            print("NOVO CONTATO")

            supabase.table("contatos").insert({
                "telefone": telefone,
                "nome": None
            }).execute()

            resp.message("Olá! Seja bem-vindo. Qual é o seu nome?")
            return Response(content=str(resp), media_type="application/xml")

        nome = contato.get("nome")

        # -------------------------
        # AINDA SEM NOME
        # -------------------------
        if not nome:
            print("SALVANDO NOME:", mensagem)

            supabase.table("contatos").update({
                "nome": mensagem
            }).eq("telefone", telefone).execute()

            resp.message(f"Prazer, {mensagem}! Como posso te ajudar hoje?")
            return Response(content=str(resp), media_type="application/xml")

        # -------------------------
        # BUSCA NA PLANILHA
        # -------------------------
        produto = buscar_produto_csv(mensagem)

        if produto:
            resposta = montar_resposta_produto(produto)
            print("RESPOSTA VIA CSV:", resposta)
            resp.message(resposta)
            return Response(content=str(resp), media_type="application/xml")

        # -------------------------
        # IA RESPONDE
        # -------------------------
        resposta_ia = perguntar_claude(nome, mensagem)
        print("RESPOSTA VIA CLAUDE:", resposta_ia)
        resp.message(resposta_ia)
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL NO WEBHOOK:", e)
        resp.message("Tive um probleminha interno agora, mas já estou corrigindo. Pode me mandar novamente?")
        return Response(content=str(resp), media_type="application/xml")
