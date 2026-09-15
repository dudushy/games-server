#!/usr/bin/env python3
"""Gera scripts/favicon.ico: um joystick (controle) ao lado de um servidor (rack).

Reproduz o ícone do site a partir de código, sem baixar imagens. O desenho segue a
paleta do tema escuro da página (fundo #0f1420, acento azul #5b9dff). O resultado é
um .ico multi-resolução (16/32/48/64 px) versionado no repositório.

Pillow NÃO é dependência de runtime do gerenciador: o site apenas serve o .ico já
gerado. Rode este script à mão quando quiser recriar o ícone:

    python3 -m venv /tmp/favicon-venv
    /tmp/favicon-venv/bin/pip install pillow
    /tmp/favicon-venv/bin/python scripts/make_favicon.py

Saída padrão: scripts/favicon.ico (ao lado deste arquivo).
"""
from pathlib import Path

from PIL import Image, ImageDraw

# Paleta alinhada ao tema do site (status_site.py).
BG = (15, 20, 32, 255)        # #0f1420 fundo
ACCENT = (91, 157, 255, 255)  # #5b9dff azul (joystick)
OK = (61, 220, 132, 255)      # #3ddc84 verde (LEDs do servidor "ligado")
LIGHT = (230, 236, 247, 255)  # #e6ecf7 detalhes claros
METAL = (44, 58, 85, 255)     # #2c3a55 corpo do servidor
DARK = (26, 34, 51, 255)      # #1a2233 slots do rack


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render(size):
    """Desenha o ícone em alta resolução (supersampling) e reduz para `size`."""
    scale = 8
    side = size * scale
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    u = side / 64.0  # unidade base: coordenadas pensadas em uma grade 64x64

    def px(*values):
        return [v * u for v in values]

    # Fundo arredondado do ícone.
    rounded(draw, px(1, 1, 63, 63), 12 * u, BG)

    # --- Joystick / controle (esquerda) ---
    # Corpo do gamepad: retângulo arredondado inclinado suavemente.
    body = px(6, 26, 34, 46)
    rounded(draw, body, 9 * u, ACCENT)
    # "Cabos"/pegadas laterais: dois círculos que alargam as extremidades.
    draw.ellipse(px(4, 30, 18, 48), fill=ACCENT)
    draw.ellipse(px(22, 30, 36, 48), fill=ACCENT)
    # D-pad (cruz) à esquerda.
    draw.rectangle(px(11, 35, 17, 39), fill=BG)
    draw.rectangle(px(12.5, 33.5, 15.5, 40.5), fill=BG)
    # Dois botões à direita.
    draw.ellipse(px(25, 33, 29, 37), fill=BG)
    draw.ellipse(px(28, 37, 32, 41), fill=BG)

    # --- Servidor / rack (direita) ---
    tower = px(40, 16, 58, 50)
    rounded(draw, tower, 4 * u, METAL)
    # Três slots/bandejas com LED de status.
    for i in range(3):
        top = 20 + i * 9
        rounded(draw, px(43, top, 55, top + 6), 1.5 * u, DARK)
        draw.ellipse(px(45, top + 2, 47.5, top + 4.5), fill=OK)
        draw.rectangle(px(49, top + 2.5, 54, top + 3.5), fill=LIGHT)

    return image.resize((size, size), Image.LANCZOS)


def main():
    out = Path(__file__).with_name("favicon.ico")
    sizes = (16, 32, 48, 64)
    # Renderiza no maior tamanho e deixa o Pillow embutir cada resolução do .ico a
    # partir dele (passar `sizes` a uma única imagem gera todos os frames; usar
    # `append_images` para ICO só gravava o primeiro frame).
    master = render(max(sizes))
    master.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Gerado: {out} ({', '.join(f'{s}x{s}' for s in sizes)})")


if __name__ == "__main__":
    main()
