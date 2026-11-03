import streamlit as st
from collections import Counter
from datetime import datetime
import pandas as pd

import loterias_engine as eng
import sigma_lab

st.set_page_config(page_title="Σ SIGMA Mobile", page_icon="🎯", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
.block-container {padding-top: 1.4rem; max-width: 1250px;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
.ball {display:inline-flex; width:44px; height:44px; border-radius:50%; align-items:center; justify-content:center; margin:4px; font-weight:800; background:#f2f4f7; border:1px solid #d0d5dd; color:#101828;}
.ball-hit {background:#12b76a !important; border-color:#039855 !important; color:white !important; box-shadow:0 0 0 3px rgba(18,183,106,.16);}
.ball-draw {background:#1570ef !important; border-color:#175cd3 !important; color:white !important;}
.result-card {padding:16px; border:1px solid #e4e7ec; border-radius:14px; margin:10px 0; background:rgba(255,255,255,.02);}
.game {padding:14px 16px; border:1px solid #e4e7ec; border-radius:14px; margin:9px 0;}
.small {color:#667085; font-size:.88rem;}
@media (max-width: 700px) {
  .block-container {padding: .65rem .75rem 2rem;}
  .ball {width: 35px; height: 35px; margin: 2px; font-size: .83rem;}
  .result-card, .game {padding: 10px;}
  [data-testid="stMetricValue"] {font-size: 1.2rem;}
  [data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
  [data-testid="stHorizontalBlock"] > div {min-width: 135px;}
  h1 {font-size: 1.8rem !important;}
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def resultados_recentes(chave, quantidade=9):
    return eng.pegar_ultimos_resultados(eng.LOTERIAS[chave], quantidade)

@st.cache_data(ttl=3600, show_spinner=False)
def perfil_real(chave):
    return eng.obter_perfil_estatistico(eng.LOTERIAS[chave])

def bolas(nums):
    return "".join(f'<span class="ball">{int(n):02d}</span>' for n in nums)

def bolas_conferidas(nums, acertados=None, classe_sorteio=False):
    acertados = set(int(n) for n in (acertados or []))
    partes = []
    for n in nums:
        n = int(n)
        extra = " ball-draw" if classe_sorteio else (" ball-hit" if n in acertados else "")
        partes.append(f'<span class="ball{extra}">{n:02d}</span>')
    return "".join(partes)

def gerar_jogos(config, resultados, perfil):
    todas = [int(d) for r in resultados for d in r.get("dezenas", [])]
    freq = Counter(todas)
    universo = range(1, config["total_numeros"] + 1)
    quentes = [n for n, _ in sorted(((n, freq.get(n,0)) for n in universo), key=lambda x:(-x[1], x[0]))[:config["n_quentes"]]]
    frios = [n for n, _ in sorted(((n, freq.get(n,0)) for n in universo), key=lambda x:(x[1], x[0]))[:config["n_frios"]]]
    jogos, infos, pool = [], [], Counter()
    for _ in range(config["jogos_misto"]):
        jogo = eng.gerar_jogo_diverso(config, quentes, frios, jogos)
        jogos.append(jogo); pool.update(jogo)
        infos.append({"numeros": jogo, "tipo":"Misto", "classificacao": eng.classificar_jogo_real(jogo, perfil)})
    for _ in range(config["jogos_combinados"]):
        jogo = eng.gerar_jogo_combinado(config, pool, jogos)
        jogos.append(jogo)
        infos.append({"numeros": jogo, "tipo":"Combinado", "classificacao": eng.classificar_jogo_real(jogo, perfil)})
    return infos, quentes, frios

st.title("Σ SIGMA · Mobile")
st.caption("Laboratório de loterias • versão web para celular")
st.info("💾 Faça backup dos jogos regularmente. Em hospedagens gratuitas, arquivos locais podem ser apagados quando o servidor reinicia.")

with st.sidebar:
    st.header("Configuração")
    nome = st.radio("Loteria", ["Mega-Sena", "Lotofácil"], horizontal=True)
    chave = "megasena" if nome == "Mega-Sena" else "lotofacil"
    config = eng.LOTERIAS[chave]
    st.info("Os filtros estatísticos organizam combinações; não aumentam a probabilidade matemática de cada combinação ser sorteada.")
    if st.button("🔄 Atualizar dados", use_container_width=True):
        st.cache_data.clear(); st.rerun()

abas = st.tabs(["🏠 Painel", "🎟️ Gerar jogos", "🧾 Histórico", "📊 Estatísticas", "🧩 Sistema fechado", "🔬 Laboratório SIGMA"])

with abas[0]:
    try:
        with st.spinner("Consultando resultados..."):
            resultados, proximo = resultados_recentes(chave, 9)
        if resultados:
            ultimo = resultados[0]
            c1,c2,c3 = st.columns(3)
            c1.metric("Último concurso", ultimo.get("concurso", "—"))
            c2.metric("Próximo concurso", proximo or "—")
            c3.metric("Sorteios analisados", len(resultados))
            st.subheader("Último resultado")
            st.markdown(bolas(ultimo.get("dezenas", [])), unsafe_allow_html=True)
            todas=[int(d) for r in resultados for d in r.get('dezenas',[])]
            freq=Counter(todas)
            df=pd.DataFrame({"Dezena": list(range(1,config['total_numeros']+1)), "Ocorrências":[freq.get(n,0) for n in range(1,config['total_numeros']+1)]})
            st.subheader("Frequência nos 9 concursos recentes")
            st.bar_chart(df.set_index("Dezena"))
        else: st.warning("Não foi possível carregar os resultados agora.")
    except Exception as e:
        st.error(f"Falha ao consultar a API: {e}")

with abas[1]:
    st.subheader("Gerador de jogos")
    st.write(f"Gera {config['jogos_misto']} jogos mistos + {config['jogos_combinados']} combinados usando a metodologia atual.")
    if st.button("🎲 GERAR JOGOS", type="primary", use_container_width=True):
        try:
            resultados, proximo = resultados_recentes(chave, 9)
            perfil = perfil_real(chave)
            if not resultados: st.error("Não consegui obter resultados recentes.")
            else:
                infos, quentes, frios = gerar_jogos(config, resultados, perfil)
                st.session_state[f"jogos_{chave}"] = (infos, quentes, frios, proximo)
        except Exception as e: st.error(f"Erro ao gerar jogos: {e}")
    pacote=st.session_state.get(f"jogos_{chave}")
    if pacote:
        infos, quentes, frios, proximo = pacote
        a,b=st.columns(2)
        a.write("🔥 **Mais frequentes:** " + ", ".join(f"{n:02d}" for n in quentes))
        b.write("❄️ **Menos frequentes:** " + ", ".join(f"{n:02d}" for n in frios))
        for i,info in enumerate(infos,1):
            jogo=info['numeros']; pares=sum(n%2==0 for n in jogo)
            st.markdown(f'<div class="game"><b>Jogo {i} · {info["tipo"]}</b><br>{bolas(jogo)}<br><span class="small">Soma {sum(jogo)} · {pares} pares · {info["classificacao"]}</span></div>', unsafe_allow_html=True)
        if st.button("💾 Salvar estes jogos no histórico"):
            eng.salvar_jogos_pendentes(config,[{"numeros":i['numeros'],"classificacao_perfil":i['classificacao']} for i in infos],proximo,quentes,frios)
            st.success(f"Jogos salvos para conferência do concurso {proximo}.")

with abas[2]:
    st.subheader("Histórico e apuração")
    import json
    historico_export = eng.carregar_historico(config)
    st.download_button("⬇️ Baixar backup do histórico (JSON)", json.dumps(historico_export, ensure_ascii=False, indent=2).encode("utf-8"), file_name=f"sigma_historico_{chave}.json", mime="application/json", use_container_width=True)
    with st.expander("📤 Restaurar backup do histórico"):
        st.warning("A restauração substitui o histórico atual desta loteria. Guarde um backup antes.")
        arquivo_backup = st.file_uploader("Selecione um arquivo JSON de histórico", type=["json"], key=f"backup_{chave}")
        confirmar = st.checkbox("Confirmo a substituição do histórico", key=f"confirmar_{chave}")
        if st.button("Restaurar histórico", disabled=not (arquivo_backup and confirmar), key=f"restaurar_{chave}"):
            try:
                dados = json.load(arquivo_backup)
                if not isinstance(dados, dict) or not isinstance(dados.get("jogos"), list):
                    raise ValueError("Arquivo incompatível: campo jogos ausente.")
                eng.salvar_historico(config, dados)
                st.success("Histórico restaurado.")
                st.rerun()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                st.error(f"Não foi possível restaurar: {e}")
    hist=eng.carregar_historico(config).get("jogos",[])
    if not hist:
        st.info("Ainda não existem jogos salvos.")
    else:
        if st.button("✅ Conferir pendentes agora", type="primary"):
            eng.conferir_pendentes(config)
            st.success("Conferência executada.")
            st.rerun()

        conferidos=[j for j in hist if j.get('status')=='conferido']
        pendentes=[j for j in hist if j.get('status')=='pendente']
        c1,c2=st.columns(2)
        c1.metric("Jogos conferidos", len(conferidos))
        c2.metric("Jogos pendentes", len(pendentes))

        concursos = {}
        for j in reversed(hist):
            concursos.setdefault(j.get('concurso_alvo','—'), []).append(j)

        for concurso, jogos_concurso in concursos.items():
            with st.expander(f"Concurso {concurso} · {len(jogos_concurso)} jogo(s)", expanded=(concurso==next(iter(concursos)))):
                primeiro = jogos_concurso[0]
                resultado = primeiro.get('resultado_sorteado')
                # Compatibilidade com históricos antigos: tenta reconstruir o resultado pela API.
                if not resultado and primeiro.get('status')=='conferido':
                    try:
                        resp = eng.HTTP.get(f"{config['base_url']}/{concurso}", timeout=10)
                        if resp.status_code == 200:
                            resultado = [int(d) for d in resp.json().get('dezenas', [])]
                    except Exception:
                        resultado = None
                if resultado:
                    st.markdown("**Resultado sorteado**")
                    st.markdown(bolas_conferidas(resultado, classe_sorteio=True), unsafe_allow_html=True)
                    st.caption("🔵 Azul = dezenas sorteadas · 🟢 Verde = dezenas acertadas dentro de cada jogo")
                for idx,j in enumerate(jogos_concurso,1):
                    nums=j.get('numeros',[])
                    acertados=j.get('numeros_acertados') or []
                    status=j.get('status','pendente')
                    acertos=j.get('acertos')
                    resumo = f"{acertos} acerto(s)" if acertos is not None else "Aguardando resultado"
                    html = f'<div class="result-card"><b>Jogo {idx} · {resumo}</b><br>{bolas_conferidas(nums, acertados)}<br><span class="small">Gerado em {j.get("data_gerado","—")} · Status: {status}</span></div>'
                    st.markdown(html, unsafe_allow_html=True)

with abas[3]:
    st.subheader("Desempenho dos jogos salvos")
    hist=eng.carregar_historico(config).get("jogos",[])
    conf=[j for j in hist if j.get('status')=='conferido' and j.get('acertos') is not None]
    if not conf: st.info("Ainda não há jogos conferidos suficientes para mostrar estatísticas.")
    else:
        media=sum(j['acertos'] for j in conf)/len(conf); melhor=max(j['acertos'] for j in conf)
        c1,c2,c3=st.columns(3); c1.metric("Jogos conferidos",len(conf)); c2.metric("Média de acertos",f"{media:.2f}"); c3.metric("Melhor resultado",melhor)
        dist=Counter(j['acertos'] for j in conf)
        st.bar_chart(pd.DataFrame({"Acertos":sorted(dist),"Jogos":[dist[x] for x in sorted(dist)]}).set_index('Acertos'))

with abas[4]:
    st.subheader("Sistema fechado")
    st.caption("Cobertura combinatória dentro de um conjunto escolhido. A garantia vale apenas sob a condição matemática descrita; não prevê o sorteio.")
    minimo=config['dezenas_por_jogo']+1; maximo=config.get('max_escolhidos_fechado',config['dezenas_por_jogo']+9)
    texto=st.text_input(f"Números escolhidos ({minimo} a {maximo}), separados por vírgula")
    garantia=st.slider("Garantia",config['dezenas_por_jogo']-3,config['dezenas_por_jogo']-1)
    if st.button("Calcular fechamento"):
        try:
            nums=[int(x.strip()) for x in texto.split(',') if x.strip()]
            if any(n<1 or n>config['total_numeros'] for n in nums): raise ValueError("Há números fora da faixa permitida.")
            jogos=eng.gerar_sistema_fechado(config,nums,garantia)
            st.success(f"{len(jogos)} jogos gerados.")
            for i,j in enumerate(jogos,1): st.markdown(f"**{i}.** {bolas(j)}",unsafe_allow_html=True)
        except Exception as e: st.error(str(e))

st.divider()
st.caption(f"SIGMA Mobile · {datetime.now().year} · Pesquisa experimental; resultados passados não predizem sorteios futuros.")

with abas[5]:
    pacote = st.session_state.get(f"jogos_{chave}")
    base = [i['numeros'] for i in pacote[0]] if pacote else None
    sigma_lab.render(config, base, chave)
