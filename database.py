"""
Camada de Persistência de Dados - Associação Acolher e Transformar.

Responsabilidades:
    * criação do esquema SQLite (tabelas `usuarios` e `registros_mvp`);
    * operações CRUD sobre usuários e registros de atendimento;
    * serialização dos registros para exportação em CSV (utf-8-sig).

Segurança (RNF01/RNF02):
    * TODAS as consultas usam parâmetros (`?`); nenhum valor vindo do usuário
      é concatenado ao SQL. Os únicos trechos dinâmicos são fragmentos fixos
      definidos neste arquivo (por exemplo, a cláusula de filtro).
    * `PRAGMA foreign_keys = ON` garante a integridade referencial.
    * Restrição `CHECK` no banco garante que `status` só assuma valores válidos.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
DB_PATH = os.environ.get(
    "ACOLHER_DB_PATH",
    str(Path(__file__).resolve().parent / "acolher_transformar.db"),
)

STATUS_PENDENTE = "Pendente"
STATUS_EM_ATENDIMENTO = "Em atendimento"
STATUS_ATENDIDA = "Atendida"
STATUS_VALIDOS = (STATUS_PENDENTE, STATUS_EM_ATENDIMENTO, STATUS_ATENDIDA)

COLUNAS_EXPORTACAO = ["ID", "Título", "Descrição", "Status", "Data de criação"]

_PREFIXOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")

DADOS_DEMO = (
    ("Família Almeida Santos", "4 pessoas, 2 crianças. Retirada mensal de cesta básica.", STATUS_PENDENTE),
    ("Família Ribeiro", "5 pessoas. Prioridade: 3 crianças em idade escolar.", STATUS_PENDENTE),
    ("Família Nogueira Lima", "3 pessoas. Cesta separada, aguardando retirada.", STATUS_EM_ATENDIMENTO),
    ("Família Costa Ferreira", "6 pessoas. Atendimento realizado na última distribuição.", STATUS_ATENDIDA),
    ("Item: Arroz 5 kg (doação de campanha)", "40 pacotes recebidos; separar para as próximas cestas.", STATUS_EM_ATENDIMENTO),
    ("Item: Feijão 1 kg (doação de campanha)", "60 pacotes recebidos e conferidos pelo voluntário.", STATUS_ATENDIDA),
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario    INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    senha_hash    TEXT NOT NULL,
    data_cadastro TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registros_mvp (
    id_registro  INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo       TEXT NOT NULL,
    descricao    TEXT,
    status       TEXT NOT NULL
                 CHECK (status IN ('Pendente', 'Em atendimento', 'Atendida')),
    data_criacao TEXT NOT NULL,
    id_usuario   INTEGER NOT NULL,
    FOREIGN KEY (id_usuario) REFERENCES usuarios (id_usuario)
);

CREATE INDEX IF NOT EXISTS idx_registros_usuario_status
    ON registros_mvp (id_usuario, status);
"""


# --------------------------------------------------------------------------- #
# Exceções de domínio
# --------------------------------------------------------------------------- #
class EmailDuplicadoError(Exception):
    """Já existe um usuário cadastrado com o e-mail informado."""


class StatusInvalidoError(ValueError):
    """O status informado não pertence a STATUS_VALIDOS."""


class DadosInvalidosError(ValueError):
    """Dados obrigatórios ausentes ou inválidos."""


# --------------------------------------------------------------------------- #
# Infraestrutura
# --------------------------------------------------------------------------- #
def _normalizar(texto: Optional[str]) -> str:
    """Remove acentos e aplica casefold, para buscas tolerantes (Família == familia)."""
    if texto is None:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acentos.casefold()


