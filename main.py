import os
import re
import json
import pandas as pd
from fastapi import FastAPI, Form, Response
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

app = FastAPI()

# =========================
# CONFIG
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ARQUIVO_PRODUTOS = "produtos.xlsx"


# =========================
# CARREGAR EXCEL
# =========================
def carregar_produtos():
    try:
        df = pd.read_excel(ARQUIVO_PRODUTOS)
        df.columns = [str(c).strip().lower() for c in df.columns]

        colunas_necessarias = ["nome", "modelo", "medida", "preco", "descricao"]
        for col in colunas_necessarias:
            if col not in df.columns:
                df[col] = ""

        df = df.fillna("")
        return df

    except Exception as e:
        print("ERRO AO CARREGAR EXCEL:", e)
        return pd.DataFrame(columns=["nome", "modelo", "medida", "preco", "descricao"])


produtos_df = carregar_produtos()


# =========================
# UTILS
# =========================
def normalizar_texto(texto: str) -> str:
    texto = str(texto).strip().lower()
    texto = texto.replace("caixa de papelão", "caixa")
    texto = texto.replace("caixa de papelao", "caixa")
    texto = texto.replace(",", ".")
    return texto


def normalizar_medida(texto: str) -> str:
    texto = normalizar_texto(texto)
    texto = texto.replace(" ", "")
    texto = texto.replace("*", "x")
    texto = texto.replace("×", "x")

    # remove casas decimais .0 desnecessárias se quiser comparar mais fácil
    return texto


def extrair_medida_regex(texto: str):
    texto = normalizar_medida(texto)
    padrao = r'(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)'
    achou = re.search(padrao, texto)

    if achou:
        return f"{achou.group(1)}x{achou.group(2)}x{achou.group(3)}"
    return None


def extrair_modelo_regex(texto: str):
    texto = normalizar_texto(texto)

    # captura tipo n18, n20, n 18
    padrao = r'\bn\s*?(\d{1,3})\b'
    achou = re.search(padrao, texto)
    if achou:
        return f"n{achou.group(1)}"
    return None


# =========================
# IA PARA INTERPRETAR A PERGUNTA
# =========================
def interpretar_pergunta(mensagem: str):
    """
    A IA interpreta a intenção e tenta extrair:
    - tipo_busca: medida | modelo | nome | desconhecido
    - valor
    - intencao: preco | disponibilidade | compra | duvida
    """
    prompt = f"""
Você é um extrator de intenção para um bot de vendas de caixas de papelão.
Analise a mensagem do cliente e devolva SOMENTE JSON válido.

Regras:
- Se houver medida como 30x20x15, use tipo_busca = "medida"
- Se houver modelo como N18, use tipo_busca = "modelo"
- Se citar um nome de produto sem medida/modelo, use tipo_busca = "nome"
- Se não der para entender, use tipo_busca = "desconhecido"
- intencao deve ser uma destas:
  "preco", "disponibilidade", "compra", "duvida"
- valor deve ser string
- Não escreva nada fora do JSON

Mensagem do cliente:
{mensagem}

Formato de saída:
{{
  "tipo_busca": "medida",
  "valor": "30x20x15",
  "intencao": "preco"
}}
"""

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        texto = response.content[0].text.strip()
        dados = json.loads(texto)

        return {
            "tipo_busca": str(dados.get("tipo_busca", "desconhecido")).strip().lower(),
            "valor": str(dados.get("valor", "")).strip(),
            "intencao": str(dados.get("intencao", "duvida")).strip().lower()
        }

    except Exception as e:
        print("ERRO AO INTERPRETAR COM IA:", e)

        # fallback inteligente sem IA
        medida = extrair_medida_regex(mensagem)
        if medida:
            return {
                "tipo_busca": "medida",
                "valor": medida,
                "intencao": "preco" if "valor" in mensagem.lower() or "preço" in mensagem.lower() or "preco" in mensagem.lower() else "disponibilidade"
            }

        modelo = extrair_modelo_regex(mensagem)
        if modelo:
            return {
                "tipo_busca": "modelo",
                "valor": modelo,
                "intencao": "preco" if "valor" in mensagem.lower() or "preço" in mensagem.lower() or "preco" in mensagem.lower() else "disponibilidade"
            }

        return {
            "tipo_busca": "desconhecido",
            "valor": "",
            "intencao": "duvida"
        }


