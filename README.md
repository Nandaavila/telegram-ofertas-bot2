# 🤖 Automação de Canal de Ofertas no Telegram

Sistema completo para automatizar a divulgação de ofertas de afiliados
(Mercado Livre, Amazon, Shopee, Magalu) em um canal do Telegram.

## 🗂️ Estrutura do projeto

```
telegram_afiliados/
├── main.py                    # ponto de entrada da automação (scheduler)
├── config.py                  # todas as configurações centralizadas
├── database/
│   ├── models.py               # tabelas: Produto, Publicacao, LogEvento
│   └── db.py                   # funções de acesso ao banco
├── collectors/                # um arquivo por fonte de ofertas
│   ├── base_collector.py
│   ├── mercado_livre.py        # API pública oficial do ML
│   ├── amazon.py                # PA-API oficial da Amazon
│   └── feed_afiliados.py       # genérico p/ Shopee/Magalu via rede de afiliados
├── processing/
│   ├── filters.py               # cálculo de desconto e regras "vale a pena?"
│   ├── expiracao.py              # detecção de ofertas expiradas
│   ├── sincronizar_conversoes.py # sincronização automática de conversões (Shopee)
│   └── importar_relatorio_ml.py  # importador manual do CSV de afiliados (Mercado Livre)
├── ai/
│   └── text_generator.py       # geração do texto com Claude (Anthropic API)
├── publisher/
│   └── telegram_publisher.py   # envio das mensagens ao canal
├── scheduler/
│   ├── pipeline.py             # orquestra: buscar -> filtrar -> gerar -> publicar
│   └── scheduler.py            # agenda as tarefas (APScheduler)
├── creative/
│   └── image_generator.py      # gera o card promocional (Pillow) com preço/desconto
├── assets/fonts/                # fontes embutidas no projeto (funcionam em qualquer Docker)
├── admin/
│   ├── app.py                   # painel Flask (aprovação, estatísticas, logs)
│   └── templates/dashboard.html
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## 🚀 Como rodar localmente (sem Docker)

```bash
# 1. Crie um ambiente virtual
python3 -m venv venv
source venv/bin/activate   # no Windows: venv\Scripts\activate

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure suas variáveis de ambiente
cp .env.example .env
# edite o .env com seu token do bot, chave da Anthropic, tags de afiliado, etc.

# 4. Rode a automação
python main.py

# 5. Em outro terminal, rode o painel administrativo
python admin/app.py
# acesse http://localhost:5000
```

## 🐳 Como rodar com Docker

```bash
cp .env.example .env   # preencha antes de subir
docker compose up -d --build
```

## 🔑 Como obter os acessos necessários

- **Bot do Telegram**: fale com [@BotFather](https://t.me/BotFather), crie
  um bot com `/newbot`, copie o token. Adicione o bot como administrador
  do seu canal.
- **ID do canal**: encaminhe uma mensagem do canal para
  [@userinfobot](https://t.me/userinfobot) ou use `@seucanal` se for público.
- **Mercado Livre**: cadastre-se em mercadolivre.com.br/afiliados.
- **Amazon**: cadastre-se em afiliados.amazon.com.br e depois solicite
  acesso à PA-API em webservices.amazon.com/paapi5.
- **Shopee/Magalu**: cadastre-se em uma rede de afiliados que os
  agregue (ex: Lomadee, Awin) para obter um feed de produtos autorizado.
- **Claude (Anthropic)**: crie uma chave em console.anthropic.com.

## ⚠️ Segurança e boas práticas aplicadas

- Tokens e chaves NUNCA ficam no código — só em `.env` (fora do Git).
- Requisições aos marketplaces usam **APIs oficiais**, não scraping,
  evitando bloqueio de IP e violação de Termos de Uso.
- Rate limiting e retry com backoff no envio ao Telegram, respeitando
  os limites da API (evita banimento do bot).
- Banco de dados abstraído via SQLAlchemy — trocar SQLite por
  PostgreSQL é só mudar a `DATABASE_URL`.
- Logs estruturados em arquivo e banco, com níveis (INFO/WARNING/ERROR).
- `docker-compose` com `restart: unless-stopped` para resiliência.

## 📊 Sincronização de cliques, pedidos e comissão

- **Shopee**: 100% automática. Um job periódico consulta o relatório de
  conversões da Affiliate Open API e atualiza cada publicação pelo sub_id.
- **Mercado Livre**: o programa de afiliados **não tem API pública** de
  relatórios (só a Shopee tem). A alternativa é exportar o CSV manualmente
  no painel (mercadolivre.com.br/afiliados → Relatórios) e importar pelo
  botão "📥 Importar relatório do Mercado Livre" no painel administrativo,
  ou rodando `processing/importar_relatorio_ml.py` diretamente.
- **Amazon**: ainda não implementado (a PA-API também não expõe relatório
  de conversões — normalmente isso é feito via relatório do Central de
  Vendas do Associado, também manual/CSV).

## 📈 Próximas evoluções sugeridas

Veja a seção final da conversa com a Claude para uma lista completa de
evoluções (multi-redes sociais, geração de imagens, encurtador de links
com tracking de cliques, IA para detectar ofertas falsas, etc).
