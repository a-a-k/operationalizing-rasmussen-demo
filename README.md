# Closed-allocation drift measurement

Executable runtime probes and saved-data analyses for observing resource
adaptation under closed administrative budgets. The measurement layer retains
the complete selected allocation, expresses relative movement in full isometric
log-ratio (ILR) coordinates, and connects the history to observed pressure,
actions, recipient output and external service outcomes.

The runtime uses a digest-pinned OpenTelemetry Demo deployment. CPU ceilings
are configured limits, not reserved or necessarily consumed CPU. CPU and RAM
have separate budgets. Checkout is SLO-safe only when request p95 is at most
500 ms and unsuccessful scheduled operations are below 1%; restart/OOM remains
a diagnostic and never overrides that label.

## Start here

- [Formal glossary / Формальный глоссарий](#formal-glossary): определения, переменные, формулы и роли всех представлений; версия 0.1.2.
- [Passive short-horizon warnings](probe8/README.md): frozen old-data rules and
  separate independent confirmation, including every signal and its outcome.
- [Native practical forecast comparison](probe8/results/prometheus-baseline-v0.1.0/README.md):
  genuine Prometheus predict_linear replay, shared coverage and the detection/
  false-signal trade-off; not another runtime campaign or a geometry-only test.
- [Results and their interpretation](RESULTS.md): comparisons, conclusions and limits.
- [Guarded full-stack adaptation](probe7/results/main-v0.2.0/README.md): three
  external requirements and measured donor selection.
- [Accumulated relative-drift analysis](probe7/results/accumulated-v0.1.0/README.md):
  complete histories, differences hidden by entire selected local traces, actual
  equal absolute transfers and their different relative meaning. The additional
  analogy comparison is reported separately, without predictive superiority.
- [Reproduction guide](REPRODUCING.md): offline checks and manual runtime workflows.
- [Sequential CPU evidence](probe5/results/README.md), including the separate
  [retrospective pre-crossing analysis](probe5/results/history-v0.1.0/README.md).
- [Joint CPU/RAM evidence](probe6/results/README.md).
- [Full-coordinate and metric checks](geometry/results/v0.1.0/RESULTS.md).

## Evidence map

Each runtime row is a separate series. Saved-data rows explicitly reuse their
named source rather than adding replications. Counts are never pooled across
campaigns, and synthetic transformations are not runtime observations.

| Evidence | Comparison | Recorded result | Data |
| --- | --- | --- | --- |
| Practical forecast comparison (saved Probe 8 data) | Native Prometheus predict_linear versus unchanged ILR scores | Prometheus settings warned 0/6, 1/6 and 0/6 events with 7, 7 and 11 false signals. Frozen live ILR warned 5/6 with 45 false signals; previously enumerated stricter ILR points warned 2/6 with 2 or 6 false signals. Retrospective whole-rule comparison, not independent confirmation of a new threshold or isolation of geometry. | [Interpretation](probe8/results/prometheus-baseline-v0.1.0/README.md), [native queries](probe8/results/prometheus-baseline-v0.1.0/native-responses.jsonl.gz), [all predictions](probe8/results/prometheus-baseline-v0.1.0/decisions.csv) |
| Independent passive warnings (Probe 8) | Four frozen old-data rules on twenty new runner pairs | All 840 windows valid. ILR warned 5/6 first violations about 52 s ahead; full shares 4/6, local and service-only rules 2/6. False decisions: 45, 38, 6 and 3; ILR precision 10%. No established practical superiority. | [Interpretation](probe8/results/confirmation-v0.1.0/README.md), [all signals](probe8/results/confirmation-v0.1.0/evaluation/warning-decisions.csv), [event timing](probe8/results/confirmation-v0.1.0/evaluation/first-violation-events.csv) |
| Guarded full-stack adaptation (Probe 7) | Live donor choices versus unchanged controls; eleven CPU/RAM allocation parts | 24 pairs received, 23 complete baseline-safe pairs. Advertising gains in 23/23 fixed-endpoint contrasts; 7 adaptive histories violated requirements versus 0 matched controls. No ILR advantage over full shares in the analog task. | [Interpretation](probe7/results/main-v0.2.0/README.md), [windows](probe7/results/main-v0.2.0/windows.csv), [metric errors](probe7/results/main-v0.2.0/pair-retrieval-errors.csv) |
| Accumulated guarded histories (saved Probe 7 data) | Full baseline-referenced displacement versus three selected local traces; equal absolute versus relative changes | Three observed histories had identical selected traces through cycle 6 but different allocations and safe/unsafe outcomes: two overlapping witnesses. Real 0.04-CPU transfers meant donor losses of 11.4%, 16.0% and 26.7%. | [Interpretation](probe7/results/accumulated-v0.1.0/README.md), [whole histories](probe7/results/accumulated-v0.1.0/history-windows.csv), [prefix witnesses](probe7/results/accumulated-v0.1.0/prefix-witnesses.csv), [transfers](probe7/results/accumulated-v0.1.0/actual-transfer-examples.csv) |
| Sequential CPU migration (Probe 5) | Pressure-motivated transfers versus unchanged controls | 19/20 planned pairs received. All 19 adaptive histories crossed at steps 8--13; controls stayed safe. At retrospective step 6 all pairs were still safe, with positive control-adjusted changes in both goodput and checkout p95. | [Trajectories](probe5/results/trajectory-level.csv), [paired epochs](probe5/results/paired-epochs.csv), [step-6 pairs](probe5/results/history-v0.1.0/step6-pairs.csv) |
| Joint CPU/RAM follow-up (Probe 6) | Control, CPU-only, RAM-only and joint histories | 20 valid blocks; five matched joint-only unsafe witnesses. Crossings: joint 20/20, CPU-only 14/20, RAM-only 17/20, control 0/20. | [Trajectories](probe6/results/joint-v0.2.0/trajectory-level.csv), [matched steps](probe6/results/joint-v0.2.0/four-way-epochs.csv) |
| Geometry verification | Full ILR and equal multiplicative updates across starting states | Six unlabeled synthetic checks; 1,145 saved windows retained in separate series. Equal relative updates have equal ILR displacement; Euclidean share distance describes additive change. | [Checks](geometry/results/v0.1.0/metric-properties.csv), [coordinates](geometry/results/v0.1.0/trajectory-coordinates.csv), [figure](geometry/results/v0.1.0/geometry.svg) |
| Fixed endpoints (Probe 3) | Corrected A/B and matched-summary service permutations | A safe in 16/16, nearer B unsafe in 10/16. Equal-balance permutations: checkout-low unsafe in 4/11; payment-low and shipping-low safe in 12/12 and 11/11. | [Interpretation](probe3/results/README.md), [all 104 points](probe3/results/point-level.csv), [aggregate](probe3/results/summary.json) |
| Threshold scenarios (Probe 4) | Twelve configurations, two loads, five repetitions | 109/120 points valid. At zero observed false alarms, balance detected 10/33 and 22/39 unsafe points; local OR detected 30/33 and 30/39. In-sample only. | [Interpretation](probe4/results/README.md), [points](probe4/results/point-level.csv), [all rules](probe4/results/thresholds.csv) |

Historical [Probe 1](probe1/) and [Probe 2](probe2/) are preserved separately:
221/256 paired reversals and 8/28 complete context witnesses, respectively.
Probe 1 omitted its intended generator-start gate; its conditional sensitivity
analysis is not a corrected execution. See the
[historical interpretation](docs/historical-endpoints.md) for deviations,
timeouts, failure diagnostics and selection provenance.

## What this establishes

Runtime histories instantiate a constructed adaptation mechanism: measured
recipient pressure motivates closed transfers, useful recipient output grows,
and another service approaches and crosses an externally measured boundary.
Fixed endpoints demonstrate information lost by radial magnitude and a single
group projection. Full ILR coordinates preserve the selected allocation; known
compositional geometry gives relative changes a consistent scale.

The accumulated saved-data analysis also shows differences hidden by an entire
sequence of selected local relations. Full raw-share states retain the same
allocation information as full ILR states. Differences of those states across
different starting allocations, without the starting states themselves, are
not equivalent descriptors; the glossary makes that distinction explicit.
Equal absolute transfers need not mean equal
proportional changes. Full initial state, budgets and subsequent vectors remain
available, and reversals do not erase previously measured failures.

These results establish a measurement basis, not a universally better detector,
production failure probability, human-behavior model or calibrated safe region.
The guarded full-stack follow-up demonstrates adaptive donor selection and
three external business requirements. Its limited held-pair-out analog task
does not show an ILR advantage over full shares; only CPU moves within those
histories because recipient RAM benefit was not established.
A separate fixed observer rule now has independent online confirmation: it
warned before 5/6 first violations, but nine of ten ILR signals were false
within its two-cycle horizon. The detection/false-warning trade-off does not
establish practical superiority. Platform integration, actionable alert
quality and benefits of interventions remain separate evaluations. Budgets,
workload and runtime history condition outcomes.

A separate [native Prometheus comparison](probe8/results/prometheus-baseline-v0.1.0/README.md)
reuses those warning observations. Previously enumerated stricter ILR points
show a favorable observed trade-off against the specified practical forecasts.
This secondary retrospective result is not independent validation of a new
threshold or isolation of the contribution of geometry.

## Verification without running a workload

Python 3.13 and its standard library suffice; no Docker, network or data-science
packages are needed:

```bash
python -B scripts/verify_archive.py
```

This checks checksums, local documentation links, anonymity, all unit-test suites
and saved-data analyses, including accumulated guarded histories and the step-6 contrasts. Full experiments run
only in the manual workflows in [REPRODUCING.md](REPRODUCING.md).
Pushing changes runs static verification only, not a workload campaign.

## Provenance and retention

Executed designs, image digests, action revisions and primary observations are
preserved. Execution identifiers and commits in metadata refer to the original
runs, without identifying source-hosting links in documentation. Post-run
analyses are explicitly versioned and do not alter frozen experiments.

Committed observations, aggregates and rules are the reviewable archive;
reading them does not depend on short-lived Actions artifacts. Native streams
and diagnostics are distinct execution artifacts, not reconstructed by compact
tables. [SHA256SUMS](SHA256SUMS) covers code, data and documentation using
canonical LF text bytes, and compressed primary inputs as exact binary bytes.
LICENSE is excluded so redacting its copyright holder
in a review mirror does not invalidate code/data verification; the original
license attribution is retained in the source repository.

<a id="formal-glossary"></a>

## Formal glossary / Формальный глоссарий

Версия 0.1.2. Обозначения сверены с реализованным Probe 7, его отдельным
анализом накопленных историй и проверкой предупреждений Probe 8 в §15.
Это описание существующих вычислений, не изменение выполненного дизайна. В других probes число
компонентов, бюджеты и требования могут отличаться; их данные не объединяются.

### 1. Индексы и область описания

| Обозначение | Определение | Значение в Probe 7 |
| --- | --- | --- |
| $j$ | Идентификатор пары прогонов на одном runner | 24 пары |
| $\pi$ | Политика внутри пары | $\mathrm{adapt}$ или $\mathrm{ctrl}$; отдельный свежий стек для каждой |
| $t$ | Номер измерительного окна, не физическое время | $0$ — baseline; $1,\ldots,20$ — последующие окна |
| $r$ | Вид ресурса | CPU или RAM |
| $i\in\mathcal I$ | Компонент выбранного распределения | 11 компонентов; фиксированный порядок ниже |
| $D$ | Число компонентов одного распределения | $D=11$ |
| $T_t$ | Длительность измерительного окна | 60 s для baseline, 30 s далее |
| $W_{j\pi t}$ | Эксплуатационный контекст | Нагрузка, VUs генератора, временные интервалы, характеристики host и прочее |

Порядок компонентов:

```text
frontend, cart, checkout, payment, currency, shipping,
product-catalog, ad, accounting, kafka, astronomy-db
```

Ниже индексы $j,\pi$ обычно опущены: все формулы относятся к конкретной
истории. При сравнении разных историй эти индексы восстанавливаются.

**«Полное» далее означает полное выбранное распределение этих 11 компонентов,
а не полное внутреннее состояние программной системы.** Очереди, содержимое
памяти, другие сервисы и состояние host этим вектором не описываются.

### 2. Абсолютное выделение ресурса: $q_t^{(r)}$

$$
q_t^{(r)}=(q_{1t}^{(r)},\ldots,q_{Dt}^{(r)}),\qquad q_{it}^{(r)}>0.
$$

$q_{it}^{(r)}$ — назначенный компоненту лимит ресурса в его собственных единицах:
CPU units или bytes памяти. Это настройки контейнеров, которые эксперимент
меняет и проверяет чтением фактических ограничений.

Они **не равны** фактически потреблённому ресурсу и не являются гарантированным
резервированием мощности host. Наблюдаемое потребление обозначим отдельно
$a_{it}^{(r)}$; например, потреблённые CPU cores за окно или memory usage.

Бюджет выбранного распределения:

$$
B_t^{(r)}=\sum_{i=1}^{D}q_{it}^{(r)}.
$$

В выполненной кампании на измеренных allocation points:

$$
B_t^{(\mathrm{CPU})}=3.4\ \mathrm{CPU},\qquad
B_t^{(\mathrm{RAM})}=4544\ \mathrm{MiB}.
$$

**Замкнутое перераспределение** здесь означает сохранение этих сумм при
изменении индивидуальных лимитов. Это условие нашего дизайна. Оно не следует
автоматически из наличия контейнеров или Kubernetes.

Индивидуальные CPU/RAM requests и limits, а также ограничения их сумм,
существуют в реальных платформах; например,
[Kubernetes ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/).
Метрики настроек доступны через
[kube-state-metrics](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md).
Однако квота платформы обычно задаёт верхнее ограничение суммы, не обязательно
её постоянство или полное использование. Наши бюджеты — суммы выбранных
настроенных лимитов, не физическая ёмкость всей машины.

### 3. Доли и композиционное состояние: $x_t^{(r)}$, $X_t$

Операция замыкания положительного вектора:

$$
\mathcal C(v)=\frac{v}{\sum_i v_i}.
$$

Доля компонента в бюджете своего ресурса:

$$
x_{it}^{(r)}=\frac{q_{it}^{(r)}}{B_t^{(r)}},\qquad
x_t^{(r)}=\mathcal C(q_t^{(r)}).
$$

При этом:

$$
x_t^{(r)}\in\mathcal S^{D-1},\qquad
\mathcal S^{D-1}=\{x\in\mathbb R_{>0}^{D}:\sum_i x_i=1\}.
$$

Это внутренность симплекса: $D$ положительных долей, но $D-1$ независимых
степеней свободы. В Probe 7 одно распределение лежит в $\mathcal S^{10}$.
Доли $x_i$ также являются барицентрическими координатами точки стандартного
симплекса: $x=\sum_i x_i e_i$. Поэтому «перейти в барицентры» — неточная
формулировка: доли уже задают такое представление точки.

Совместное относительное состояние CPU и RAM:

$$
X_t=(x_t^{(\mathrm{CPU})},x_t^{(\mathrm{RAM})})
\in\mathcal S^{10}\times\mathcal S^{10}.
$$

CPU и RAM нормируются **раздельно**. Складывать CPU units с MiB и затем
нормировать их общей суммой нельзя. Это произведение двух симплексов,
не одно распределение 22 взаимозаменяемых ресурсов.

Список всех долей удобно хранить как конкатенацию:

$$
v_t=\begin{pmatrix}x_t^{(\mathrm{CPU})}\\x_t^{(\mathrm{RAM})}\end{pmatrix}
\in\mathbb R^{22}.
$$

В нём две отдельные суммы равны 1; всего 20 степеней свободы. Конкатенация
используется для хранения и сравнения без сложения физических единиц.

**Ранее названная «полная таблица исходных долей» — именно последовательность
$v_t$.** «Исходные» означало непреобразованные в ILR данные, а не только
baseline. Правильное название: **вектор всех ресурсных долей $v_t$**.

Его роль: исходные данные для CoDA и информационно-полное контрольное
представление. Он не является отдельным стандартным production-детектором.
При известных бюджетах исходные лимиты восстанавливаются:

$$
q_t^{(r)}=B_t^{(r)}x_t^{(r)}.
$$

Сами доли уже являются композиционными данными. «Анализ долей без ILR» не
означает, что данные перестали быть композиционными.

**Вектор долей — данные, а не метрика.** В контрольном способе эти данные
сравниваются обычной евклидовой метрикой; для одного ресурса
$d_E(x,y)=\sqrt{\sum_i(x_i-y_i)^2}$. Это не Aitchison-метрика. В CoDA-варианте
те же распределения преобразуются в ILR, где евклидово расстояние соответствует
Aitchison-расстоянию. Поэтому название сравниваемого способа —
**«евклидова геометрия долей»**, а не «полные доли». В Probe 8 обе ресурсные
геометрии дополнительно имеют фиксированные training-масштабы, и оба способа
получают одинаковые сервисные признаки.

### 4. Абсолютный перенос и аддитивное изменение: $\Delta q_t$, $\Delta x_t$

**Изменение абсолютных выделений за шаг**:

$$
\Delta q_t^{(r)}=q_t^{(r)}-q_{t-1}^{(r)}.
$$

Если между двумя измеренными состояниями выполнен только перенос из донора
$d$ получателю $b$ в размере $\alpha$ CPU, без промежуточных откатов:

$$
\Delta q_t^{(\mathrm{CPU})}=\alpha(e_b-e_d),\qquad
\Delta q_t^{(\mathrm{RAM})}=0,
$$

где $e_i$ — единичный вектор компонента $i$. Поэтому сумма изменений равна 0.
В кампании $b=\mathrm{ad}$ и $\alpha=0.04$ CPU.

**Аддитивное изменение долей за шаг**:

$$
\Delta x_t^{(r)}=x_t^{(r)}-x_{t-1}^{(r)},\qquad
\Delta v_t=v_t-v_{t-1}.
$$

При постоянном бюджете:

$$
\Delta x_t^{(r)}=\frac{\Delta q_t^{(r)}}{B^{(r)}}.
$$

Следовательно, одинаковый перенос между теми же компонентами при одинаковом
бюджете даёт одинаковый **весь вектор** $\Delta x_t$, независимо от того,
сколько у донора было до переноса. Это корректное измерение аддитивного
изменения, но ещё не описание его пропорционального смысла.

При меняющемся бюджете эта сокращённая формула неверна; нужно вычислять
$q_t^{(r)}/B_t^{(r)}-q_{t-1}^{(r)}/B_{t-1}^{(r)}$.

### 5. Пропорциональное изменение: множители $u_t^{(r)}$

Фактический множитель изменения индивидуального лимита:

$$
u_{it}^{(r)}=\frac{q_{it}^{(r)}}{q_{i,t-1}^{(r)}}.
$$

Процентное изменение компонента — $100(u_{it}^{(r)}-1)$, а логарифмическое —
$\log u_{it}^{(r)}$. Для донора при переносе $\alpha$:

$$
u_{dt}=1-\frac{\alpha}{q_{d,t-1}}.
$$

Например, одинаковые $\alpha=0.04$ CPU дают:

| CPU донора до / после | $u_d$ | Потеря относительно начального выделения | Изменение доли при $B=3.4$ CPU |
| --- | ---: | ---: | ---: |
| .35 / .31 | .885714 | 11.43% | $-.04/3.4$ |
| .25 / .21 | .84 | 16.00% | $-.04/3.4$ |
| .15 / .11 | .733333 | 26.67% | $-.04/3.4$ |

Последний столбец — в долях единицы: $-.0117647$, то есть **минус 1.17647
процентного пункта**, не одинаковая процентная потеря самого донора.

Композиционное относительное возмущение положительным вектором $u$:

$$
x'=\mathcal C(x\odot u),
$$

где $\odot$ — покомпонентное умножение. Общий множитель всех $u_i$ не меняет
результат: $u$ и $c u$ при $c>0$ задают одно относительное возмущение.

**«Одинаковое относительное перераспределение»** означает одинаковые изменения
всех попарных отношений, то есть одинаковый $u$ с точностью до общего
множителя. Это не то же самое, что одинаковый абсолютный перенос $\alpha$.

Если один и тот же $u$ применить к разным начальным $x$, последующее замыкание
может изменить все абсолютные выделения. Эти полученные состояния нельзя
считать выполненными runtime-переносами, если они отдельно не запускались.

### 6. Попарные и выбранные локальные отношения: $R_{ik,t}$, $b_t$

Попарное отношение двух компонентов **одного ресурса**:

$$
R_{ik,t}^{(r)}=\frac{x_{it}^{(r)}}{x_{kt}^{(r)}}
=\frac{q_{it}^{(r)}}{q_{kt}^{(r)}}.
$$

Оно показывает выделение $i$ относительно выделения $k$. Общий бюджет из
отношения сокращается. Не всякое отношение двух метрик является таким
композиционным отношением: CPU/RAM имеет разные физические единицы.

Выполненный дизайн выбрал три локальные координаты:

$$
b_t=\frac{1}{\sqrt2}\begin{pmatrix}
\log(x_{\mathrm{checkout},t}^{(\mathrm{CPU})}/x_{\mathrm{payment},t}^{(\mathrm{CPU})})\\
\log(x_{\mathrm{frontend},t}^{(\mathrm{CPU})}/x_{\mathrm{ad},t}^{(\mathrm{CPU})})\\
\log(x_{\mathrm{accounting},t}^{(\mathrm{RAM})}/x_{\mathrm{kafka},t}^{(\mathrm{RAM})})
\end{pmatrix}\in\mathbb R^3.
$$

**«Выбранные локальные отношения» в наших результатах — именно $b_t$.**
Это три заранее заданные проекции, не все отношения системы и не
универсальный стандарт мониторинга. Слово «локальные» означает ограниченный
выбор компонентов; оно не означает отсутствие логарифмов или отсутствие CoDA.
Каждая из этих координат сама является простейшим CoDA-балансом.

Изменения и накопленные изменения этих координат:

$$
\Delta b_t=b_t-b_{t-1},\qquad D_t^b=b_t-b_0.
$$

По одному только $b_t$ нельзя восстановить произвольное распределение 11
компонентов CPU и 11 компонентов RAM. Отдельный алерт на CPU-лимит одного
компонента, на его долю и на отношение двух компонентов — также три разных
правила; они не называются здесь одним словом «порог».

### 7. Баланс групп и отношение сумм: $\beta_{\mathcal G,\mathcal K}$, $A_{\mathcal G,\mathcal K}$

Для непересекающихся непустых групп компонентов одного ресурса
$\mathcal G,\mathcal K$ обозначим их геометрические средние:

$$
g_{\mathcal G}(x)=\left(\prod_{i\in\mathcal G}x_i\right)^{1/|\mathcal G|}.
$$

Ортонормированно масштабированный **CoDA-баланс** между группами:

$$
\beta_{\mathcal G,\mathcal K}(x)=
\sqrt{\frac{|\mathcal G||\mathcal K|}{|\mathcal G|+|\mathcal K|}}
\log\frac{g_{\mathcal G}(x)}{g_{\mathcal K}(x)}.
$$

Для двух одиночных компонентов это $\log(x_i/x_k)/\sqrt2$, как в $b_t$.
Один баланс — одна скалярная проекция распределения, не полное распределение.

Другая возможная характеристика — **отношение суммарных долей групп**:

$$
A_{\mathcal G,\mathcal K}(x)=
\frac{\sum_{i\in\mathcal G}x_i}{\sum_{k\in\mathcal K}x_k}.
$$

В общем случае $A_{\mathcal G,\mathcal K}$ не совпадает с балансом через
геометрические средние. Для одиночных групп оба используют одно попарное
отношение, а balance дополнительно логарифмирует и масштабирует его.
Скалярное отношение групп тоже может терять распределение внутри групп.
Здесь такая формула определяется как возможный comparator; её наличие в
математике не означает, что именно такой алерт является общей практикой.

### 8. Полные ILR-координаты состояния: $z_t^{(r)}$, $z_t$

Для каждого ресурса выбирается фиксированная матрица
$H\in\mathbb R^{(D-1)\times D}$ с ортонормированными строками, ортогональными
вектору единиц:

$$
HH^\mathsf T=I_{D-1},\qquad H\mathbf1=0.
$$

Полные ILR-координаты:

$$
z_t^{(r)}=H\log x_t^{(r)}\in\mathbb R^{D-1},\qquad
z_t=\begin{pmatrix}z_t^{(\mathrm{CPU})}\\z_t^{(\mathrm{RAM})}\end{pmatrix}
\in\mathbb R^{20}.
$$

Логарифм берётся покомпонентно. В реализации используется Helmert-базис
в зафиксированном порядке компонентов:

$$
z_{kt}^{(r)}=
\frac{\sum_{i=1}^{k}\log x_{it}^{(r)}-k\log x_{k+1,t}^{(r)}}{\sqrt{k(k+1)}},
\qquad k=1,\ldots,D-1.
$$

Обратное преобразование:

$$
x_t^{(r)}=\mathcal C\!\left(\exp(H^\mathsf Tz_t^{(r)})\right).
$$

Следовательно, **$X_t$ и $z_t$ — два взаимно однозначных представления одного
выбранного относительного состояния**, не два разных набора измерений.
$v_t$ хранит его в 22 долях с двумя ограничениями; $z_t$ — в 20 свободных
координатах. Абсолютные бюджеты хранятся отдельно. Достаточно $(B_t,z_t)$,
чтобы восстановить все выбранные лимиты, но не внутреннее состояние системы.

Один баланс не равен полному ILR-вектору. Полный базис включает $D-1$
независимых ортонормированных log-contrasts на ресурс. Числа отдельных
координат зависят от базиса; полные Aitchison-расстояния — нет. Это установленные
свойства ILR, не новая теорема выполненного PoC.
[Egozcue et al., Isometric Logratio Transformations for Compositional Data Analysis](https://doi.org/10.1023/A:1023818214614).

Для трёх конкретных выбранных координат существует матрица
$P\in\mathbb R^{3\times20}$:

$$
b_t=Pz_t,\qquad PP^\mathsf T=I_3.
$$

Иными словами, $b_t$ — ортонормированная трёхмерная проекция полного
20-мерного состояния. Это утверждение относится к конкретным трём
неперекрывающимся контрастам дизайна; произвольные выбранные отношения не
обязаны быть ортонормированными.

### 9. Изменение за шаг и накопленный дрейф: $\Delta z_t$, $D_t^z$

**Полное относительное изменение за шаг**:

$$
\Delta z_t=z_t-z_{t-1}.
$$

Изменение каждой пары компонентов выражается через отношения множителей:

$$
\log R_{ik,t}^{(r)}-\log R_{ik,t-1}^{(r)}
=\log(u_{it}^{(r)}/u_{kt}^{(r)}).
$$

Для произвольного положительного $u$ и $x'=\mathcal C(x\odot u)$:

$$
\operatorname{ilr}(x')-\operatorname{ilr}(x)
=H\log u=\operatorname{ilr}(\mathcal C(u)).
$$

Поэтому одинаковое относительное возмущение даёт одинаковый полный ILR-вектор
изменения при разных начальных композициях. Утверждение касается отношений,
не равенства SLO-исходов и не равенства абсолютных переносов.

**Накопленный относительный дрейф от baseline**:

$$
D_t^z=z_t-z_0=\sum_{s=1}^{t}\Delta z_s.
$$

Аналогичные, но отличные по смыслу величины:

$$
D_t^v=v_t-v_0=\sum_{s=1}^{t}\Delta v_s,\qquad
D_t^b=b_t-b_0=P D_t^z.
$$

$D_t^v$ — накопленное аддитивное изменение долей; $D_t^z$ — накопленное
относительное изменение; $D_t^b$ — его выбранная проекция. Они не обозначаются
одним неопределённым словом «изменение».

По одному $D_t^z$ нельзя восстановить текущее распределение без $z_0$.
Полное состояние $z_t$ и полный вектор изменения $D_t^z$ — разные объекты.
Потенциальная связь с исходом также требует начального состояния и контекста.

**История адаптации** — упорядоченная последовательность, а не один endpoint:

$$
\mathcal H_{j\pi}(t)=\big((\tau_s,q_s,X_s,z_s,b_s,A_s,y_s,V_s)\big)_{s=0}^{t}.
$$

Здесь $\tau_s$ — реальные границы окна; $A_s$ — команда адаптации,
$y_s$ — измеренные исходы, $V_s$ — техническая валидность. Их определения ниже.
Если система вернулась к baseline, $D_t^z=0$, но предыдущая история могла
содержать существенные изменения и нарушения. Нулевое net displacement их
не отменяет.

### 10. Метрики, направление и длина пути: $d_E$, $d_A$, $L_t$

Евклидово расстояние между векторами долей:

$$
d_E(X,X')=\|v-v'\|_2.
$$

Оно измеряет аддитивные различия долей. Вычисление этого расстояния по
композиционным данным не превращает его в Aitchison-расстояние.

Aitchison-расстояние для одного ресурса:

$$
d_A(x,x')=\|\operatorname{ilr}(x)-\operatorname{ilr}(x')\|_2,
$$

или через все попарные отношения:

$$
d_A(x,x')^2=\frac1D\sum_{i<k}
\left(\log\frac{x_i/x_k}{x'_i/x'_k}\right)^2.
$$

В совместном пространстве двух ресурсов:

$$
d_{\mathrm{rel}}(X,X')^2=
\omega_{\mathrm{CPU}}d_A(x^{(\mathrm{CPU})},x'^{(\mathrm{CPU})})^2+
\omega_{\mathrm{RAM}}d_A(x^{(\mathrm{RAM})},x'^{(\mathrm{RAM})})^2.
$$

В реализованных вычислениях $\omega_{\mathrm{CPU}}=\omega_{\mathrm{RAM}}=1$, поэтому
$d_{\mathrm{rel}}(X,X')=\|z-z'\|_2$. Веса — явно заданная конвенция сравнения
ресурсов, не оценённые веса риска.

**Величина накопленного относительного движения**:

$$
N_t=\|D_t^z\|_2.
$$

**Направление** — $D_t^z/N_t$ при $N_t>0$. Одна норма $N_t$ не сохраняет
направление. Назвать направление «рискованным» можно лишь после связи с
измеренными требованиями в соответствующем контексте; такого значения у
координат или метрики автоматически нет.

**Длина пути по измеренным вершинам**:

$$
L_t^{\mathrm{obs}}=\sum_{s=1}^{t}\|\Delta z_s\|_2\geq N_t.
$$

$N_t$ измеряет net displacement, $L_t^{\mathrm{obs}}$ — пройденный дискретный
путь. Ни одна из величин не является вероятностью нарушения.
Численные масштабы $d_E$ и $d_A$ различны; вывод «одна геометрия лучше» нельзя
получить простым сравнением величин двух норм.

### 11. Потеря информации в выбранной проекции: $\eta_t$

Для ненулевого накопленного движения и конкретного ортонормированного $P$:

$$
\eta_t=1-\frac{\|D_t^b\|_2^2}{\|D_t^z\|_2^2}
=\frac{\|(I_{20}-P^\mathsf TP)D_t^z\|_2^2}{\|D_t^z\|_2^2}.
$$

$\eta_t\in[0,1]$ — доля квадрата длины накопленного относительного движения
вне выбранных трёх координат. При $D_t^z=0$ она не определена и не заменяется
нулём. Для произвольных неортонормированных отношений эта формула напрямую
неприменима.

В сохранённом анализе медиана **внутри каждой adaptive-истории**, затем медиана
этих 24 медиан, равна .7811. Это не 78.1% пропущенных нарушений. Старое .8870
вычислено для отдельных соседних изменений $\Delta z_t$, а не для $D_t^z$.

**Совпадение выбранных endpoints** двух историй:

$$
b_{jt}=b_{ks},\qquad z_{jt}\ne z_{ks}.
$$

**Совпадение всего выбранного префикса** при одинаковом baseline и контексте:

$$
b_{js}=b_{ks}\quad\text{для всех }s=0,\ldots,t,
\qquad z_{jt}\ne z_{kt}.
$$

Если одновременно наблюдаются разные SLO-labels, это свидетельство, что
выбранная проекция не различает эти полные allocation histories и наблюдаемые
исходы. Оно не доказывает, что отличие распределения вызвало отличие исхода.
Численная проверка совпадения в реализации использует допуск $10^{-10}$.

### 12. Команда адаптации, измеренное состояние и откат: $A_t$, $q_t^-$, $q_t^+$

Обычная команда переноса:

$$
A_t=(r,d,b,\alpha),\qquad
q_t^{\mathrm{trial},(r)}=q_t^{-,(r)}+\alpha(e_b-e_d).
$$

$q_t^-$ — состояние перед этой командой; $q_t^{\mathrm{trial}}$ — проверяемое
состояние, в котором измерен $y_t$. В данной записи $q_t=q_t^{\mathrm{trial}}$.

После проверки применяется состояние:

$$
q_t^+=\begin{cases}
q_t^{\mathrm{trial}},&\text{если trial оставлен;}\\
q_t^-,&\text{если выполнен rollback.}
\end{cases}
$$

Удержание allocation и восстановление всей baseline allocation — отдельные
виды команд, не перенос $\alpha$ между двумя компонентами.

Из-за rollback или восстановления $q_t^-$ может не совпадать с предыдущим
**измеренным** $q_{t-1}$. Поэтому $\Delta q_t=q_t-q_{t-1}$ в таблице соседних
окон не обязательно равно одной команде переноса.

Command-vertex path учитывает дополнительные вершины $q_t^-$,
$q_t^{\mathrm{trial}}$, $q_t^+$ и восстановления. Это не запись непрерывной
траектории промежуточных kernel updates. Если $q_t^+$ отличается от измеренного
trial и следующего окна нет, ему не присваивается выдуманный post-rollback
SLO-label. Таких конечных случаев в кампании два.

### 13. Измеренные исходы, допустимость и запас: $y_t$, $S_t$, $m_t$, $h_t$

Измеренный вектор эксплуатационных исходов:

$$
y_t=(\ell_{95,t},\varepsilon_t,\rho_{\mathrm{ad},t},\rho_{\mathrm{acct},t},G_t).
$$

| Величина | Определение | Единицы / требование |
| --- | --- | --- |
| $\ell_{95,t}$ | p95 длительности checkout-запросов | ms; не более 500 |
| $\varepsilon_t$ | Доля неуспешных запланированных checkout-операций | Доля; строго меньше .01 |
| $\rho_{\mathrm{ad},t}$ | Доля рекламных попыток с непустым ответом за не более 200 ms | Доля; не менее .99 |
| $\rho_{\mathrm{acct},t}$ | Доля подтверждённых заказов с commit за не более 5000 ms | Доля; не менее .99 |
| $G_t$ | Успешные непустые рекламные ответы внутри окна / длительность окна | responses/s; полезный выход, не отдельный SLO |

Checkout-операция планируется arrival-rate генератором. При $\lambda$
операциях/s за $T_t$ секунд знаменатель равен $N_{\mathrm{sched}}=\lambda T_t$.
Неуспешные завершённые, не запущенные и не завершившиеся операции остаются
в error fraction. p95 относится к checkout-запросам, не к длительности всей
cart-plus-checkout операции. Для accounting знаменатель — все подтверждённые
заказы; отсутствующие commits не исчезают из него.

При наличии необходимых измерений общий SLO-label:

$$
S_t=I[
\ell_{95,t}\le500
\land\varepsilon_t<.01
\land\rho_{\mathrm{ad},t}\ge.99
\land\rho_{\mathrm{acct},t}\ge.99].
$$

**$S_t$ вычисляется из измеренных исходов, не из $x_t$, $z_t$ или расстояния.**
Restart/OOM — диагностика, не самостоятельная замена этого label. Потеря
первичных данных, не позволяющая восстановить исход, отделяется как
инфраструктурная невалидность. Известный неуспешный запрос не является
просто «пропущенными данными».

Физические запасы до требований:

$$
m_t=
\begin{pmatrix}
500-\ell_{95,t}\\
.01-\varepsilon_t\\
\rho_{\mathrm{ad},t}-.99\\
\rho_{\mathrm{acct},t}-.99
\end{pmatrix}.
$$

Первая координата — ms, остальные — доли. Для процентных пунктов последние
умножаются на 100. Нулевая граница допустима для p95 и timely fractions,
но не для checkout error fraction. Несовместимые единицы не складываются
в общий «запас системы», а рост $G_t$ не компенсирует нарушение другого
требования.

Нормированный engineering headroom контроллера обозначается отдельно:

$$
h_{\mathrm{checkout},t}=
\min\left(1-\frac{\ell_{95,t}}{500},\
1-\frac{\varepsilon_t}{.01}\right).
$$

Для рекламы и accounting:

$$
h_{c,t}=
\min\left(
\frac{\rho_{c,t}-.99}{1-.99},\
1-\frac{\ell_{99,c,t}}{d_c}
\right),\qquad
c\in\{\mathrm{ad},\mathrm{acct}\},
$$

где $d_{\mathrm{ad}}=200$ ms, $d_{\mathrm{acct}}=5000$ ms. В accounting
$\ell_{99,\mathrm{acct},t}$ — p99 задержек **наблюдённых commits**, то есть
условная диагностическая величина. Отсутствующие commits учитываются через
$\rho_{\mathrm{acct},t}$. Поэтому $h_t$ не переопределяет SLO-membership.

Техническая валидность окна обозначается $V_t$. Она хранится отдельно
от $S_t$ и не выводится из геометрии.

**Граница допустимости** — условия на $y_t$ в формуле $S_t$, а не заранее
известная поверхность в пространстве $X_t$ или $z_t$. Для связи распределения
с исходом важны $W_t$ и внутреннее состояние системы. Allocation-вектор
не объявляется достаточным предиктором.

В этой кампании менялся CPU. RAM различалась между начальными контекстами,
но оставалась постоянной внутри истории: $\Delta z_t^{(\mathrm{RAM})}=0$.
Полное 20-мерное описание состояния не означает двадцать исследованных
направлений движения.

### 14. Три описания перехода и дополнительный поиск аналогов: $f_t^m$

В дополнительном анализе сравнивались **описания переходов**, не новые
runtime-политики:

| Метод | Признаки перехода | Размер | Что сохраняется в описании |
| --- | --- | ---: | --- |
| Выбранные log-ratios | $f_t^{\mathrm{sel}}=\Delta b_t$ | 3 | Изменение выбранных трёх координат |
| Все аддитивные изменения долей | $f_t^{\mathrm{shares}}=\Delta v_t$ | 22 | Изменение доли каждого компонента |
| Все относительные изменения | $f_t^{\mathrm{ILR}}=\Delta z_t$ | 20 | Полное относительное изменение |

**Информационная эквивалентность $v_t$ и $z_t$ относится к состояниям,
не к разностям $\Delta v_t$ и $\Delta z_t$ без начальных состояний.**
Одинаковое $\Delta v_t$ при разных стартах может дать разные $\Delta z_t$,
как в примерах одинаковых абсолютных переносов. Оба descriptors вычислены
из тех же пар allocations и учитывают все компоненты, но по-разному
сжимают эти пары. Это не просто две линейно заменяемые системы координат
одного вектора изменений.

Для двух переходов $t,s$ расстояние в методе $m$:

$$
d_m(t,s)=\|f_t^m-f_s^m\|_2.
$$

Это **расстояние между описаниями переходов**, не расстояние текущего
allocation до baseline и не запас до SLO-границы.

Цель прогнозирования:

$$
\Delta h_t=h_t-h_{t-1}.
$$

Ближайшие аналоги выбираются вне всей query runner-пары, при совпадении
workload profile и длительностей обоих окон перехода. Все ближайшие
равноудалённые аналоги в допуске $10^{-10}$ усредняются сначала внутри
соседней пары, затем равновесно между соседними парами.

Для метода $m$ aggregate error:

$$
E_m=\frac1{|\mathcal J|}
\sum_{j\in\mathcal J}\frac1{|\mathcal E_j|}
\sum_{e\in\mathcal E_j}\frac13
\sum_{c\in\{\mathrm{checkout},\mathrm{ad},\mathrm{acct}\}}
|\Delta h_{c,e}-\widehat{\Delta h}_{c,e}^{\,m}|,
$$

где $\mathcal E_j$ — eligible query transitions пары $j$, а $\mathcal J$ —
пары с такими transitions. Для данных с определёнными headrooms retained
targets составляют 476 nonzero adjacent reallocations и 24 query pairs.

Обсуждаемые .4312, .3860 и .4120 — значения $E_m$ для трёх методов,
а не геометрические расстояния, missed-alert rates или ошибки восстановления
allocation. Отдельная retrospective диагностика
$\widehat{\Delta h}=0$ дала .2691; она не является новым выполненным
online-детектором.

Сравнение не включает полное начальное состояние или всю историю в признаки.
Кроме того, число усредняемых ближайших runner-пар различается между
методами. Поэтому оно не изолирует исключительно влияние метрики и не
устанавливает качество предупреждения до нарушения.

Источник реализации: [state representation и контроллер](probe7/scripts/model.py),
[измерения](probe7/scripts/measurements.py),
[поиск аналогов](probe7/scripts/analyze.py),
[накопленный анализ](probe7/scripts/analyze_accumulated.py).
Данные: [фактические переносы](probe7/results/accumulated-v0.1.0/actual-transfer-examples.csv),
[все накопленные окна](probe7/results/accumulated-v0.1.0/history-windows.csv),
[сравнения префиксов](probe7/results/accumulated-v0.1.0/prefix-witnesses.csv),
[дополнительные ошибки](probe7/results/accumulated-v0.1.0/secondary-diagnostics.csv).

### 15. Отдельная проверка предупреждений: $w_t$, $Y_t^{(K)}$

Этот подраздел определяет отдельную задачу, реализованную в Probe 8 и
проверенную на двадцати новых runner-парах. Она не меняет результаты прежней
кампании. [Зафиксированное правило и development](probe8/README.md)
отделены от [независимых результатов](probe8/results/confirmation-v0.1.0/README.md).

Пусть $K$ — выбранный до проверки горизонт в циклах; матрица ILR-базиса $H$
обозначена отдельно выше. Для текущего safe-окна
цель предупреждения под фиксированной политикой адаптации:

$$
Y_t^{(K)}=
I[\exists k\in\{1,\ldots,K\}:S_{t+k}=0].
$$

Обозначим $\mathcal F_t$ информацию, реально доступную к моменту решения:
начальное состояние, историю, текущие уже завершённые измерения и контекст.
Будущие outcomes и позже поступившие сведения в неё не входят.

В реализованном правиле:

$$
w_t=I[g(\mathcal F_t)\ge\theta],\qquad S_t=1,
$$

В Probe 8 $K=2$ выбран до расчёта development scores. $g$ — средняя метка
будущего нарушения среди ближайших пяти old runner-пар при совпадении
workload и epoch. Для каждой пары сначала усредняются ближайшие tied prefixes;
ties на границе пятой пары также включаются. Это score, не откалиброванная
вероятность. Представления сравниваются на всей последовательности состояний
до $t$, с одинаковыми текущими сервисными показателями. Пороги каждого метода
зафиксированы в [модели](probe8/frozen-model-v0.1.0.json). Решения на шагах 19 и
20 исключены из задачи двухциклового предупреждения; эти окна всё равно
измеряются для проверки предыдущих сигналов и выявления нарушений.

Разработка на изученной кампании и подтверждение на новых runner-парах
разделяются. Зависимые окна одной пары не распределяются между development
и test как независимые примеры. Разделение обучения, настройки и проверки
описано в [scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html).

Если до конца горизонта нет наблюдений и нарушения ещё не было,
$Y_t^{(K)}$ остаётся неизвестным, а не превращается в 0. Lead time нужно
считать по реальным timestamps доступности сигнала и измерения нарушения,
не только по номерам циклов.

Ложный сигнал имеет $w_t=1$ и $Y_t^{(K)}=0$: все следующие $K$ окон валидны
и безопасны. Верный сигнал имеет $w_t=1$ и $Y_t^{(K)}=1$. Если штатный
контроллер отменил сокращение и будущие измерения безопасны, сигнал всё равно
ложный для прогноза фактического нарушения при этой политике. Риск без такого
отката не устанавливается. Число ложных решений $FP$ не равно числу независимых
историй; $FP/N_{Y=0}$ и precision $TP/(TP+FP)$ имеют разные знаменатели.

При оценке нужны обнаруженные и пропущенные нарушения, ложные сигналы,
lead time и явно определённая единица подсчёта. Совместное рассмотрение
precision, recall и времени оповещения обсуждается в
[Google SRE](https://sre.google/workbook/alerting-on-slos/); обнаружение уже
произошедшего нарушения не равно раннему предупреждению.

Для первого observer-only теста сигналы не должны менять controller policy:
иначе предупреждение может предотвратить событие, и отсутствие нарушения
нельзя автоматически считать ложным сигналом. Этот тест оценивает риск
при данной guarded-политике, не контрфактический риск без её откатов.

Для сравнения геометрий CoDA-способ и евклидова геометрия долей должны получать
одинаковые распределения и контекст. Отдельный сервисный способ проверяет,
что добавляет история распределения к сервисным показателям. Нужны сопоставимые
правила настройки и учёт числа ложных сигналов. Качество конкретного правила
не означает универсального превосходства одной обратимой системы координат
над другой.

Предыдущие измерения устанавливают representational witnesses и относительную
геометрию. Отдельный Probe 8 уже показал реальные ранние сигналы: 5/6 первых
нарушений предупреждены ILR-правилом примерно за 52 s. Но было 45 ложных
сигналов при 5 верных, precision 10%; практическое превосходство и польза
действий по предупреждению не установлены. Евклидова геометрия долей предупредила 4/6 при
38 ложных решениях. [Упрощённые пояснения](probe8/interpretation-v0.1.0.md)
разделяют эти выводы и роли сравнений.


## License

Artifact code is released under the [MIT License](LICENSE). Upstream
OpenTelemetry Demo retains its own license.