# =========================
# BUSCA NO EXCEL
# =========================
def buscar_produto_no_excel(mensagem: str):
    global produtos_df

    if produtos_df.empty:
        return None

    interpretacao = interpretar_pergunta(mensagem)
    tipo_busca = interpretacao["tipo_busca"]
    valor = normalizar_texto(interpretacao["valor"])
    intencao = interpretacao["intencao"]

    print("INTERPRETACAO:", interpretacao)

    # Primeiro tenta busca direta por regex local, porque ajuda bastante
    medida_local = extrair_medida_regex(mensagem)
    modelo_local = extrair_modelo_regex(mensagem)

    if tipo_busca == "medida" or medida_local:
        medida_busca = normalizar_medida(medida_local or valor)

        for _, row in produtos_df.iterrows():
            medida_planilha = normalizar_medida(row.get("medida", ""))
            if medida_planilha == medida_busca:
                return {
                    "nome": row.get("nome", ""),
                    "modelo": row.get("modelo", ""),
                    "medida": row.get("medida", ""),
                    "preco": row.get("preco", ""),
                    "descricao": row.get("descricao", ""),
                    "intencao": intencao
                }

    if tipo_busca == "modelo" or modelo_local:
        modelo_busca = normalizar_texto(modelo_local or valor).replace(" ", "")

        for _, row in produtos_df.iterrows():
            modelo_planilha = normalizar_texto(row.get("modelo", "")).replace(" ", "")
            nome_planilha = normalizar_texto(row.get("nome", "")).replace(" ", "")

            if modelo_planilha == modelo_busca or modelo_busca in nome_planilha:
                return {
                    "nome": row.get("nome", ""),
                    "modelo": row.get("modelo", ""),
                    "medida": row.get("medida", ""),
                    "preco": row.get("preco", ""),
                    "descricao": row.get("descricao", ""),
                    "intencao": intencao
                }

    if tipo_busca == "nome" and valor:
        valor_norm = normalizar_texto(valor)

        for _, row in produtos_df.iterrows():
            nome_planilha = normalizar_texto(row.get("nome", ""))
            descricao_planilha = normalizar_texto(row.get("descricao", ""))

            if valor_norm in nome_planilha or valor_norm in descricao_planilha:
                return {
                    "nome": row.get("nome", ""),
                    "modelo": row.get("modelo", ""),
                    "medida": row.get("medida", ""),
                    "preco": row.get("preco", ""),
                    "descricao": row.get("descricao", ""),
                    "intencao": intencao
                }

    return None


# =========================
# RESPOSTA DE VENDAS COM IA
# =========================
def responder_com_ia(nome_cliente: str, mensagem: str) -> str:
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                f"Você é um vendedor especialista em caixas de papelão via WhatsApp. "
                f"Você conversa com {nome_cliente}. "
                f"Seja natural, curto, direto e humano. "
                f"Nunca invente preço ou medida se não tiver certeza. "
                f"Quando faltar informação, faça uma pergunta objetiva."
            ),
            messages=[
                {"role": "user", "content": mensagem}
            ]
        )

        return response.content[0].text.strip()

    except Exception as e:
        print("ERRO RESPOSTA IA:", e)
        return "Recebi sua mensagem. Me diga o modelo ou a medida da caixa que você procura."


# =========================
# MONTAR RESPOSTA A PARTIR DO EXCEL
# =========================
def montar_resposta_produto(produto: dict) -> str:
    nome = produto.get("nome", "")
    modelo = produto.get("modelo", "")
    medida = produto.get("medida", "")
    preco = produto.get("preco", "")
    descricao = produto.get("descricao", "")
    intencao = produto.get("intencao", "duvida")

    titulo = nome
    if modelo:
        titulo += f" ({modelo})"

    detalhes = []
    if medida:
        detalhes.append(f"medida {medida}")
    if preco != "":
        detalhes.append(f"R$ {preco}")

    detalhes_txt = ", ".join(detalhes)

    if intencao == "preco":
        if preco != "":
            return f"Tenho sim! {titulo} - {detalhes_txt}. Quantas unidades você precisa?"
        return f"Encontrei {titulo}, mas o preço não está cadastrado. Quer que eu te ajude com quantidade ou medida?"

    if intencao == "disponibilidade":
        if detalhes_txt:
            return f"Tenho sim! {titulo} - {detalhes_txt}. Quantas unidades você precisa?"
        return f"Tenho sim! {titulo}. Quantas unidades você precisa?"

    if intencao == "compra":
        return f"Perfeito! {titulo} - {detalhes_txt}. Quantas unidades você deseja?"

    return f"Encontrei {titulo} - {detalhes_txt}. Quer saber preço, quantidade ou mais detalhes?"


# =========================
# ENDPOINTS
# =========================
@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/debug")
async def debug():
    return {
        "status": "ok",
        "arquivo_produtos": ARQUIVO_PRODUTOS,
        "qtd_produtos": int(len(produtos_df))
    }


@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(...)
):
    telefone = From
    mensagem = Body.strip()

    print("MENSAGEM RECEBIDA:", telefone, mensagem)

    resp = MessagingResponse()

    try:
        # Atualiza dataframe a cada mensagem para refletir mudanças no arquivo
        global produtos_df
        produtos_df = carregar_produtos()

        # Busca ou cria contato
        resultado = (
            supabase.table("contatos")
            .select("*")
            .eq("telefone", telefone)
            .execute()
        )

        if not resultado.data:
            supabase.table("contatos").insert({
                "telefone": telefone,
                "nome": None
            }).execute()

            resp.message("Olá! Seja bem-vindo 😊 Qual é o seu nome?")
            return Response(content=str(resp), media_type="application/xml")

        contato = resultado.data[0]
        nome_cliente = contato.get("nome")

        # Se ainda não tem nome salvo
        if not nome_cliente:
            supabase.table("contatos").update({
                "nome": mensagem
            }).eq("telefone", telefone).execute()

            resp.message(f"Prazer, {mensagem}! Me diga o modelo ou a medida da caixa que você procura.")
            return Response(content=str(resp), media_type="application/xml")

        # PRIMEIRO: tenta achar produto no Excel
        produto = buscar_produto_no_excel(mensagem)

        if produto:
            resposta = montar_resposta_produto(produto)
            resp.message(resposta)
            return Response(content=str(resp), media_type="application/xml")

        # Se não achou produto, IA responde sem inventar preço
        resposta_ia = responder_com_ia(nome_cliente, mensagem)
        resp.message(resposta_ia)
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print("ERRO GERAL WEBHOOK:", e)
        resp.message("Tive um erro interno aqui, mas já estou corrigindo. Pode mandar novamente em alguns segundos?")
        return Response(content=str(resp), media_type="application/xml")
