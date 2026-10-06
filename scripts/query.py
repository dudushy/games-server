"""Consulta de rede para contagem de jogadores (online/max), como as listas de servidores.

Em vez de inferir jogadores pelo log (frágil: qualquer um pode digitar "joined the
game" no chat), consultamos o próprio servidor pelos protocolos padrão que os
navegadores de servidores usam:

- Minecraft (Java): Server List Ping (SLP), via TCP na porta do jogo.
- Jogos Steam/Source (Valheim, Conan, Rust, Smalland): A2S_INFO, via UDP na query port.

Ambas as funções retornam uma tupla ``(online, max)`` de inteiros ou ``None`` em
qualquer falha (timeout, porta fechada, resposta malformada). Nunca propagam exceção
e nunca extraem nomes, IDs ou endereços de jogadores — apenas as contagens agregadas.
Em particular, não usamos A2S_PLAYER (que traria nomes); só o A2S_INFO.
"""
import json
import socket
import struct


def _read_varint(data, offset):
    """Lê um VarInt (protocolo Minecraft) a partir de ``offset``.

    Retorna ``(valor, novo_offset)``. Levanta ValueError se o buffer acabar antes
    de terminar o VarInt ou se ele exceder 5 bytes (limite do protocolo).
    """
    value = 0
    for i in range(5):
        if offset >= len(data):
            raise ValueError("VarInt incompleto")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return value, offset
    raise ValueError("VarInt longo demais")


def _encode_varint(value):
    """Codifica um inteiro não negativo como VarInt (protocolo Minecraft)."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _recv_exact(sock, count):
    """Lê exatamente ``count`` bytes de um socket TCP ou levanta ConnectionError."""
    buffer = bytearray()
    while len(buffer) < count:
        chunk = sock.recv(count - len(buffer))
        if not chunk:
            raise ConnectionError("conexão encerrada antes do esperado")
        buffer += chunk
    return bytes(buffer)


def _recv_packet(sock):
    """Lê um pacote SLP (comprimento VarInt + corpo) e devolve o corpo em bytes.

    Lê o VarInt de comprimento byte a byte (não sabemos quantos bytes ele ocupa
    antes de lê-lo) e então o corpo completo. Limita o tamanho para não alocar
    memória sem limite diante de um servidor malicioso ou de uma resposta corrompida.
    """
    length_bytes = bytearray()
    while True:
        byte = _recv_exact(sock, 1)[0]
        length_bytes.append(byte)
        if not byte & 0x80:
            break
        if len(length_bytes) >= 5:
            raise ValueError("VarInt de comprimento longo demais")
    length, _ = _read_varint(bytes(length_bytes), 0)
    if not 0 <= length <= 4 * 1024 * 1024:
        raise ValueError("pacote SLP com tamanho inválido")
    return _recv_exact(sock, length)


def minecraft_slp(host, port, timeout=3.0):
    """Consulta um servidor Minecraft Java via Server List Ping (SLP).

    Retorna ``(online, max)`` como inteiros, ou ``None`` em qualquer falha. Lê apenas
    ``players.online`` e ``players.max`` do JSON de status; ignora o ``sample`` (que
    conteria nomes de jogadores) e todo o restante.
    """
    try:
        # Handshake (state=1) seguido de Status Request, enviados juntos.
        host_bytes = host.encode("utf-8")
        handshake_payload = (
            b"\x00"                              # packet id 0x00 (handshake)
            + _encode_varint(-1 & 0xFFFFFFFF)    # protocol version (-1: só ping)
            + _encode_varint(len(host_bytes)) + host_bytes
            + struct.pack(">H", port)            # porta (unsigned short, big-endian)
            + _encode_varint(1)                  # next state = 1 (status)
        )
        handshake = _encode_varint(len(handshake_payload)) + handshake_payload
        status_request = _encode_varint(1) + b"\x00"  # len=1, packet id 0x00

        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(handshake + status_request)
            body = _recv_packet(sock)
        # Corpo: packet id (VarInt) + comprimento da string (VarInt) + JSON UTF-8.
        packet_id, offset = _read_varint(body, 0)
        if packet_id != 0x00:
            return None
        json_len, offset = _read_varint(body, offset)
        raw = body[offset:offset + json_len]
        if len(raw) < json_len:
            return None
        players = json.loads(raw.decode("utf-8", errors="replace")).get("players", {})
        online, maximum = players.get("online"), players.get("max")
        if isinstance(online, int) and isinstance(maximum, int):
            return max(online, 0), max(maximum, 0)
        return None
    except (OSError, ValueError, json.JSONDecodeError, struct.error):
        return None


def _a2s_request(sock, address, challenge=b""):
    """Envia um A2S_INFO (0x54) com o payload padrão e um challenge opcional."""
    packet = b"\xFF\xFF\xFF\xFF\x54Source Engine Query\x00" + challenge
    sock.sendto(packet, address)
    data, _ = sock.recvfrom(4096)
    return data


def steam_a2s_info(host, port, timeout=3.0):
    """Consulta um servidor Steam/Source via A2S_INFO (UDP).

    Retorna ``(online, max)`` como inteiros, ou ``None`` em qualquer falha. Trata o
    handshake de challenge (0x41) exigido por servidores modernos: ao receber um
    desafio, reenvia o A2S_INFO anexando os 4 bytes do challenge. Lê apenas os campos
    ``Players`` e ``Max players`` do cabeçalho; não consulta A2S_PLAYER (nomes).
    """
    try:
        address = (host, port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            data = _a2s_request(sock, address)
            # Resposta a connectionless começa com 0xFFFFFFFF; o 5º byte é o tipo.
            if len(data) < 5 or data[:4] != b"\xFF\xFF\xFF\xFF":
                return None
            header = data[4]
            if header == 0x41:  # S2C_CHALLENGE: reenviar com os 4 bytes do desafio.
                challenge = data[5:9]
                if len(challenge) != 4:
                    return None
                data = _a2s_request(sock, address, challenge)
                if len(data) < 5 or data[:4] != b"\xFF\xFF\xFF\xFF":
                    return None
                header = data[4]
            if header != 0x49:  # 0x49 = 'I', A2S_INFO response.
                return None
        return _parse_a2s_info(data)
    except (OSError, ValueError, struct.error):
        return None


def _parse_a2s_info(data):
    """Extrai ``(online, max)`` de uma resposta A2S_INFO (header 0x49).

    Layout após 0xFFFFFFFF 0x49: Protocol (byte), Name (string C), Map (string C),
    Folder (string C), Game (string C), ID (short), Players (byte), Max players (byte)...
    Lê apenas até Max players. Retorna None se o buffer acabar antes.
    """
    offset = 5          # pula 0xFFFFFFFF + header 0x49
    offset += 1         # Protocol (byte)

    def skip_cstring(pos):
        end = data.find(b"\x00", pos)
        if end == -1:
            raise ValueError("string C sem terminador")
        return end + 1

    for _ in range(4):  # Name, Map, Folder, Game
        offset = skip_cstring(offset)
    offset += 2         # ID (short)
    if offset + 1 >= len(data):
        return None
    players = data[offset]
    maximum = data[offset + 1]
    return players, maximum
