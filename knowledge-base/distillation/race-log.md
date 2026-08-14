# 赛马结果回填日志（race-log）

> 每行 = 一道子问题的赛马结论（候选集 / winner / 主指标 / 结果摘要 / 稳健性），由 scripts/kb_backfill.py 从 workspace 追加；数值均来自 workspace 可复现产物。

| 日期 | workspace | 问 | 候选(kind) | 赛马协议 | 结果摘要 | 稳健性 | 数据源 |
|---|---|---|---|---|---|---|---|
| 2026-08-14 | 2025C-nipt | q1 | q1_baseline_mlr(baseline), q1_adv_saturating_long(advanced) | chosen=q1_baseline_mlr; winner=q1_baseline_mlr; metric=RMSE (min) | q1_baseline_mlr=0.03242；q1_adv_saturating_long=0.03290 | sensitivity-ok | results/q1/scheme-comparison.md |
| 2026-08-14 | 2025C-nipt | q2 | q2_baseline_binned(baseline), q2_adv_ic_surv(advanced) | chosen=q2_adv_ic_surv; winner=q2_adv_ic_surv; metric=expected_risk (min) | q2_adv_ic_surv=1.64507；q2_baseline_binned=3.34047 | sensitivity-ok | results/q2/scheme-comparison.md |
| 2026-08-14 | 2025C-nipt | q3 | q3_baseline_bmi_cov(baseline), q3_adv_predict_assign(advanced) | chosen=q3_baseline_bmi_cov; winner=q3_baseline_bmi_cov; metric=expected_risk (min) | q3_baseline_bmi_cov=1.76259；q3_adv_predict_assign=2.53835；q2_adv_ic_surv（Q2 winner 对照）=1.64507 | sensitivity-ok | results/q3/scheme-comparison.md |
| 2026-08-14 | 2025C-nipt | q4 | q4_baseline_z3(baseline), q4_baseline_logistic(baseline), q4_adv_rf_cost(advanced) | chosen=q4_baseline_logistic; winner=q4_baseline_logistic; metric=auc (max) | q4_baseline_logistic=0.8205；q4_baseline_z3=0.5039；q4_adv_rf_cost=0.7756；z3_vs_logistic=0.8205；z3_vs_rf=0.7756；logistic_vs_rf=0.7756 | holdout-ok; repeated-cv-ok | results/q4/scheme-comparison.md |
