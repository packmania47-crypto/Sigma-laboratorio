"""SIGMA V3: laboratory for combinatorial diversity and Monte Carlo controls."""
import random
from collections import Counter
from datetime import datetime
import pandas as pd
import streamlit as st


def overlap_metrics(games, universe):
    pairs = [len(set(a) & set(b)) for i, a in enumerate(games) for b in games[i+1:]]
    freq = Counter(n for g in games for n in g)
    return {"dezenas_cobertas":len(freq), "sobreposicao_media":sum(pairs)/len(pairs) if pairs else 0,
            "sobreposicao_maxima":max(pairs) if pairs else 0, "frequencia_minima":min(freq.get(n,0) for n in range(1,universe+1)),
            "frequencia_maxima":max(freq.values()) if freq else 0}


def coverage_games(universe, size, count, seed=42, pool_size=500):
    """Greedy search minimizing pair overlap and repeated number imbalance."""
    rng=random.Random(seed)
    chosen=[]
    counts=Counter()
    for _ in range(count):
        best=None; best_score=None
        for _ in range(pool_size):
            candidate=tuple(sorted(rng.sample(range(1,universe+1),size)))
            if candidate in chosen: continue
            overlaps=[len(set(candidate)&set(g)) for g in chosen]
            newcounts=counts.copy(); newcounts.update(candidate)
            # Strongly penalize excessive overlap, and balance frequency across the full universe.
            score=(sum(x*x for x in overlaps) + 0.4*sum(newcounts.get(n,0)**2 for n in range(1,universe+1)),
                   max(overlaps,default=0))
            if best_score is None or score < best_score: best,best_score=candidate,score
        if best is None: break
        chosen.append(list(best)); counts.update(best)
    return chosen


def random_games(universe,size,count,seed):
    rng=random.Random(seed)
    seen=set(); out=[]
    while len(out)<count:
        game=tuple(sorted(rng.sample(range(1,universe+1),size)))
        if game not in seen: seen.add(game); out.append(list(game))
    return out


def simulate(groups, universe, draw_size, trials, seed):
    rng=random.Random(seed)
    totals={name:{"best":Counter(),"sum":0,"hits11":0,"hits12":0,"hits3":0,"hits4":0} for name in groups}
    for _ in range(trials):
        draw=set(rng.sample(range(1,universe+1),draw_size))
        for name,games in groups.items():
            hits=[len(draw.intersection(g)) for g in games]
            best=max(hits)
            x=totals[name]; x['best'][best]+=1; x['sum']+=sum(hits)/len(hits)
            for threshold,key in [(11,'hits11'),(12,'hits12'),(3,'hits3'),(4,'hits4')]:
                x[key]+=int(best>=threshold)
    return totals


def render(config, base=None, lottery='lotofacil'):
    st.subheader('🔬 Σ SIGMA — Laboratório V3')
    st.caption('Comparação experimental de conjuntos de jogos. Sorteios são simulados uniformemente, sem previsão de dezenas.')
    n=config['total_numeros']; k=config['dezenas_por_jogo']; count=11
    col1,col2=st.columns(2)
    with col1: seed=st.number_input('Semente reproduzível',min_value=1,max_value=999999999,value=20261009,step=1)
    with col2: trials=st.select_slider('Simulações Monte Carlo',options=[1000,5000,10000,25000],value=5000)
    if st.button('🧪 Gerar e comparar estratégias',type='primary',use_container_width=True):
        groups={'Cobertura Inteligente':coverage_games(n,k,count,int(seed)), 'Controle Aleatório':random_games(n,k,count,int(seed)+1)}
        if base and len(base)==count: groups={'Base V2 (lote atual)':base,**groups}
        with st.spinner('Simulando resultados independentes...'):
            result=simulate(groups,n,k,int(trials),int(seed)+2)
        st.session_state[f'sigma_lab_{lottery}']={'groups':groups,'result':result,'seed':int(seed),'trials':int(trials),'created':datetime.now().isoformat(timespec='seconds')}
    data=st.session_state.get(f'sigma_lab_{lottery}')
    if not data:
        st.info('Clique em Gerar e comparar estratégias. Para incluir a Base V2, gere um lote na aba Gerar jogos primeiro.')
        return
    groups=data['groups']; result=data['result']; t=data['trials']; threshold=11 if lottery=='lotofacil' else 3
    rows=[]
    for name,games in groups.items():
        m=overlap_metrics(games,n); r=result[name]
        rows.append({'Estratégia':name,'Dezenas distintas no lote':m['dezenas_cobertas'],
                     'Sobreposição média':round(m['sobreposicao_media'],2),
                     f'Prob. de ≥{threshold} em algum jogo (%)':round(100*r[f'hits{threshold}']/t,2),
                     'Média de acertos por jogo':round(r['sum']/t,3)})
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    st.caption('Probabilidades estimadas por simulação. As médias por jogo devem ser próximas entre estratégias; a diversidade pode mudar a chance de ao menos um jogo atingir um limiar.')
    for name,games in groups.items():
        with st.expander(f'{name} — {len(games)} jogos'):
            for idx,game in enumerate(games,1): st.write(f'{idx:02d}: '+ ' '.join(f'{v:02d}' for v in game))
    games_rows=[]
    for name,games in groups.items():
        for idx,game in enumerate(games,1):
            games_rows.append({'modalidade':lottery,'estrategia':name,'jogo':idx,'dezenas':' '.join(f'{v:02d}' for v in game),'semente':data['seed'],'gerado_em':data['created']})
    st.download_button('⬇️ Exportar jogos do laboratório (CSV)',pd.DataFrame(games_rows).to_csv(index=False).encode('utf-8-sig'),file_name=f'SIGMA_V3_{lottery}_jogos.csv',mime='text/csv')
    st.download_button('⬇️ Exportar comparação (CSV)',pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),file_name=f'SIGMA_V3_{lottery}_comparacao.csv',mime='text/csv')
    st.warning('Experimento exploratório: otimização e comparação não demonstram capacidade de prever sorteios. Preserve jogos e sementes antes do resultado para avaliação prospectiva.')
