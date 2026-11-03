import requests
import json
import os
import math
import tempfile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from collections import Counter
from itertools import combinations
import random
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuração das loterias suportadas
#
# Cada loteria tem seu próprio arquivo de histórico/perfil (pra não misturar
# jogos da Mega-Sena com os da Lotofácil) e seus próprios parâmetros de
# faixa/quantidade, mas usa exatamente a mesma metodologia.
# ---------------------------------------------------------------------------

def criar_sessao_http():
    """Sessão HTTP com retry automático para falhas temporárias da API."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "Loterias-Analyzer/2.0"})
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    sessao.mount("http://", HTTPAdapter(max_retries=retry))
    return sessao


HTTP = criar_sessao_http()


LOTERIAS = {
    "megasena": {
        "nome_exibicao": "Mega-Sena",
        "base_url": "https://loteriascaixa-api.herokuapp.com/api/megasena",
        "arquivo_historico": "historico_jogos_megasena.json",
        "arquivo_perfil": "perfil_estatistico_megasena.json",
        "total_numeros": 60,
        "dezenas_por_jogo": 6,
        "faixas": [(1, 20), (21, 40), (41, 60)],
        "numeros_por_faixa": 2,
        "n_quentes": 10,
        "n_frios": 8,
        "jogos_misto": 8,
        "jogos_combinados": 3,
        "max_escolhidos_fechado": 15,
    },
    "lotofacil": {
        "nome_exibicao": "Lotofácil",
        "base_url": "https://loteriascaixa-api.herokuapp.com/api/lotofacil",
        "arquivo_historico": "historico_jogos_lotofacil.json",
        "arquivo_perfil": "perfil_estatistico_lotofacil.json",
        "total_numeros": 25,
        "dezenas_por_jogo": 15,
        "faixas": [(1, 8), (9, 17), (18, 25)],
        "numeros_por_faixa": 5,
        "n_quentes": 8,
        "n_frios": 5,
        "jogos_misto": 8,
        "jogos_combinados": 3,
        "max_escolhidos_fechado": 17,
    },
}


# ---------------------------------------------------------------------------
# Coleta e análise de resultados
# ---------------------------------------------------------------------------

def obter_concurso_mais_recente_real(config):
    """Confirma qual é de fato o concurso mais recente, sem confiar cegamente
    no /latest da API.

    O bug relatado (jogos sempre conferidos contra um sorteio "atrasado",
    nunca contra o resultado atual) acontece porque o endpoint /latest desse
    serviço fica com cache desatualizado às vezes por horas depois do
    sorteio real já ter saído. Nessa hora, "proximoConcurso" não é o próximo
    sorteio de verdade — é o sorteio que ACABOU de sair, só que o cache
    ainda não percebeu. Resultado: o jogo é salvo apontando pro concurso
    errado (um que já ficou pra trás) e nunca bate com o sorteio que você
    esperava.

    Aqui a gente checa manualmente se já existe concurso mais novo do que o
    /latest está informando, avançando número por número até confirmar onde
    de fato a sequência de resultados termina.
    """
    base_url = config["base_url"]
    try:
        resp = HTTP.get(f"{base_url}/latest", timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        concurso_atual = dados["concurso"]
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Erro ao buscar dados da API: {e}")
        return None, None
    except (KeyError, ValueError) as e:
        print(f"⚠️  Resposta inesperada da API: {e}")
        return None, None

    candidato = concurso_atual + 1
    falhas_seguidas = 0
    while falhas_seguidas < 2:
        try:
            resp = HTTP.get(f"{base_url}/{candidato}", timeout=10)
            if resp.status_code == 200:
                dados_candidato = resp.json()
                if dados_candidato.get("dezenas"):
                    concurso_atual = candidato
                    candidato += 1
                    falhas_seguidas = 0
                    continue
            falhas_seguidas += 1
            candidato += 1
        except requests.exceptions.RequestException:
            falhas_seguidas += 1
            candidato += 1

    proximo_concurso = concurso_atual + 1
    return concurso_atual, proximo_concurso


def pegar_ultimos_resultados(config, quantidade=9, mostrar_progresso=False):
    """Pega os últimos N sorteios de verdade e também retorna o próximo
    concurso (já confirmado de verdade, não só o que o cache diz)."""
    resultados = []
    concurso_atual, proximo_concurso = obter_concurso_mais_recente_real(config)
    if concurso_atual is None:
        return [], None

    base_url = config["base_url"]
    for indice, concurso in enumerate(range(concurso_atual, concurso_atual - quantidade, -1), 1):
        if concurso < 1:
            break
        try:
            resp = HTTP.get(f"{base_url}/{concurso}", timeout=10)
            resp.raise_for_status()
            resultados.append(resp.json())
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Erro ao buscar concurso {concurso}: {e}")
        except (KeyError, ValueError) as e:
            print(f"⚠️  Resposta inesperada da API: {e}")

        if mostrar_progresso and (indice % 10 == 0 or indice == quantidade):
            print(f"   ...{indice}/{quantidade} sorteios buscados")

    return resultados, proximo_concurso


def analisar_ultimos_sorteios(config, resultados):
    """Análise exatamente como antes, só que parametrizada por loteria."""
    todas_dezenas = []
    for r in resultados:
        if "dezenas" in r:
            todas_dezenas.extend([int(d) for d in r.get("dezenas", [])])

    frequencia = Counter(todas_dezenas)

    print(f"\n📊 Análise dos ÚLTIMOS {len(resultados)} SORTEIOS ({config['nome_exibicao']}):")
    print("-" * 50)

    # Inclui também dezenas que não apareceram na janela. Antes, Counter.most_common()
    # ignorava números com frequência zero, o que distorcia a lista de "frios".
    universo = range(1, config["total_numeros"] + 1)
    ranking = sorted(((n, frequencia.get(n, 0)) for n in universo), key=lambda x: (-x[1], x[0]))
    ranking_frios = sorted(((n, frequencia.get(n, 0)) for n in universo), key=lambda x: (x[1], x[0]))
    quentes = ranking[:config["n_quentes"]]
    frios = ranking_frios[:config["n_frios"]]

    print("🔥 Números mais frequentes na janela:")
    print([num for num, _ in quentes])

    print("\n❄️  Números menos frequentes na janela:")
    print([num for num, _ in frios])

    return [num for num, _ in quentes], [num for num, _ in frios]


def gerar_jogo_misto(config, quentes, frios):
    """Combina sua metodologia com o sistema de equilíbrio baixo/médio/alto,
    generalizado para o tamanho de jogo e faixas de cada loteria."""
    jogo = set()
    for inicio, fim in config["faixas"]:
        faixa_numeros = list(range(inicio, fim + 1))
        qtd = min(config["numeros_por_faixa"], len(faixa_numeros))
        jogo.update(random.sample(faixa_numeros, qtd))

    n_trocas_quentes = max(1, config["dezenas_por_jogo"] // 2)
    candidatos_quentes = [n for n in quentes if n not in jogo]
    random.shuffle(candidatos_quentes)
    for num in candidatos_quentes[:n_trocas_quentes]:
        if random.random() < 0.75 and len(jogo) >= 1:
            jogo.discard(random.choice(list(jogo)))
            jogo.add(num)

    candidatos_frios = [n for n in frios if n not in jogo]
    if candidatos_frios and random.random() < 0.6:
        jogo.discard(random.choice(list(jogo)))
        jogo.add(random.choice(candidatos_frios))

    alvo = config["dezenas_por_jogo"]
    total = config["total_numeros"]
    while len(jogo) < alvo:
        jogo.add(random.randint(1, total))

    return sorted(jogo)[:alvo] if len(jogo) == alvo else sorted(random.sample(sorted(jogo), alvo))


def _jogos_diversos_o_bastante(novo_jogo, existentes, max_overlap):
    return all(len(set(novo_jogo) & set(existente)) <= max_overlap for existente in existentes)


def gerar_jogo_diverso(config, quentes, frios, existentes, max_overlap=None, tentativas=100):
    """Gera um jogo que não se sobrepõe demais com os já gerados nesta
    rodada. Laço de tentativas aumentado de 50 pra 100, já que agora
    geramos mais jogos por rodada e fica mais difícil achar um jogo
    suficientemente diferente dos outros dentro de poucas tentativas."""
    if max_overlap is None:
        max_overlap = max(1, config["dezenas_por_jogo"] - 3)

    candidato = gerar_jogo_misto(config, quentes, frios)
    for _ in range(tentativas):
        if _jogos_diversos_o_bastante(candidato, existentes, max_overlap):
            return candidato
        candidato = gerar_jogo_misto(config, quentes, frios)
    return candidato  # não conseguiu em N tentativas: usa o último gerado mesmo assim


def gerar_jogo_combinado(config, pool_frequencia, existentes, max_overlap=None, tentativas=100):
    """Gera um jogo usando só números que já apareceram nos OUTROS jogos
    gerados nesta mesma rodada (pesados pela frequência com que apareceram
    entre eles), em vez de sortear números totalmente novos do zero. É o
    que você pediu: os jogos "extras" reaproveitam as escolhas dos outros
    jogos possíveis já gerados, em vez de criar um conjunto do zero."""
    alvo = config["dezenas_por_jogo"]
    if max_overlap is None:
        max_overlap = max(1, alvo - 3)

    populacao = list(pool_frequencia.keys())
    pesos = list(pool_frequencia.values())

    def sorteia():
        jogo = set()
        tentativa_interna = 0
        while len(jogo) < alvo and tentativa_interna < 300:
            escolhido = random.choices(populacao, weights=pesos, k=1)[0]
            jogo.add(escolhido)
            tentativa_interna += 1
        while len(jogo) < alvo:
            jogo.add(random.randint(1, config["total_numeros"]))
        return sorted(jogo)

    candidato = sorteia()
    for _ in range(tentativas):
        if _jogos_diversos_o_bastante(candidato, existentes, max_overlap):
            return candidato
        candidato = sorteia()
    return candidato


# ---------------------------------------------------------------------------
# Histórico / lista de espera
# ---------------------------------------------------------------------------

def carregar_historico(config):
    arquivo = config["arquivo_historico"]
    if os.path.exists(arquivo):
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print("⚠️  Histórico corrompido ou ilegível, começando um novo.")
    return {"jogos": []}


def _salvar_json_atomico(arquivo, dados):
    """Evita corromper o JSON se o programa for interrompido durante a gravação."""
    pasta = os.path.dirname(os.path.abspath(arquivo)) or "."
    fd, temporario = tempfile.mkstemp(prefix=".tmp_loterias_", suffix=".json", dir=pasta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, arquivo)
    except Exception:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def salvar_historico(config, historico):
    try:
        _salvar_json_atomico(config["arquivo_historico"], historico)
    except OSError as e:
        print(f"⚠️  Não foi possível salvar o histórico: {e}")


def salvar_jogos_pendentes(config, jogos_info, concurso_alvo, quentes, frios):
    """Coloca os jogos gerados hoje na lista de espera, associados ao
    próximo concurso (já confirmado de verdade), pra conferir depois.

    jogos_info é uma lista de dicts {"numeros": [...], "classificacao_perfil": str},
    pra guardar também qual foi a classificação de soma/paridade de cada
    jogo no momento em que ele foi gerado — isso é o que permite depois
    checar se essa classificação tem alguma correlação real com acertos."""
    if concurso_alvo is None:
        print("⚠️  Não sei qual é o próximo concurso — não vou salvar na lista de espera.")
        return

    historico = carregar_historico(config)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    for info in jogos_info:
        historico["jogos"].append({
            "numeros": info["numeros"],
            "classificacao_perfil": info.get("classificacao_perfil"),
            "concurso_alvo": concurso_alvo,
            "quentes_usados": quentes,
            "frios_usados": frios,
            "data_gerado": agora,
            "status": "pendente",
            "acertos": None,
            "numeros_acertados": None,
        })

    salvar_historico(config, historico)
    print(f"\n📝 {len(jogos_info)} jogo(s) salvos na lista de espera para o concurso {concurso_alvo}.")


def conferir_pendentes(config):
    """Busca os jogos pendentes, tenta pegar o resultado do concurso alvo
    de cada um e atualiza o histórico com os acertos."""
    historico = carregar_historico(config)
    pendentes = [j for j in historico["jogos"] if j["status"] == "pendente"]

    if not pendentes:
        print("\n✅ Nenhum jogo pendente para conferir.")
        return

    concursos_alvo = sorted(set(j["concurso_alvo"] for j in pendentes))
    resultados_cache = {}

    for concurso in concursos_alvo:
        try:
            resp = HTTP.get(f"{config['base_url']}/{concurso}", timeout=10)
            if resp.status_code == 200:
                dados = resp.json()
                if "dezenas" in dados:
                    resultados_cache[concurso] = [int(d) for d in dados["dezenas"]]
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Erro ao buscar concurso {concurso}: {e}")

    atualizados = 0
    for jogo in pendentes:
        concurso = jogo["concurso_alvo"]
        if concurso in resultados_cache:
            sorteados = resultados_cache[concurso]
            acertados = [n for n in jogo["numeros"] if n in sorteados]
            jogo["status"] = "conferido"
            jogo["acertos"] = len(acertados)
            jogo["numeros_acertados"] = acertados
            jogo["resultado_sorteado"] = sorteados
            atualizados += 1

    salvar_historico(config, historico)

    if atualizados:
        print(f"\n✅ {atualizados} jogo(s) conferido(s) e atualizado(s) no histórico.")
    else:
        print("\n⏳ Resultado dos concursos pendentes ainda não saiu. Tente de novo mais tarde.")


def mostrar_estatisticas(config):
    """Mostra o desempenho acumulado: acertos médios e o quanto os
    números 'quentes'/'frios' realmente se confirmaram no sorteio seguinte."""
    historico = carregar_historico(config)
    conferidos = [j for j in historico["jogos"] if j["status"] == "conferido"]

    if not conferidos:
        print("\n📊 Ainda não há jogos conferidos para gerar estatísticas.")
        return

    total_jogos = len(conferidos)
    media_acertos = sum(j["acertos"] for j in conferidos) / total_jogos
    melhor = max(conferidos, key=lambda j: j["acertos"])

    print(f"\n📊 ESTATÍSTICAS DE DESEMPENHO — {config['nome_exibicao']} ({total_jogos} jogos conferidos)")
    print("-" * 50)
    print(f"Média de acertos por jogo: {media_acertos:.2f}")
    print(f"Melhor jogo: {melhor['numeros']} → {melhor['acertos']} acertos "
          f"(concurso {melhor['concurso_alvo']})")

    distrib = Counter(j["acertos"] for j in conferidos)
    print("\nDistribuição de acertos:")
    for pontos in sorted(distrib, reverse=True):
        print(f"  {pontos} acertos: {distrib[pontos]} jogo(s)")

    total_quentes_usados = 0
    quentes_que_saiam = 0
    total_frios_usados = 0
    frios_que_saiam = 0

    for j in conferidos:
        acertados = set(j["numeros_acertados"])
        for n in j.get("quentes_usados", []):
            if n in j["numeros"]:
                total_quentes_usados += 1
                if n in acertados:
                    quentes_que_saiam += 1
        for n in j.get("frios_usados", []):
            if n in j["numeros"]:
                total_frios_usados += 1
                if n in acertados:
                    frios_que_saiam += 1

    print("\n🔥 vs ❄️  Confirmação da metodologia:")
    if total_quentes_usados:
        print(f"  Quentes usados que saíram no sorteio seguinte: "
              f"{quentes_que_saiam}/{total_quentes_usados} "
              f"({100 * quentes_que_saiam / total_quentes_usados:.1f}%)")
    if total_frios_usados:
        print(f"  Frios usados que saíram no sorteio seguinte: "
              f"{frios_que_saiam}/{total_frios_usados} "
              f"({100 * frios_que_saiam / total_frios_usados:.1f}%)")

    print("\n💡 Lembrete: cada sorteio é independente. Isso mede se a sua metodologia")
    print("   'parece' funcionar, não se ela de fato prevê números futuros.")


def analisar_correlacao_perfil(config):
    """Checa se jogos classificados como '✓✓ Muito compatível' de fato
    acertam mais, na prática, do que os '⚠️ Atípico' — em vez de simplesmente
    assumir que o filtro de soma/paridade ajuda."""
    historico = carregar_historico(config)
    conferidos = [
        j for j in historico["jogos"]
        if j["status"] == "conferido" and j.get("classificacao_perfil")
    ]

    if len(conferidos) < 10:
        print(f"\n📊 Só {len(conferidos)} jogo(s) conferido(s) com classificação de perfil "
              "registrada. Use pelo menos 10 pra uma comparação minimamente confiável "
              "(jogos gerados antes dessa atualização não têm essa marcação salva).")
        return

    grupos = {}
    for j in conferidos:
        grupos.setdefault(j["classificacao_perfil"], []).append(j["acertos"])

    print(f"\n🔎 CORRELAÇÃO: classificação do perfil × acertos reais — {config['nome_exibicao']}")
    print("-" * 60)
    for classificacao, acertos_lista in sorted(
        grupos.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1]))
    ):
        media = sum(acertos_lista) / len(acertos_lista)
        print(f"{classificacao:<25} n={len(acertos_lista):<4} média de acertos: {media:.3f}")

    if len(grupos) >= 2:
        grupos_ordenados = sorted(grupos.values(), key=lambda lst: -(sum(lst) / len(lst)))
        melhor, pior = grupos_ordenados[0], grupos_ordenados[-1]
        if len(melhor) >= 5 and len(pior) >= 5:
            t_stat, df, p_valor = _teste_t_welch(melhor, pior)
            df_texto = f"{df:.1f}" if df is not None else "n/d"
            print(f"\n📐 Teste t (melhor grupo vs. pior grupo): t={t_stat:.3f}, gl≈{df_texto}, "
                  f"p≈{p_valor:.4f}")

    print("\n💡 Se as médias forem parecidas entre os grupos (e o p-valor não for baixo),")
    print("   o filtro de soma/paridade não tem sinal preditivo real — é só estética,")
    print("   já que cada sorteio é independente do perfil histórico.")


# ---------------------------------------------------------------------------
# Teste qui-quadrado de aderência (os sorteios reais são mesmo uniformes?)
# ---------------------------------------------------------------------------

def _p_valor_qui_quadrado(chi2_stat, df):
    """Aproximação de Wilson-Hilferty para o p-valor (cauda superior) da
    distribuição qui-quadrado, sem depender de scipy."""
    if chi2_stat <= 0:
        return 1.0
    termo = (chi2_stat / df) ** (1 / 3)
    numerador = termo - (1 - 2 / (9 * df))
    denominador = math.sqrt(2 / (9 * df))
    z = numerador / denominador
    return 0.5 * math.erfc(z / math.sqrt(2))


def teste_qui_quadrado(config):
    """Compara a frequência observada das dezenas, nos últimos N sorteios
    reais, com a frequência esperada sob distribuição uniforme."""
    try:
        quantidade = int(input("Quantos sorteios usar na amostra? (mín. 20, sugestão 50): ").strip())
    except ValueError:
        print("Valor inválido.")
        return

    if quantidade < 20:
        print("⚠️  Amostra pequena deixa o teste pouco confiável. Use pelo menos 20.")
        return

    print(f"\n🔎 Buscando {quantidade} sorteios para o teste...")
    resultados, _ = pegar_ultimos_resultados(config, quantidade, mostrar_progresso=True)
    if not resultados:
        print("⚠️  Não consegui buscar sorteios suficientes para o teste.")
        return

    total_numeros = config["total_numeros"]
    dezenas_por_jogo = config["dezenas_por_jogo"]

    freq = Counter()
    for r in resultados:
        for d in r.get("dezenas", []):
            freq[int(d)] += 1

    n_sorteios = len(resultados)
    esperado = n_sorteios * dezenas_por_jogo / total_numeros
    df = total_numeros - 1

    chi2 = sum((freq.get(num, 0) - esperado) ** 2 / esperado for num in range(1, total_numeros + 1))
    p_valor = _p_valor_qui_quadrado(chi2, df)

    print(f"\n📐 TESTE QUI-QUADRADO DE ADERÊNCIA — {config['nome_exibicao']} "
          f"({n_sorteios} sorteios, gl={df})")
    print("-" * 50)
    print(f"Frequência esperada por dezena: {esperado:.2f}")
    print(f"Estatística qui-quadrado: {chi2:.2f}")
    print(f"p-valor aproximado: {p_valor:.4f}")

    if p_valor < 0.05:
        print("\n⚠️  p < 0,05 — haveria evidência estatística de desvio da uniformidade.")
        print("   (Vale reconferir com uma amostra maior antes de tirar conclusões.)")
    else:
        print("\n✅ p ≥ 0,05 — consistente com sorteio uniforme/aleatório, como esperado.")
        print("   Ou seja: nenhuma dezena está 'atrasada' ou 'quente' de forma estatisticamente")
        print("   significativa — as variações observadas são só ruído normal do acaso.")


def _teste_t_welch(amostra1, amostra2):
    """Teste t de Welch (duas amostras, variâncias diferentes) pra saber se
    a diferença entre metodologia e controle é estatisticamente
    significativa ou só ruído. Sem depender de scipy: com os tamanhos de
    amostra típicos de um backtesting (centenas/milhares de jogos), o graus
    de liberdade de Welch já é grande o bastante pra aproximar a
    distribuição t por uma normal padrão, então o p-valor abaixo é uma
    aproximação (fica ligeiramente conservadora para amostras pequenas)."""
    n1, n2 = len(amostra1), len(amostra2)
    if n1 < 2 or n2 < 2:
        return 0.0, None, 1.0
    media1, media2 = sum(amostra1) / n1, sum(amostra2) / n2
    var1 = sum((x - media1) ** 2 for x in amostra1) / (n1 - 1)
    var2 = sum((x - media2) ** 2 for x in amostra2) / (n2 - 1)

    erro_padrao = math.sqrt(var1 / n1 + var2 / n2)
    if erro_padrao == 0:
        return 0.0, None, 1.0

    t_stat = (media1 - media2) / erro_padrao
    numerador_df = (var1 / n1 + var2 / n2) ** 2
    denominador_df = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
    df = numerador_df / denominador_df if denominador_df > 0 else None

    p_valor = math.erfc(abs(t_stat) / math.sqrt(2))  # aproximação normal, bicaudal
    return t_stat, df, p_valor


# ---------------------------------------------------------------------------
# Sistema fechado (wheeling system) — cobertura combinatória
# ---------------------------------------------------------------------------

def gerar_sistema_fechado(config, numeros_escolhidos, garantia):
    """Gera, por um algoritmo guloso de cobertura de conjuntos, o menor
    número de jogos (do tamanho da loteria escolhida) dentro dos números
    escolhidos, tal que: se 'garantia' dos números escolhidos saírem no
    sorteio oficial, pelo menos um dos jogos gerados vai conter todos eles."""
    tamanho_jogo = config["dezenas_por_jogo"]
    numeros_escolhidos = sorted(set(numeros_escolhidos))
    n = len(numeros_escolhidos)

    minimo = tamanho_jogo + 1
    maximo = config.get("max_escolhidos_fechado", tamanho_jogo + 9)
    garantia_min = tamanho_jogo - 3
    garantia_max = tamanho_jogo - 1

    if n < minimo:
        raise ValueError(f"Escolha pelo menos {minimo} números.")
    if n > maximo:
        raise ValueError(f"Máximo de {maximo} números (acima disso fica computacionalmente pesado).")
    if not (garantia_min <= garantia <= garantia_max):
        raise ValueError(f"Garantia deve estar entre {garantia_min} e {garantia_max}.")

    alvos = set(combinations(numeros_escolhidos, garantia))
    candidatos = list(combinations(numeros_escolhidos, tamanho_jogo))

    if len(alvos) * len(candidatos) > 5_000_000:
        print("⚠️  Essa combinação de quantidade de números e garantia é pesada; pode demorar.")
        print("   Considere reduzir a quantidade de números escolhidos, se possível.")

    cobertos = set()
    jogos_selecionados = []

    while alvos - cobertos:
        restantes = alvos - cobertos
        melhor_jogo = None
        melhor_cobertura = set()

        for jogo in candidatos:
            cobertura_jogo = {c for c in combinations(jogo, garantia) if c in restantes}
            if len(cobertura_jogo) > len(melhor_cobertura):
                melhor_cobertura = cobertura_jogo
                melhor_jogo = jogo

        if melhor_jogo is None:
            break  # segurança, não deveria acontecer

        jogos_selecionados.append(melhor_jogo)
        cobertos |= melhor_cobertura
        candidatos.remove(melhor_jogo)

    return [list(j) for j in jogos_selecionados]


def menu_sistema_fechado(config):
    tamanho_jogo = config["dezenas_por_jogo"]
    minimo = tamanho_jogo + 1
    maximo = config.get("max_escolhidos_fechado", tamanho_jogo + 9)
    garantia_min = tamanho_jogo - 3
    garantia_max = tamanho_jogo - 1

    entrada = input(f"Digite os números escolhidos ({minimo} a {maximo}), separados por vírgula: ").strip()
    try:
        numeros = [int(x) for x in entrada.split(",") if x.strip()]
    except ValueError:
        print("Entrada inválida.")
        return

    if any(n < 1 or n > config["total_numeros"] for n in numeros):
        print(f"Todos os números devem estar entre 1 e {config['total_numeros']}.")
        return

    try:
        garantia = int(input(f"Nível de garantia ({garantia_min} a {garantia_max}): ").strip())
    except ValueError:
        print("Valor inválido.")
        return

    print("\n⏳ Calculando cobertura combinatória (pode levar alguns segundos)...")
    try:
        jogos = gerar_sistema_fechado(config, numeros, garantia)
    except ValueError as e:
        print(f"⚠️  {e}")
        return

    print(f"\n🎟️  SISTEMA FECHADO — {config['nome_exibicao']}: {len(jogos)} jogo(s) necessário(s)")
    print(f"    Garantia: se {garantia} dos números escolhidos saírem, pelo menos 1 jogo os contém todos.")
    print("-" * 50)
    for i, jogo in enumerate(jogos, 1):
        print(f"Jogo {i}: {jogo}")
    print(f"\n💡 Confira o preço atual da aposta simples para calcular o custo total ({len(jogos)} jogos).")


# ---------------------------------------------------------------------------
# Backtesting histórico — a metodologia bate o acaso puro?
# ---------------------------------------------------------------------------

def rodar_backtesting(config):
    """Simula a metodologia (8 jogos mistos + 3 combinados = 11) contra
    sorteios JÁ ocorridos, e compara com 11 jogos 100% aleatórios (controle)
    contra o MESMO sorteio."""
    try:
        n_rodadas = int(input("Quantos sorteios históricos testar? (sugestão 50, mín. 20): ").strip())
    except ValueError:
        print("Valor inválido.")
        return

    if n_rodadas < 20:
        print("⚠️  Use pelo menos 20 rodadas para um resultado minimamente confiável.")
        return

    janela_analise = 9
    jogos_por_rodada = config["jogos_misto"] + config["jogos_combinados"]
    total_necessario = n_rodadas + janela_analise

    print(f"\n🔎 Buscando {total_necessario} sorteios históricos (pode levar um tempo)...")
    resultados, _ = pegar_ultimos_resultados(config, total_necessario, mostrar_progresso=True)
    if len(resultados) < janela_analise + 1:
        print("⚠️  Não consegui buscar sorteios suficientes para o backtesting.")
        return

    cronologico = list(reversed(resultados))

    resultados_metodo = []
    resultados_controle = []
    rodadas_executadas = 0
    total_numeros = config["total_numeros"]
    dezenas_por_jogo = config["dezenas_por_jogo"]

    for i in range(janela_analise, len(cronologico)):
        dezenas_alvo = set(int(d) for d in cronologico[i].get("dezenas", []))
        if not dezenas_alvo:
            continue

        janela = cronologico[i - janela_analise:i]
        todas_dezenas_janela = [int(d) for r in janela for d in r.get("dezenas", [])]
        frequencia = Counter(todas_dezenas_janela)
        quentes = [n for n, _ in frequencia.most_common(config["n_quentes"])]
        frios = [n for n, _ in frequencia.most_common()[-config["n_frios"]:]]

        jogos_rodada = []
        pool_frequencia = Counter()

        for _ in range(config["jogos_misto"]):
            jogo = gerar_jogo_diverso(config, quentes, frios, jogos_rodada)
            jogos_rodada.append(jogo)
            pool_frequencia.update(jogo)
            resultados_metodo.append(len(set(jogo) & dezenas_alvo))

        for _ in range(config["jogos_combinados"]):
            jogo = gerar_jogo_combinado(config, pool_frequencia, jogos_rodada)
            jogos_rodada.append(jogo)
            resultados_metodo.append(len(set(jogo) & dezenas_alvo))

        for _ in range(jogos_por_rodada):
            jogo_controle = random.sample(range(1, total_numeros + 1), dezenas_por_jogo)
            resultados_controle.append(len(set(jogo_controle) & dezenas_alvo))

        rodadas_executadas += 1

    if not resultados_metodo:
        print("⚠️  Não houve dados suficientes para simular nenhuma rodada.")
        return

    media_metodo = sum(resultados_metodo) / len(resultados_metodo)
    media_controle = sum(resultados_controle) / len(resultados_controle)
    esperado_teorico = dezenas_por_jogo * dezenas_por_jogo / total_numeros

    distrib_metodo = Counter(resultados_metodo)
    distrib_controle = Counter(resultados_controle)

    print(f"\n📈 BACKTESTING — {config['nome_exibicao']} ({rodadas_executadas} sorteios simulados × "
          f"{jogos_por_rodada} jogos = {len(resultados_metodo)} jogos no total)")
    print("-" * 60)
    print(f"Média de acertos — Sua metodologia:        {media_metodo:.3f}")
    print(f"Média de acertos — Controle (aleatório):   {media_controle:.3f}")
    print(f"Valor esperado teórico (acaso puro):        {esperado_teorico:.3f}")

    print(f"\n{'Acertos':<10}{'Metodologia':<15}{'Controle':<15}")
    for pontos in range(0, dezenas_por_jogo + 1):
        print(f"{pontos:<10}{distrib_metodo.get(pontos, 0):<15}{distrib_controle.get(pontos, 0):<15}")

    diferenca = media_metodo - media_controle
    print(f"\n💡 Diferença método vs. controle: {diferenca:+.3f} acertos por jogo, em média.")

    t_stat, df, p_valor = _teste_t_welch(resultados_metodo, resultados_controle)
    df_texto = f"{df:.1f}" if df is not None else "n/d"
    print(f"\n📐 Teste t de Welch (metodologia vs. controle): t={t_stat:.3f}, gl≈{df_texto}, "
          f"p≈{p_valor:.4f}")
    if p_valor < 0.05:
        print("   ⚠️  p < 0,05 — diferença estatisticamente significativa nesta amostra.")
        print("   Vale reconferir com uma amostra bem maior antes de confiar nisso: com muitas")
        print("   comparações ao longo do tempo, achar um p<0,05 de vez em quando é esperado")
        print("   por acaso (é o que se chama de 'p-hacking' se você só olhar quando dá certo).")
    else:
        print("   ✅ p ≥ 0,05 — não há evidência estatística de que a metodologia bate o acaso.")

    if abs(diferenca) < 0.05:
        print("   Praticamente idêntico ao acaso — nenhuma vantagem estatística mensurável.")
    else:
        print("   Há uma diferença observada, mas com essa quantidade de rodadas ela pode")
        print("   perfeitamente ser só ruído estatístico, não uma vantagem real.")
        print("   Rode de novo com mais sorteios (ex: 200+) para reduzir a chance de coincidência.")


# ---------------------------------------------------------------------------
# Perfil estatístico real (soma e paridade dos sorteios de verdade)
# ---------------------------------------------------------------------------

def obter_perfil_estatistico(config, forcar_atualizacao=False, quantidade=200):
    """Calcula (ou reaproveita de um cache de até 30 dias) a faixa real de
    soma e de quantidade de pares dos sorteios históricos, pra comparar os
    jogos gerados com o padrão real de cada loteria."""
    arquivo = config["arquivo_perfil"]
    if not forcar_atualizacao and os.path.exists(arquivo):
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                dados = json.load(f)
            data_calculo = datetime.strptime(dados["calculado_em"], "%d/%m/%Y")
            if (datetime.now() - data_calculo).days < 30:
                return dados["perfil"]
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass

    resultados, _ = pegar_ultimos_resultados(config, quantidade, mostrar_progresso=True)
    if not resultados:
        return None

    dezenas_por_jogo = config["dezenas_por_jogo"]
    somas = []
    contagem_pares = []
    for r in resultados:
        dezenas = [int(d) for d in r.get("dezenas", [])]
        if len(dezenas) == dezenas_por_jogo:
            somas.append(sum(dezenas))
            contagem_pares.append(sum(1 for d in dezenas if d % 2 == 0))

    if not somas:
        return None

    somas_ordenadas = sorted(somas)

    def percentil(lista_ordenada, p):
        idx = min(int(p / 100 * (len(lista_ordenada) - 1)), len(lista_ordenada) - 1)
        return lista_ordenada[idx]

    perfil = {
        "n_amostra": len(somas_ordenadas),
        "soma_p10": percentil(somas_ordenadas, 10),
        "soma_p90": percentil(somas_ordenadas, 90),
        "soma_media": sum(somas_ordenadas) / len(somas_ordenadas),
        "pares_mais_comuns": [p for p, _ in Counter(contagem_pares).most_common(3)],
    }

    try:
        _salvar_json_atomico(arquivo, {
            "calculado_em": datetime.now().strftime("%d/%m/%Y"),
            "perfil": perfil,
        })
    except OSError as e:
        print(f"⚠️  Não foi possível salvar o perfil estatístico: {e}")

    return perfil


def classificar_jogo_real(jogo, perfil):
    if perfil is None:
        return "— (sem perfil calculado ainda)"
    soma = sum(jogo)
    pares = sum(1 for n in jogo if n % 2 == 0)
    soma_ok = perfil["soma_p10"] <= soma <= perfil["soma_p90"]
    pares_ok = pares in perfil["pares_mais_comuns"]
    if soma_ok and pares_ok:
        return "✓✓ Muito compatível"
    elif soma_ok or pares_ok:
        return "✓ Compatível"
    else:
        return "⚠️ Atípico"


def menu_atualizar_perfil(config):
    print(f"\n🔄 Recalculando perfil estatístico real de {config['nome_exibicao']} "
          f"(busca ~200 sorteios, pode demorar)...")
    perfil = obter_perfil_estatistico(config, forcar_atualizacao=True)
    if perfil is None:
        print("⚠️  Não consegui calcular o perfil.")
        return

    print(f"\n📐 PERFIL ESTATÍSTICO REAL — {config['nome_exibicao']} "
          f"(baseado em {perfil['n_amostra']} sorteios)")
    print("-" * 50)
    print(f"Soma típica (10º–90º percentil): {perfil['soma_p10']} a {perfil['soma_p90']}")
    print(f"Soma média histórica: {perfil['soma_media']:.1f}")
    print(f"Quantidades de pares mais comuns por jogo: {perfil['pares_mais_comuns']}")
    print("\n💾 Perfil salvo — será reaproveitado por 30 dias antes de recalcular.")


def gerar_grafico_evolucao(config):
    """Gera um PNG com dois gráficos: a distribuição de acertos (histograma)
    e a média móvel de acertos ao longo do tempo, comparada com o valor
    esperado teórico do acaso puro — pra visualizar a variância em vez de
    só olhar números soltos."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  matplotlib não está instalado. Rode: pip install matplotlib")
        return

    historico = carregar_historico(config)
    conferidos = [j for j in historico["jogos"] if j["status"] == "conferido"]

    if len(conferidos) < 5:
        print("\n📊 Poucos jogos conferidos ainda para gerar um gráfico útil (mín. 5).")
        return

    conferidos.sort(key=lambda j: datetime.strptime(j["data_gerado"], "%d/%m/%Y %H:%M"))

    acertos = [j["acertos"] for j in conferidos]
    dezenas_por_jogo = config["dezenas_por_jogo"]
    total_numeros = config["total_numeros"]
    esperado_teorico = dezenas_por_jogo * dezenas_por_jogo / total_numeros

    janela_media_movel = min(10, len(acertos))
    media_movel = []
    for i in range(len(acertos)):
        inicio = max(0, i - janela_media_movel + 1)
        media_movel.append(sum(acertos[inicio:i + 1]) / (i - inicio + 1))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    max_acertos = max(acertos)
    bins = list(range(0, max_acertos + 2))
    ax1.hist(acertos, bins=bins, align="left", rwidth=0.8, color="steelblue")
    ax1.axvline(esperado_teorico, color="red", linestyle="--",
                label=f"Esperado teórico ({esperado_teorico:.2f})")
    ax1.set_xlabel("Acertos por jogo")
    ax1.set_ylabel("Frequência")
    ax1.set_title(f"Distribuição de acertos — {config['nome_exibicao']}")
    ax1.legend()

    ax2.plot(range(1, len(acertos) + 1), media_movel, color="steelblue",
             label=f"Média móvel ({janela_media_movel} jogos)")
    ax2.axhline(esperado_teorico, color="red", linestyle="--",
                label=f"Esperado teórico ({esperado_teorico:.2f})")
    ax2.set_xlabel("Jogo (ordem cronológica)")
    ax2.set_ylabel("Acertos médios")
    ax2.set_title("Evolução dos acertos ao longo do tempo")
    ax2.legend()

    plt.tight_layout()
    sufixo = config["arquivo_historico"].replace("historico_jogos_", "").replace(".json", "")
    nome_arquivo = f"evolucao_desempenho_{sufixo}.png"
    plt.savefig(nome_arquivo, dpi=120)
    plt.close(fig)

    print(f"\n📈 Gráfico salvo em: {nome_arquivo}")
    print("   Se a média móvel ficar oscilando em torno da linha vermelha (esperado teórico),")
    print("   é sinal de que não há vantagem real mensurável sobre o acaso.")


