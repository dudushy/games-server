"""RCON local; credenciais não são colocadas na linha de comando do cliente."""
import json
import socket
import struct
import time
from urllib.parse import quote


def exact(sock, count):
    result = b""
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise ConnectionError("RCON encerrou a conexão")
        result += chunk
    return result


def packet(sock):
    size = struct.unpack("<i", exact(sock, 4))[0]
    if not 10 <= size <= 4 * 1024 * 1024:
        raise ValueError("Pacote RCON inválido")
    body = exact(sock, size)
    ident, kind = struct.unpack("<ii", body[:8])
    return ident, kind, body[8:-2].decode("utf-8", errors="replace")


def send(sock, ident, kind, message):
    body = struct.pack("<ii", ident, kind) + message.encode() + b"\0\0"
    sock.sendall(struct.pack("<i", len(body)) + body)


def source_commands(port, password, commands):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        send(sock, 1, 3, password)
        for _ in range(8):
            ident, kind, _ = packet(sock)
            if ident == -1:
                raise ValueError("Autenticação RCON recusada")
            # A resposta de autenticação tem tipo 2 (SERVERDATA_AUTH_RESPONSE).
            # O spec original ecoa o id do pedido (1), mas implementações reais
            # variam — Conan Exiles Enhanced responde com ident=0. Como a falha é
            # sinalizada de forma inequívoca por ident=-1 (tratado acima), qualquer
            # pacote tipo 2 com ident != -1 confirma a autenticação.
            if kind == 2:
                break
        else:
            raise ValueError("Sem confirmação de autenticação RCON")
        # Shutdown pode encerrar a conexão antes da resposta. O manager aguarda o processo.
        for i, command in enumerate(commands, 2):
            send(sock, i, 2, command)


def web_commands(port, password, commands):
    try:
        import websocket
    except ImportError as error:
        raise ValueError("Rust exige o pacote python3-websocket") from error
    address = f"ws://127.0.0.1:{port}/{quote(password, safe='')}"
    try:
        with websocket.create_connection(address, timeout=10, http_no_proxy=["127.0.0.1"]) as sock:
            for ident, command in enumerate(commands, 1):
                sock.send(json.dumps({"Identifier": ident, "Message": command, "Name": "games-server"}))
                if command == "quit":
                    return
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    reply = json.loads(sock.recv())
                    if reply.get("Identifier") == ident:
                        message = reply.get("Message", "").lower()
                        if any(word in message for word in ("unknown command", "exception", "error")):
                            raise ValueError("Rust recusou o comando de salvamento")
                        break
                else:
                    raise ValueError("Rust não confirmou o comando de salvamento")
    except Exception as error:
        # Bibliotecas WebSocket podem incluir a URL (que contém a senha) na exceção.
        raise ValueError("Falha no WebRCON local; verifique configuração e disponibilidade") from None