def _escapar_like(termo: str) -> str:
    """Escapa curingas do LIKE para que '%' e '_' digitados sejam tratados como texto."""
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conexao(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Abre uma conexão, faz commit ao sair com sucesso, rollback em erro e sempre fecha."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("normalizar", 1, _normalizar, deterministic=True)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Cria as tabelas e índices caso ainda não existam (idempotente)."""
    with conexao(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def _validar_status(status: str) -> None:
    if status not in STATUS_VALIDOS:
        raise StatusInvalidoError(
            f"Status inválido: {status!r}. Valores permitidos: {', '.join(STATUS_VALIDOS)}."
        )


# --------------------------------------------------------------------------- #
# Usuários
# --------------------------------------------------------------------------- #
def criar_usuario(
    nome: str, email: str, senha_hash: str, db_path: Optional[str] = None
) -> int:
    """Insere um usuário e devolve o id. Lança EmailDuplicadoError se o e-mail já existir."""
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    if not nome or not email or not senha_hash:
        raise DadosInvalidosError("Nome, e-mail e senha_hash são obrigatórios.")
    try:
        with conexao(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO usuarios (nome, email, senha_hash, data_cadastro) "
                "VALUES (?, ?, ?, ?)",
                (nome, email, senha_hash, _agora()),
            )
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper():
            raise EmailDuplicadoError("Este e-mail já está cadastrado.") from exc
        raise


def buscar_usuario_por_email(email: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Retorna o usuário (incluindo senha_hash) ou None."""
    email = (email or "").strip().lower()
    with conexao(db_path) as conn:
        linha = conn.execute(
            "SELECT id_usuario, nome, email, senha_hash, data_cadastro "
            "FROM usuarios WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(linha) if linha else None


def contar_usuarios(db_path: Optional[str] = None) -> int:
    with conexao(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0])


# --------------------------------------------------------------------------- #
# Registros de atendimento
# --------------------------------------------------------------------------- #
def criar_registro(
    titulo: str,
    descricao: Optional[str],
    id_usuario: int,
    status: str = STATUS_PENDENTE,
    db_path: Optional[str] = None,
) -> int:
    """Cria um registro (família/item) vinculado ao operador e devolve o id."""
    titulo = (titulo or "").strip()
    if not titulo:
        raise DadosInvalidosError("O título (nome da família ou item) é obrigatório.")
    _validar_status(status)
    descricao = (descricao or "").strip()
    with conexao(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO registros_mvp (titulo, descricao, status, data_criacao, id_usuario) "
            "VALUES (?, ?, ?, ?, ?)",
            (titulo, descricao, status, _agora(), id_usuario),
        )
        return int(cursor.lastrowid)


def listar_registros(
    id_usuario: int,
    busca: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    Lista os registros do operador, do mais recente para o mais antigo.

    `busca` filtra por título OU descrição (sem diferenciar maiúsculas/acentos).
    `status` filtra por um dos valores de STATUS_VALIDOS.
    """
    sql = (
        "SELECT id_registro, titulo, descricao, status, data_criacao, id_usuario "
        "FROM registros_mvp WHERE id_usuario = ?"
    )
    parametros: list = [id_usuario]

    if busca and busca.strip():
        termo = f"%{_escapar_like(_normalizar(busca.strip()))}%"
        sql += (
            " AND (normalizar(titulo) LIKE ? ESCAPE '\\'"
            " OR normalizar(COALESCE(descricao, '')) LIKE ? ESCAPE '\\')"
        )
        parametros.extend([termo, termo])

    if status:
        _validar_status(status)
        sql += " AND status = ?"
        parametros.append(status)

    sql += " ORDER BY id_registro DESC"

    with conexao(db_path) as conn:
        linhas = conn.execute(sql, parametros).fetchall()
    return [dict(linha) for linha in linhas]


def atualizar_status(
    id_registro: int, novo_status: str, id_usuario: int, db_path: Optional[str] = None
) -> bool:
    """Atualiza o status de um registro DO PRÓPRIO operador. Retorna True se alterou."""
    _validar_status(novo_status)
    with conexao(db_path) as conn:
        cursor = conn.execute(
            "UPDATE registros_mvp SET status = ? WHERE id_registro = ? AND id_usuario = ?",
            (novo_status, id_registro, id_usuario),
        )
        return cursor.rowcount > 0


def excluir_registro(id_registro: int, id_usuario: int, db_path: Optional[str] = None) -> bool:
    """Remove um registro DO PRÓPRIO operador. Retorna True se removeu."""
    with conexao(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM registros_mvp WHERE id_registro = ? AND id_usuario = ?",
            (id_registro, id_usuario),
        )
        return cursor.rowcount > 0


def contar_por_status(id_usuario: int, db_path: Optional[str] = None) -> dict[str, int]:
    """Quantidade de registros por status (todos os status aparecem, mesmo com zero)."""
    contagem = {status: 0 for status in STATUS_VALIDOS}
    with conexao(db_path) as conn:
        linhas = conn.execute(
            "SELECT status, COUNT(*) AS total FROM registros_mvp "
            "WHERE id_usuario = ? GROUP BY status",
            (id_usuario,),
        ).fetchall()
    for linha in linhas:
        contagem[linha["status"]] = int(linha["total"])
    return contagem


def popular_dados_demo(id_usuario: int, db_path: Optional[str] = None) -> int:
    """
    Seed opcional: insere registros fictícios de demonstração.
    Só executa se o operador ainda não tiver nenhum registro. Retorna quantos inseriu.
    """
    if sum(contar_por_status(id_usuario, db_path).values()) > 0:
        return 0
    for titulo, descricao, status in DADOS_DEMO:
        criar_registro(titulo, descricao, id_usuario, status, db_path)
    return len(DADOS_DEMO)


# --------------------------------------------------------------------------- #
# Exportação (RF04)
# --------------------------------------------------------------------------- #
def _neutralizar_formula(valor):
    """
    Mitiga CSV/Formula Injection (OWASP): textos iniciados por = + - @ são
    prefixados com apóstrofo para que planilhas não os executem como fórmula.
    """
    if isinstance(valor, str) and valor.startswith(_PREFIXOS_FORMULA):
        return "'" + valor
    return valor


def _formatar_data(valor: str) -> str:
    try:
        return datetime.strptime(valor, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(valor)


def registros_para_dataframe(registros: list[dict]) -> pd.DataFrame:
    """Converte a lista de registros em DataFrame com colunas legíveis em português."""
    if not registros:
        return pd.DataFrame(columns=COLUNAS_EXPORTACAO)
    linhas = [
        {
            "ID": r["id_registro"],
            "Título": r["titulo"],
            "Descrição": r["descricao"] or "",
            "Status": r["status"],
            "Data de criação": _formatar_data(r["data_criacao"]),
        }
        for r in registros
    ]
    return pd.DataFrame(linhas, columns=COLUNAS_EXPORTACAO)


def dataframe_para_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Gera o conteúdo do CSV em `utf-8-sig` (BOM, para o Excel reconhecer acentos).
    Separador ';' (padrão do Excel em pt-BR).
    """
    saida = df.copy()
    for coluna in ("Título", "Descrição"):
        if coluna in saida.columns:
            saida[coluna] = saida[coluna].map(_neutralizar_formula)
    texto = saida.to_csv(index=False, sep=";", lineterminator="\r\n")
    return texto.encode("utf-8-sig")