# ---------------------------------------------------------------------------
# Geração de jogos (8 mistos + 3 combinados = 11 no total)
# ---------------------------------------------------------------------------

def gerar_novos_jogos(config):
    print(f"🚀 {config['nome_exibicao']} — Equilíbrio + Sua Metodologia")
    print("=" * 55)

    resultados, proximo_concurso = pegar_ultimos_resultados(config, 9)
    if not resultados:
        print("⚠️  Não consegui buscar sorteios recentes — abortando geração.")
        return

    quentes, frios = analisar_ultimos_sorteios(config, resultados)
    perfil = obter_perfil_estatistico(config)  # usa cache se já tiver sido calculado antes

    n_misto = config["jogos_misto"]
    n_combinados = config["jogos_combinados"]

    print(f"\n🎟️  {n_misto + n_combinados} JOGOS GERADOS:")
    print("-" * 40)

    jogos_gerados = []
    jogos_info = []
    pool_frequencia = Counter()

    for i in range(n_misto):
        jogo = gerar_jogo_diverso(config, quentes, frios, jogos_gerados)
        jogos_gerados.append(jogo)
        pool_frequencia.update(jogo)
        soma = sum(jogo)
        classificacao_real = classificar_jogo_real(jogo, perfil)
        jogos_info.append({"numeros": jogo, "classificacao_perfil": classificacao_real})
        print(f"Jogo {i+1}: {jogo} | Soma: {soma} | {classificacao_real}")

    print(f"\n🔗 Mais {n_combinados} jogo(s), combinando os números já escolhidos acima:")
    for i in range(n_combinados):
        jogo = gerar_jogo_combinado(config, pool_frequencia, jogos_gerados)
        jogos_gerados.append(jogo)
        soma = sum(jogo)
        classificacao_real = classificar_jogo_real(jogo, perfil)
        jogos_info.append({"numeros": jogo, "classificacao_perfil": classificacao_real})
        print(f"Jogo {n_misto + i + 1} (combinado): {jogo} | Soma: {soma} | {classificacao_real}")

    print(f"\n📅 Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    salvar_jogos_pendentes(config, jogos_info, proximo_concurso, quentes, frios)


# ---------------------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------------------

def escolher_loteria():
    while True:
        print("\nEscolha a loteria:")
        print("1 - Mega-Sena")
        print("2 - Lotofácil")
        escolha = input("Opção: ").strip()
        if escolha == "1":
            return LOTERIAS["megasena"]
        if escolha == "2":
            return LOTERIAS["lotofacil"]
        print("Opção inválida. Digite 1 ou 2.")


def main():
    config = LOTERIAS["megasena"]
    while True:
        print("\n" + "=" * 55)
        print(f"Loteria atual: {config['nome_exibicao']}")
        print("1 - Gerar novos jogos")
        print("2 - Conferir jogos pendentes (após o sorteio sair)")
        print("3 - Ver estatísticas de desempenho")
        print("4 - Teste qui-quadrado (os sorteios reais são uniformes?)")
        print("5 - Gerar sistema fechado (wheeling) a partir de N números")
        print("6 - Backtesting (testar a metodologia contra sorteios passados)")
        print("7 - Atualizar perfil estatístico real (soma/paridade)")
        print("8 - Trocar de loteria (Mega-Sena / Lotofácil)")
        print("9 - Perfil real vs. acertos: o filtro soma/paridade prediz algo?")
        print("10 - Gráfico de distribuição e evolução dos acertos")
        print("0 - Sair")
        escolha = input("Escolha uma opção: ").strip()

        if escolha == "1":
            gerar_novos_jogos(config)
        elif escolha == "2":
            conferir_pendentes(config)
        elif escolha == "3":
            mostrar_estatisticas(config)
        elif escolha == "4":
            teste_qui_quadrado(config)
        elif escolha == "5":
            menu_sistema_fechado(config)
        elif escolha == "6":
            rodar_backtesting(config)
        elif escolha == "7":
            menu_atualizar_perfil(config)
        elif escolha == "8":
            config = escolher_loteria()
        elif escolha == "9":
            analisar_correlacao_perfil(config)
        elif escolha == "10":
            gerar_grafico_evolucao(config)
        elif escolha == "0":
            print("Até mais! 👋")
            break
        else:
            print("Opção inválida.")


if __name__ == "__main__":
    main()
