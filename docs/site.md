# Site de consulta e publicação

A página informa quais jogos estão configurados/instalados e qual processo está
ativo. O servidor HTTP aceita apenas leitura de três rotas: `/`, `/status.js` e
`/api/status`. Não serve diretórios do disco, senhas, comandos RCON ou logs.
Por ser só-leitura e não expor dados privados, publicá-lo é seguro.

## Pelo menu (recomendado)

Tudo o que este documento descreve pode ser feito pelo menu principal, em
**"Site e serviços"** (`./start_server.sh` → opção 9):

- **Gerar/instalar serviços systemd** — cria as unidades do gerenciador e do site,
  perguntando o bind (`127.0.0.1` ou `0.0.0.0`) e a porta.
- **Habilitar e iniciar (com linger)** — roda `sudo loginctl enable-linger` e
  `systemctl --user enable --now`.
- **Parar / Desabilitar / Status / Logs** dos serviços.
- **Testar o site agora** — sobe o site em primeiro plano (Ctrl+C encerra).
- **Publicar o site** — três caminhos:
  - **Atrás de proxy reverso externo** (recomendado): expõe o site em `0.0.0.0` na
    porta escolhida e mostra a config pronta para colar no proxy (Caddy/nginx em
    outra máquina, ex.: um Raspberry Pi). O proxy termina o HTTPS e encaminha até
    aqui; o certificado é responsabilidade do proxy. No modem, os 80/443 vão para o
    host do proxy, não para este servidor.
  - **HTTPS neste servidor**: instala Nginx + Certbot localmente, cria o proxy para
    `127.0.0.1:8080`, emite o certificado e mostra o registro DNS e o port
    forwarding (80 e 443) para este servidor. Use quando NÃO há proxy externo.
  - **Somente LAN (HTTP)**: publica o site em `0.0.0.0` na porta escolhida e mostra
    o endereço `http://<ip-da-lan>:<porta>` para acesso interno.

As seções abaixo documentam os mesmos passos manualmente, caso você prefira.

## Teste local

```bash
python3 scripts/status_site.py --bind 127.0.0.1 --port 8080
```

Para consultar do seu computador sem publicar a porta, use um túnel SSH:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@servidor
```

Acesse `http://127.0.0.1:8080` no computador. Para manter o site ativo use a unidade
`games-status.service` descrita em [operação](operacao.md).

O JSON tem horário da consulta e não contém caminhos privados. Em erro de consulta,
a página limpa a listagem anterior para não apresentar um estado antigo como atual.
Atualmente `running` significa **grupo de processos vivo**, não autenticação
concluída, mapa carregado ou conectividade externa confirmada.

## Publicação

Há duas formas de deixar a página acessível publicamente. A recomendada é atrás de
um proxy reverso com HTTPS.

### Opção A (recomendada): proxy reverso Nginx com HTTPS

Mantenha o aplicativo em `127.0.0.1:8080` (o padrão) e ponha o Nginx na frente,
terminando o TLS. Crie o registro DNS do seu domínio para o IP público e encaminhe
TCP 80/443 no roteador. **Não** encaminhe a porta 8080 nem portas de RCON.

Instale o Nginx e o certbot:

```bash
sudo apt update
sudo apt install nginx certbot python3-certbot-nginx
```

Configuração HTTP inicial (substitua `status.seu-dominio.example` pelo seu domínio):

```nginx
server {
    listen 80;
    server_name status.seu-dominio.example;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
    }
}
```

Valide e recarregue, depois emita o certificado — o certbot ajusta o bloco para
HTTPS e configura a renovação automática:

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d status.seu-dominio.example
```

O certbot obtém o certificado do [Let's Encrypt](https://letsencrypt.org/) e
instala um `server` em `listen 443 ssl` com redirecionamento de 80 para 443.
A renovação roda por timer do systemd; teste com `sudo certbot renew --dry-run`.
O encaminhamento é feito com a diretiva
[`proxy_pass` do Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass).
Não configure `root`/`alias` do Nginx apontando para `GAMES_ROOT` ou para backups.

### Opção B: expor a porta diretamente (HTTP, sem proxy)

Se você quer apenas HTTP simples e não tem um domínio/proxy, faça o site escutar em
todas as interfaces e libere a porta no firewall e no roteador:

```bash
python3 scripts/status_site.py --bind 0.0.0.0 --port 8080
sudo ufw allow 8080/tcp
```

Para a unidade systemd escutar em `0.0.0.0`, gere-a com `STATUS_BIND=0.0.0.0`
(veja [operação](operacao.md)). Encaminhe TCP 8080 no roteador. Essa opção não tem
criptografia; prefira a Opção A quando puder usar um domínio.

## Observações

Teste de fora da rede doméstica (por exemplo, conexão móvel): roteadores podem
não suportar acesso ao próprio IP público pela rede interna. O site continuar
acessível não garante que as portas UDP de um jogo estejam encaminhadas.

Esta versão não executa consultas de protocolo de todos os jogos, não exibe
jogadores online e não permite escolher o jogo pela web. A escolha permanece no
terminal do administrador.
