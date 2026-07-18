"""
collectors/base_collector.py
=============================
Define um "contrato" (classe abstrata) que todo coletor de marketplace
deve seguir. Isso é o padrão de projeto "Strategy": cada marketplace
implementa sua própria forma de buscar produtos, mas todos entregam os
dados no MESMO formato para o resto do sistema.

Vantagem prática: se amanhã você quiser adicionar a Casas Bahia ou a
AliExpress, basta criar uma nova classe que segue esse mesmo contrato —
nada mais no sistema precisa mudar.
"""

from abc import ABC, abstractmethod


class BaseCollector(ABC):
    """Toda classe de coleta de ofertas deve herdar desta e implementar buscar_ofertas()."""

    nome_marketplace: str = "base"

    @abstractmethod
    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """
        Deve retornar uma lista de dicionários no seguinte formato padrão:

        {
            "id_externo": "MLB123456",
            "marketplace": "mercadolivre",
            "categoria": "eletronicos",
            "titulo": "Fone de Ouvido Bluetooth XYZ",
            "url_produto": "https://...",
            "url_imagem": "https://...",
            "preco_atual": 89.90,
            "preco_anterior": 149.90,
            "frete_gratis": True,
            "parcelamento": "3x de R$ 29,96 sem juros",
            "avaliacao": 4.6,
        }

        Observação: percentual_desconto e valor_economizado NÃO precisam
        vir daqui — eles são calculados depois, na camada de processamento,
        para garantir que o cálculo seja sempre consistente.
        """
        raise NotImplementedError

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        """
        Implementação padrão (pode ser sobrescrita por cada marketplace,
        já que cada um tem uma regra diferente de parâmetro de afiliado).
        """
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}ref={tag_afiliado}"

    def gerar_short_link_com_subid(self, url_longa: str, sub_id: str) -> str | None:
        """
        Gera um link curto rastreável com um sub_id de tracking, quando o
        marketplace oferece esse recurso na sua API de afiliados.

        Implementação padrão: retorna None (marketplace não suporta).
        Cada collector pode sobrescrever este método quando tiver esse
        recurso disponível (ex: ShopeeCollector via generateShortLink).

        O pipeline de publicação chama este método de forma genérica —
        se vier None, ele simplesmente usa o link de afiliado normal,
        sem tracking por sub-ID.
        """
        return None

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """
        Consulta o marketplace para saber se uma oferta JÁ PUBLICADA
        ainda está válida (produto disponível e com o preço atual).

        Deve retornar:
            {"disponivel": bool, "preco_atual": float | None}

        Ou None se NÃO for possível verificar (ex: marketplace sem
        endpoint de consulta individual, erro de rede, etc).

        Retornar None é uma decisão de design deliberada: o job de
        detecção de expiração trata "não consegui verificar" como
        "assumir que ainda está válida" — é mais seguro pecar por
        deixar um post antigo no ar do que apagar/marcar como expirada
        uma oferta que na real ainda está de pé, só porque a verificação
        falhou por um problema técnico passageiro.

        Implementação padrão: não sabe verificar (retorna None).
        """
        return None
