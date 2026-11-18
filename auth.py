"""
Camada de Regras de Negócio e Autenticação - Associação Acolher e Transformar.

Segurança (RNF01/RNF02 - OWASP):
    * Senhas armazenadas com PBKDF2-HMAC-SHA256, salt exclusivo de 16 bytes
      gerado por `os.urandom` e 600.000 iterações (recomendação OWASP Password
      Storage Cheat Sheet). Nunca em texto plano, MD5 ou SHA-1.
    * Comparação de hashes em tempo constante (`hmac.compare_digest`).
    * Mensagem de login genérica e custo de hash equivalente quando o e-mail não
      existe, reduzindo a enumeração de usuários por tempo de resposta.

Formato armazenado em `usuarios.senha_hash`:
    pbkdf2_sha256$<iteracoes>$<salt_hex>$<hash_hex>
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from functools import lru_cache
from typing import Optional

import database

ALGORITMO = "pbkdf2_sha256"
ITERACOES = 600_000
TAMANHO_SALT = 16  # bytes
SENHA_MIN = 6
SENHA_MAX = 128  # evita abuso de CPU com senhas gigantes
NOME_MAX = 100
EMAIL_MAX = 254

_REGEX_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class ErroValidacao(ValueError):
    """Dados de cadastro inválidos (mensagem pronta para exibir ao usuário)."""


# --------------------------------------------------------------------------- #
# Hash de senha
# --------------------------------------------------------------------------- #
def gerar_hash_senha(senha: str, iteracoes: Optional[int] = None) -> str:
    """Gera o hash PBKDF2-HMAC-SHA256 com salt exclusivo e devolve a string armazenável."""
    iteracoes = iteracoes or ITERACOES
    salt = os.urandom(TAMANHO_SALT)
    derivada = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iteracoes)
    return f"{ALGORITMO}${iteracoes}${salt.hex()}${derivada.hex()}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    """Confere a senha contra o hash armazenado. Hash malformado => False (nunca lança)."""
    try:
        algoritmo, iteracoes_txt, salt_hex, hash_hex = senha_hash.split("$")
        if algoritmo != ALGORITMO:
            return False
        iteracoes = int(iteracoes_txt)
        if not 1 <= iteracoes <= 5_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        esperado = bytes.fromhex(hash_hex)
        if not salt or not esperado:
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), salt, iteracoes, dklen=len(esperado)
        )
    except (ValueError, AttributeError, TypeError):
        return False
    return hmac.compare_digest(calculado, esperado)


@lru_cache(maxsize=1)
def _hash_falso() -> str:
    """Hash descartável usado para igualar o tempo de resposta quando o e-mail não existe."""
    return gerar_hash_senha("senha-descartavel-nao-utilizada")


# --------------------------------------------------------------------------- #
# Validação (RF01)
# --------------------------------------------------------------------------- #
def validar_cadastro(
    nome: str, email: str, senha: str, confirmacao: Optional[str] = None
) -> tuple[str, str]:
    """Valida os campos do cadastro e devolve (nome, email) normalizados."""
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    senha = senha or ""

    if not nome:
        raise ErroValidacao("Informe o nome completo.")
    if len(nome) > NOME_MAX:
        raise ErroValidacao(f"O nome deve ter no máximo {NOME_MAX} caracteres.")
    if not email or len(email) > EMAIL_MAX or not _REGEX_EMAIL.match(email):
        raise ErroValidacao("Informe um e-mail válido, por exemplo: nome@exemplo.com.")
    if len(senha) < SENHA_MIN:
        raise ErroValidacao(f"A senha deve ter no mínimo {SENHA_MIN} caracteres.")
    if len(senha) > SENHA_MAX:
        raise ErroValidacao(f"A senha deve ter no máximo {SENHA_MAX} caracteres.")
    if confirmacao is not None and senha != confirmacao:
        raise ErroValidacao("A confirmação de senha não confere com a senha digitada.")
    return nome, email


def cadastrar_usuario(
    nome: str,
    email: str,
    senha: str,
    confirmacao: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """
    RF01 - Cadastra voluntário/operador.

    Lança `ErroValidacao` (dados inválidos) ou `database.EmailDuplicadoError`
    (e-mail já cadastrado). Devolve o id do novo usuário.
    """
    nome, email = validar_cadastro(nome, email, senha, confirmacao)
    senha_hash = gerar_hash_senha(senha)
    return database.criar_usuario(nome, email, senha_hash, db_path)


# --------------------------------------------------------------------------- #
# Autenticação (RF02)
# --------------------------------------------------------------------------- #
def autenticar(email: str, senha: str, db_path: Optional[str] = None) -> Optional[dict]:
    """
    Valida as credenciais. Devolve {'id_usuario', 'nome', 'email'} em caso de
    sucesso (sem o hash) ou None se e-mail/senha estiverem incorretos.
    """
    if not isinstance(email, str) or not isinstance(senha, str):
        return None
    if not email.strip() or not senha or len(senha) > SENHA_MAX:
        return None

    usuario = database.buscar_usuario_por_email(email, db_path)
    if usuario is None:
        verificar_senha(senha, _hash_falso())  # custo equivalente; resultado ignorado
        return None
    if not verificar_senha(senha, usuario["senha_hash"]):
        return None
    return {
        "id_usuario": usuario["id_usuario"],
        "nome": usuario["nome"],
        "email": usuario["email"],
    }
