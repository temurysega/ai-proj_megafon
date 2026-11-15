# Расчёт цены за ГБ по публичным заявлениям (источники — в утверждениях C005, C013 и др.)
beeline = 1050/30          # 30 ГБ за 1050 ₽ (Европа, от)
beeline_cis = 1450/30
mts_turkey_20 = 1200/20    # 20 ГБ за 1200 ₽ (заявление МТС, 2024)
mts_turkey_1 = 100/1
roam_day = (489, 590)      # 1 ГБ/сутки (обзор vc.ru, Китай) -> ₽/ГБ при 1 ГБ в сутки
megafon_default = 7.9*1024*1024/100   # 7,9 ₽ за 100 КБ -> ₽/ГБ
print("Билайн Европа ₽/ГБ", round(beeline,1), "СНГ", round(beeline_cis,1))
print("МТС Турция ₽/ГБ", mts_turkey_1, mts_turkey_20)
print("Суточный роуминг ₽/ГБ (1 ГБ/сут)", roam_day, "отношение к Билайн Европа:", [round(x/beeline,1) for x in roam_day])
print("МегаФон по умолчанию ₽/ГБ", round(megafon_default))
share_connect = 1-0.38
print("доля eSIM среди всех опрошенных ≈", round(share_connect*0.14*100,1), "%")
