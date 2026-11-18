"""
Camada de Apresentação (UI) - Associação Acolher e Transformar.

Telas:
    Tela 1 - Login e Cadastro de voluntários        (RF01, RF02)
    Tela 2 - Painel de gestão, busca e atualização  (RF03)
    Tela 3 - Feedback visual e exportação CSV       (RF04)

Executar:
    streamlit run app.py
"""

from __future__ import annotations

import time
from datetime import datetime

import streamlit as st

import auth
import database
from database import STATUS_VALIDOS, EmailDuplicadoError

st.set_page_config(
    page_title="Acolher e Transformar",
    page_icon="🤝",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAX_TENTATIVAS_LOGIN = 5
BLOQUEIO_LOGIN_SEGUNDOS = 60
OPCAO_TODOS = "Todos"
ESCOPO_FILTRADOS = "Somente os registros filtrados no painel"
ESCOPO_TODOS = "Todos os meus registros"

# --------------------------------------------------------------------------- #
# CSS acessível (RNF04 - WCAG 2.1 AA)
#   * alvos de toque >= 48px (mínimo exigido: 44x44px)
#   * contraste: texto #1A1A1A / #FFFFFF (~17:1); botões #FFFFFF / #0B3D91 (~10:1)
#   * foco de teclado visível; rótulos sempre visíveis (nunca só placeholder)
# --------------------------------------------------------------------------- #
CSS_ACESSIVEL = """
<style>
    .stApp { background-color: #FFFFFF; color: #1A1A1A; }
    [data-testid="stSidebar"] { background-color: #EEF2F9; }
    html, body, [class*="css"] { font-size: 16px; line-height: 1.5; }

    h1, h2, h3, h4 { color: #0B2A5B; }
    [data-testid="stCaptionContainer"], .stCaption { color: #3D3D3D !important; font-size: 0.95rem; }

    /* Rótulos persistentes e legíveis */
    [data-testid="stWidgetLabel"] p, label, label p {
        color: #1A1A1A !important; font-size: 1rem !important; font-weight: 600 !important;
    }

    /* Campos de entrada >= 48px */
    div[data-baseweb="input"], div[data-baseweb="base-input"] { min-height: 48px; }
    div[data-baseweb="input"] input, div[data-baseweb="base-input"] input,
    textarea { min-height: 48px; font-size: 1rem !important; color: #1A1A1A !important; }
    div[data-baseweb="select"] > div { min-height: 48px; font-size: 1rem; }
    div[data-baseweb="input"], div[data-baseweb="select"] > div, textarea {
        border: 2px solid #4A4A4A !important; border-radius: 8px !important;
    }

    /* Botões e áreas de toque >= 48px */
    div.stButton > button,
    div.stDownloadButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        min-height: 48px; min-width: 48px; padding: 0.5rem 1.25rem;
        font-size: 1rem; font-weight: 700; border-radius: 8px;
        background-color: #0B3D91; color: #FFFFFF; border: 2px solid #0B3D91;
    }
    div.stButton > button p,
    div.stDownloadButton > button p,
    div[data-testid="stFormSubmitButton"] > button p { color: #FFFFFF !important; font-weight: 700; }
    div.stButton > button:hover,
    div.stDownloadButton > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {
        background-color: #082B66; border-color: #082B66; color: #FFFFFF;
    }

    /* Abas e radio com alvos de toque adequados */
    button[data-baseweb="tab"] { min-height: 48px; padding: 0 1.25rem; font-size: 1rem; font-weight: 600; color: #1A1A1A; }
    div[role="radiogroup"] label { min-height: 48px; display: flex; align-items: center; }

    /* Foco de teclado sempre visível */
    button:focus-visible, input:focus-visible, textarea:focus-visible,
    [role="tab"]:focus-visible, [role="radio"]:focus-visible, div[data-baseweb="select"]:focus-within {
        outline: 3px solid #1A1A1A !important; outline-offset: 3px !important;
    }

    /* Alertas: ícone + texto, borda forte, texto escuro */
    [data-testid="stAlert"] { border: 2px solid #1A1A1A; border-radius: 8px; }
    [data-testid="stAlert"] p { color: #1A1A1A !important; font-size: 1rem; }

    /* Métricas */
    [data-testid="stMetric"] { background: #F5F7FB; border: 2px solid #C9D3E6; border-radius: 8px; padding: 0.75rem 1rem; }
    [data-testid="stMetricLabel"] p { color: #1A1A1A !important; font-weight: 600; }
    [data-testid="stMetricValue"] { color: #0B2A5B; }
</style>
"""


# --------------------------------------------------------------------------- #
# Utilitários de UI
# --------------------------------------------------------------------------- #
@st.cache_resource
def _iniciar_banco() -> bool:
    database.init_db()
    return True


def alerta(tipo: str, mensagem: str) -> None:
    """Alerta visual que combina ícone + rótulo textual (nunca depende só de cor)."""
    icones = {"sucesso": "✅", "erro": "❌", "aviso": "⚠️", "info": "ℹ️"}
    rotulos = {"sucesso": "Sucesso", "erro": "Erro", "aviso": "Atenção", "info": "Informação"}
    funcoes = {"sucesso": st.success, "erro": st.error, "aviso": st.warning, "info": st.info}
    funcoes[tipo](f"**{rotulos[tipo]}:** {mensagem}", icon=icones[tipo])


def definir_flash(tipo: str, mensagem: str) -> None:
    """Guarda uma mensagem para ser exibida após o próximo rerun."""
    st.session_state["flash"] = (tipo, mensagem)


def mostrar_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        alerta(*flash)


def exibir_tabela(df) -> None:
    """Exibe o DataFrame de forma compatível com diferentes versões do Streamlit."""
    try:
        st.dataframe(df, hide_index=True, width="stretch")
    except Exception:  # versões antigas não aceitam width="stretch"
        try:
            st.dataframe(df, hide_index=True, use_container_width=True)
        except Exception:
            st.dataframe(df, hide_index=True)


# --------------------------------------------------------------------------- #
# Sessão (RF02)
# --------------------------------------------------------------------------- #
def usuario_logado() -> dict | None:
    return st.session_state.get("usuario")


def fazer_login(usuario: dict) -> None:
    st.session_state["usuario"] = usuario
    st.session_state.pop("tentativas_login", None)
    st.session_state.pop("bloqueado_ate", None)
    definir_flash("sucesso", f"Login realizado. Bem-vindo(a), {usuario['nome']}!")
    st.rerun()


def fazer_logout() -> None:
    st.session_state.clear()
    definir_flash("info", "Sessão encerrada com segurança. Até a próxima!")
    st.rerun()


def segundos_de_bloqueio() -> int:
    restante = st.session_state.get("bloqueado_ate", 0) - time.time()
    return int(restante) + 1 if restante > 0 else 0


# --------------------------------------------------------------------------- #
# Tela 1 - Login e Cadastro (RF01, RF02)
# --------------------------------------------------------------------------- #
def formulario_login() -> None:
    bloqueio = segundos_de_bloqueio()
    if bloqueio:
        alerta(
            "aviso",
            f"Muitas tentativas incorretas. Aguarde {bloqueio} segundos e tente novamente.",
        )

    with st.form("form_login"):
        email = st.text_input("E-mail", max_chars=auth.EMAIL_MAX, key="login_email")
        senha = st.text_input("Senha", type="password", max_chars=auth.SENHA_MAX, key="login_senha")
        enviar = st.form_submit_button("Entrar")

    if not enviar:
        return
    if bloqueio:
        return
    if not email.strip() or not senha:
        alerta("erro", "Preencha o e-mail e a senha para entrar.")
        return

    usuario = auth.autenticar(email, senha)
    if usuario:
        fazer_login(usuario)
        return

    tentativas = st.session_state.get("tentativas_login", 0) + 1
    if tentativas >= MAX_TENTATIVAS_LOGIN:
        st.session_state["bloqueado_ate"] = time.time() + BLOQUEIO_LOGIN_SEGUNDOS
        st.session_state["tentativas_login"] = 0
        alerta(
            "aviso",
            f"Muitas tentativas incorretas. Acesso bloqueado por {BLOQUEIO_LOGIN_SEGUNDOS} segundos.",
        )
    else:
        st.session_state["tentativas_login"] = tentativas
        alerta("erro", "E-mail ou senha incorretos. Verifique os dados e tente novamente.")


def formulario_cadastro() -> None:
    st.caption(
        f"Crie sua conta de voluntário. A senha deve ter no mínimo {auth.SENHA_MIN} caracteres."
    )
    with st.form("form_cadastro", clear_on_submit=True):
        nome = st.text_input("Nome completo", max_chars=auth.NOME_MAX, key="cad_nome")
        email = st.text_input("E-mail", max_chars=auth.EMAIL_MAX, key="cad_email")
        senha = st.text_input(
            "Senha (mínimo de 6 caracteres)", type="password", max_chars=auth.SENHA_MAX, key="cad_senha"
        )
        confirmacao = st.text_input(
            "Confirme a senha", type="password", max_chars=auth.SENHA_MAX, key="cad_confirmacao"
        )
        enviar = st.form_submit_button("Cadastrar voluntário")

    if not enviar:
        return
    try:
        auth.cadastrar_usuario(nome, email, senha, confirmacao)
    except auth.ErroValidacao as erro:
        alerta("erro", str(erro))
    except EmailDuplicadoError:
        alerta("erro", "Este e-mail já está cadastrado. Use a aba “Entrar” para acessar.")
    else:
        alerta("sucesso", "Cadastro realizado! Agora acesse a aba “Entrar” com seu e-mail e senha.")


def tela_login_cadastro() -> None:
    st.title("🤝 Associação Acolher e Transformar")
    st.caption(
        "Gestão de atendimentos e distribuição de cestas básicas — Jardim das Flores, São Paulo/SP"
    )
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        mostrar_flash()
        aba_entrar, aba_cadastrar = st.tabs(["🔑 Entrar", "📝 Cadastrar voluntário"])
        with aba_entrar:
            formulario_login()
        with aba_cadastrar:
            formulario_cadastro()


# --------------------------------------------------------------------------- #
# Tela 2 - Painel de gestão e busca (RF03)
# --------------------------------------------------------------------------- #
def filtros_atuais() -> tuple[str, str | None]:
    busca = st.session_state.get("filtro_busca", "") or ""
    status = st.session_state.get("filtro_status", OPCAO_TODOS)
    return busca, (None if status == OPCAO_TODOS else status)


def secao_metricas(id_usuario: int) -> None:
    contagem = database.contar_por_status(id_usuario)
    colunas = st.columns(4)
    colunas[0].metric("Total de registros", sum(contagem.values()))
    for coluna, status in zip(colunas[1:], STATUS_VALIDOS):
        coluna.metric(status, contagem[status])


def secao_novo_registro(id_usuario: int) -> None:
    st.subheader("➕ Novo atendimento / cesta básica")
    with st.form("form_novo_registro", clear_on_submit=True):
        titulo = st.text_input(
            "Nome da família ou item (obrigatório)", max_chars=120, key="novo_titulo"
        )
        descricao = st.text_area(
            "Descrição e observações", max_chars=500, key="novo_descricao", height=100
        )
        status = st.selectbox("Status inicial", STATUS_VALIDOS, index=0, key="novo_status")
        enviar = st.form_submit_button("Cadastrar atendimento")

    if not enviar:
        return
    try:
        database.criar_registro(titulo, descricao, id_usuario, status)
    except database.DadosInvalidosError as erro:
        alerta("erro", str(erro))
    else:
        definir_flash("sucesso", f"Atendimento “{titulo.strip()}” cadastrado com status “{status}”.")
        st.rerun()


def secao_filtros() -> None:
    st.subheader("🔎 Buscar e filtrar")
    col_busca, col_status = st.columns([2, 1])
    with col_busca:
        st.text_input("Buscar por nome ou descrição", key="filtro_busca", max_chars=120)
    with col_status:
        st.selectbox("Filtrar por status", [OPCAO_TODOS, *STATUS_VALIDOS], key="filtro_status")


def secao_lista_e_status(id_usuario: int, registros: list[dict], total_geral: int) -> None:
    st.subheader("📋 Atendimentos")
    if total_geral == 0:
        alerta("info", "Você ainda não tem registros. Cadastre o primeiro acima ou carregue dados de demonstração.")
        if st.button("Carregar dados de demonstração", key="btn_seed"):
            inseridos = database.popular_dados_demo(id_usuario)
            definir_flash("sucesso", f"{inseridos} registros de demonstração foram carregados.")
            st.rerun()
        return
    if not registros:
        alerta("aviso", "Nenhum registro encontrado com os filtros atuais. Ajuste a busca ou o status.")
        return

    st.caption(f"{len(registros)} registro(s) encontrado(s).")
    exibir_tabela(database.registros_para_dataframe(registros))

    st.subheader("🔄 Atualizar status")
    rotulos = {
        r["id_registro"]: f"#{r['id_registro']} — {r['titulo']} (atual: {r['status']})" for r in registros
    }
    with st.form("form_atualizar_status"):
        id_registro = st.selectbox(
            "Selecione o atendimento",
            list(rotulos.keys()),
            format_func=lambda i: rotulos[i],
            key="status_registro",
        )
        novo_status = st.selectbox("Novo status", STATUS_VALIDOS, key="status_novo")
        enviar = st.form_submit_button("Atualizar status")

    if enviar:
        if database.atualizar_status(id_registro, novo_status, id_usuario):
            definir_flash("sucesso", f"Status do atendimento #{id_registro} atualizado para “{novo_status}”.")
            st.rerun()
        else:
            alerta("erro", "Não foi possível atualizar: registro não encontrado.")


# --------------------------------------------------------------------------- #
# Tela 3 - Feedback visual e exportação CSV (RF04)
# --------------------------------------------------------------------------- #
def _registrar_download(quantidade: int, nome_arquivo: str) -> None:
    st.session_state["csv_exportado"] = (quantidade, nome_arquivo, datetime.now().strftime("%H:%M:%S"))


def tela_exportacao(todos: list[dict], filtrados: list[dict]) -> None:
    st.subheader("📥 Exportar registros para CSV")
    escopo = st.radio("O que deseja exportar?", [ESCOPO_FILTRADOS, ESCOPO_TODOS], key="escopo_exportacao")
    dados = filtrados if escopo == ESCOPO_FILTRADOS else todos

    exportado = st.session_state.pop("csv_exportado", None)
    if exportado:
        quantidade, nome_arquivo, hora = exportado
        alerta(
            "sucesso",
            f"Exportação concluída às {hora}: {quantidade} registro(s) salvos em “{nome_arquivo}”. "
            "Verifique a pasta de downloads do seu dispositivo.",
        )

    if not dados:
        alerta("aviso", "Não há registros para exportar com a seleção atual.")
        return

    df = database.registros_para_dataframe(dados)
    nome_arquivo = f"atendimentos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    alerta("info", f"Arquivo pronto: {len(df)} registro(s). Formato CSV (UTF-8 com BOM, separador “;”).")
    st.caption("Pré-visualização dos dados que serão exportados:")
    exibir_tabela(df)
    st.download_button(
        "⬇️ Baixar arquivo CSV",
        data=database.dataframe_para_csv_bytes(df),
        file_name=nome_arquivo,
        mime="text/csv",
        key="btn_baixar_csv",
        on_click=_registrar_download,
        args=(len(df), nome_arquivo),
    )


# --------------------------------------------------------------------------- #
# Área autenticada
# --------------------------------------------------------------------------- #
def tela_painel() -> None:
    usuario = usuario_logado()
    id_usuario = usuario["id_usuario"]

    with st.sidebar:
        st.subheader(f"👤 {usuario['nome']}")
        st.caption(usuario["email"])
        if st.button("Sair (logout)", key="btn_logout"):
            fazer_logout()

    st.title("🤝 Painel de Gestão — Acolher e Transformar")
    mostrar_flash()

    busca, status = filtros_atuais()
    todos = database.listar_registros(id_usuario)
    filtrados = database.listar_registros(id_usuario, busca=busca, status=status)

    aba_painel, aba_exportar = st.tabs(["📋 Painel de gestão", "📥 Exportar CSV"])
    with aba_painel:
        secao_metricas(id_usuario)
        secao_novo_registro(id_usuario)
        secao_filtros()
        secao_lista_e_status(id_usuario, filtrados, total_geral=len(todos))
    with aba_exportar:
        tela_exportacao(todos, filtrados)


def main() -> None:
    _iniciar_banco()
    st.markdown(CSS_ACESSIVEL, unsafe_allow_html=True)
    if usuario_logado():
        tela_painel()
    else:
        tela_login_cadastro()


main()
