"""
processing/filters.py
=======================
Aqui ficam as regras de negócio que decidem SE uma oferta é boa o
suficiente para ser publicada. Separar isso em uma camada própria
(em vez de misturar com o coletor ou o publisher) segue o princípio de
"responsabilidade única": cada parte do código faz uma coisa só.
"""

import config


def calcular_metricas_desconto(preco_atual: float, preco_anterior: float) -> dict:
    """
    Calcula o percentual de desconto e o valor economizado.

    Fazemos esse cálculo de forma CENTRALIZADA (e não em cada coletor)
    para garantir que todo produto, não importa o marketplace de origem,
    seja avaliado com a mesma fórmula — evitando inconsistência.
    """
    valor_economizado = round(preco_anterior - preco_atual, 2)
    percentual_desconto = round((valor_economizado / preco_anterior) * 100, 1)
    return {
        "valor_economizado": valor_economizado,
        "percentual_desconto": percentual_desconto,
    }


def oferta_vale_a_pena(preco_atual: float, preco_anterior: float) -> bool:
    """
    Regra central: só consideramos uma oferta válida se:
    1. O preço anterior é realmente maior que o atual (óbvio, mas
       marketplaces às vezes retornam dados inconsistentes).
    2. O desconto bate o mínimo configurado (config.DESCONTO_MINIMO_PERCENTUAL).

    Isso evita cair na armadilha comum de "desconto fake" (quando a loja
    infla o preço 'de' artificialmente pouco antes da promoção).
    """
    if preco_anterior is None or preco_atual is None:
        return False
    if preco_anterior <= preco_atual:
        return False

    metricas = calcular_metricas_desconto(preco_atual, preco_anterior)
    return metricas["percentual_desconto"] >= config.DESCONTO_MINIMO_PERCENTUAL


def categoria_esta_ativa(categoria: str) -> bool:
    """Verifica se a categoria está habilitada nas configurações do usuário."""
    return config.CATEGORIAS_ATIVAS.get(categoria, False)
