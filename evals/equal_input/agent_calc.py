# inputs: brief.md (числа таблицы вписаны ниже)
# outputs: stdout
import numpy as np
from math import sqrt
rng = np.random.default_rng(1)
D = {('ref','cur'):(200,80,8), ('ref','new'):(800,304,80),
     ('ads','cur'):(800,80,32), ('ads','new'):(200,18,20)}
V, C = 900, 120
vol = {'ref':6000,'ads':4000}

def wilson(k,n,z=1.96):
    p=k/n; d=1+z*z/n; c=p+z*z/(2*n); h=z*sqrt(p*(1-p)/n+z*z/(4*n*n))
    return (c-h)/d,(c+h)/d

print("== Ставки по ячейкам ==")
rate={}
for (ch,sc),(n,s,t) in D.items():
    pc,pt=s/n,t/n; rate[(ch,sc)]=(pc,pt)
    lo,hi=wilson(s,n); tlo,thi=wilson(t,n)
    print(f"{ch} {sc}: n={n} подписка {pc:.1%} [{lo:.1%};{hi:.1%}] обращения {pt:.1%} [{tlo:.1%};{thi:.1%}] "
          f"вклад/рег {pc*V-pt*C:.1f} ₽")

print("\n== Наивное объединение (парадокс Симпсона) ==")
for sc in ('cur','new'):
    n=sum(D[(c,sc)][0] for c in ('ref','ads')); s=sum(D[(c,sc)][1] for c in ('ref','ads'))
    t=sum(D[(c,sc)][2] for c in ('ref','ads'))
    print(sc, f"n={n} конверсия {s/n:.1%} обращения {t/n:.1%} доля рекомендаций {D[('ref',sc)][0]/n:.0%}")

print("\n== Разница внутри канала (новый - текущий) ==")
for ch in ('ref','ads'):
    dc=rate[(ch,'new')][0]-rate[(ch,'cur')][0]; dt=rate[(ch,'new')][1]-rate[(ch,'cur')][1]
    v=lambda sc: rate[(ch,sc)][0]*V-rate[(ch,sc)][1]*C
    print(f"{ch}: конверсия {dc*100:+.1f} п.п., обращения {dt*100:+.1f} п.п., вклад {v('new')-v('cur'):+.1f} ₽/рег")
    print(f"   безубыточный прирост конверсии при обращениях {dt:+.1%}: {dt*C/V*100:+.2f} п.п.")

print("\n== Прогноз на 10 000 регистраций (точечно) ==")
def total(scr):
    return sum(vol[ch]*(rate[(ch,scr[ch])][0]*V-rate[(ch,scr[ch])][1]*C) for ch in vol)
allcur=total({'ref':'cur','ads':'cur'}); allnew=total({'ref':'new','ads':'new'})
print(f"все текущий {allcur:,.0f} ₽; все новый {allnew:,.0f} ₽; разница {allnew-allcur:+,.0f} ₽")
print(f"только рекомендации новый: {total({'ref':'new','ads':'cur'})-allcur:+,.0f} ₽; только реклама новый: {total({'ref':'cur','ads':'new'})-allcur:+,.0f} ₽")
for share in (0.2,0.3,0.5):
    print(f"тест {share:.0%} трафика на новый (если оценки верны): {share*(allnew-allcur):+,.0f} ₽")

print("\n== Неопределённость (Бета-апостериоры, ТОЛЬКО шум выборки, без поправки на неслучайное назначение) ==")
N=200000
def draw(ch,sc):
    n,s,t=D[(ch,sc)]
    return rng.beta(s+1,n-s+1,N), rng.beta(t+1,n-t+1,N)
diff=0
dch={}
for ch in vol:
    c0,t0=draw(ch,'cur'); c1,t1=draw(ch,'new')
    d=vol[ch]*((c1*V-t1*C)-(c0*V-t0*C)); dch[ch]=d; diff=diff+d
    print(f"{ch}: разница вклада, медиана {np.median(d):+,.0f}, 90% [{np.percentile(d,5):+,.0f};{np.percentile(d,95):+,.0f}], P(новый лучше)={np.mean(d>0):.1%}")
print(f"итого: медиана {np.median(diff):+,.0f}, 90% [{np.percentile(diff,5):+,.0f};{np.percentile(diff,95):+,.0f}], P(новый лучше)={np.mean(diff>0):.1%}")
# конверсия отдельно
for ch in vol:
    c0,_=draw(ch,'cur'); c1,_=draw(ch,'new')
    print(f"{ch}: P(конверсия новый > текущий)={np.mean(c1>c0):.1%}; P(прирост > безубыточного)=",end="")
    _,t0=draw(ch,'cur'); _,t1=draw(ch,'new')
    print(f"{np.mean((c1-c0)*V-(t1-t0)*C>0):.1%}")
    print(f"   разница обращений: 95% [{np.percentile(t1-t0,2.5)*100:+.1f};{np.percentile(t1-t0,97.5)*100:+.1f}] п.п.")

print("\n== Чувствительность: при каком росте стоимости обращения/снижении конверсии итог меняется ==")
for C2 in (0,30,60,120):
    d=sum(vol[ch]*((rate[(ch,'new')][0]-rate[(ch,'cur')][0])*V-(rate[(ch,'new')][1]-rate[(ch,'cur')][1])*C2) for ch in vol)
    print(f"стоимость обращения {C2} ₽: разница {d:+,.0f} ₽")
print("Если обращения нового экрана НЕ вина экрана (напр. в текущем их недоучитывали) — нужен рандомизированный тест.")

print("\n== Размер теста (80% мощность, α=0.05, двусторонний), на группу ==")
def n_per(p1,delta):
    p2=p1+delta; z=1.96+0.84
    return z*z*(p1*(1-p1)+p2*(1-p2))/delta**2
for ch,p in (('ref',0.40),('ads',0.10)):
    for dl in (0.02,0.03,0.05):
        print(f"{ch} база {p:.0%}, обнаружить ±{dl*100:.0f} п.п.: {n_per(p,dl):,.0f} на группу")
print("обращения: 4% vs 10% (−6 п.п.): ", f"{n_per(0.04,0.06):,.0f} на группу")
print("месячный объём при 50/50: рекомендации 3000/группа, реклама 2000/группа; при 20% нового: 1200 и 800 в новой")
