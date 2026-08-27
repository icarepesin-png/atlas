# Feuille de route ATLAS

Etat au 2026-08-27, apres l'audit complet du 26 aout (voir docs/BACKTEST.md).

## Ou on en est vraiment

| Domaine | Etat |
|---|---|
| Infrastructure | **solide**: 104 tests, verrou d'execution, watchdog cloud, sauvegardes, synchro Neon, rattrapage automatique |
| Gestion du risque | **fonctionne**: selection mauvaise et pourtant -2% seulement, drawdown 8.6% pour un plafond de 15% |
| Comptabilite | **exacte**: capital + realise + latent = equity au centime |
| Selection des titres | **ne fonctionne pas**: le score achete des titres qui baissent (top 5% a -1.42% contre +2.67% pour l'univers) |
| Validation | **absente**: le backtest de reference teste une autre strategie que celle qui tourne |

La priorite n'est pas d'ajouter des fonctionnalites. C'est de savoir si ce
systeme a un avantage, et d'arreter d'empiler des couches par-dessus une
question sans reponse.

---

## Phase 0 - Rendre le systeme coherent (cette semaine, rien a payer)

### 0.1 Neutraliser le pilier technique

- **Quoi**: `config/config.yaml`, poids `technical: 0.25 -> 0`, redistribue en
  `fundamental: 0.55` et `sector: 0.20`. ET `min_technical_score: 80 -> 0`,
  sans quoi le filtre continue d'exiger des titres en tendance forte et le
  changement de poids ne sert a rien.
- **Pourquoi**: IC de -0.008 sur 2010-2026 (841 mesures, 534 titres). Le signal
  n'est pas inverse, il n'a jamais rien predit. Mesure faite sur 15 ans, pas
  sur un trimestre.
- **Succes**: IC du composite superieur a 0 et top 5% au-dessus de l'univers
  sur les 4 semaines suivantes (`scripts/pouvoir_predictif.py`).
- **Effort**: 10 minutes. **Bloque par**: decision utilisateur.

### 0.2 Delai de carence apres une sortie sur stop

- **Quoi**: interdire de racheter un titre pendant N seances (proposition: 20)
  apres une sortie perdante. `atlas/pipelines/paper_trade.py`, section entrees.
- **Pourquoi**: 8 titres re-trades pesent -3 921 USD, soit 72% de la perte
  totale. WDC traite 5 fois, EOG 4 fois, SNDK et STX 3 fois.
- **Succes**: aucun rachat dans les 20 seances suivant une sortie sur stop.
- **Effort**: 1 heure avec tests. **Bloque par**: 0.1 - ne pas changer deux
  choses a la fois, sinon on ne sait plus laquelle a produit quel effet.

### 0.3 Traiter les piliers qui ne discriminent rien

- **Quoi**: `macro` (poids 0.15) vaut 80 pour TOUS les titres et `sentiment`
  (0.10) vaut 50 pour tous. 25% du score ne participe donc pas au classement,
  il ne fait que diluer les piliers qui, eux, discriminent.
- **Options**: soit sortir macro du score et le laisser jouer son vrai role
  (modulateur d'exposition globale, ce qu'il fait deja via
  `exposure_modifier`), soit le rendre transversal (sensibilite au regime,
  titre par titre).
- **Succes**: 100% du poids du score porte sur des piliers qui varient d'un
  titre a l'autre.
- **Effort**: 2 a 4 heures.

---

## Phase 1 - Mesurer honnetement (4 a 6 semaines)

### 1.1 Backtest fidele a la strategie reelle

- **Quoi**: un moteur qui simule ce qui tourne vraiment: entree sur signal,
  sizing par risque, stop 2 ATR, trailing 2.75 ATR, prise partielle a 1.5R,
  plafonds secteur et pays. Aujourd'hui `atlas/backtest/engine.py` simule 20
  titres equiponderes rebalances mensuellement, sans aucun stop.
- **Pourquoi**: c'est l'angle mort qui a permis de croire le systeme valide
  pendant deux mois et demi. Tant qu'il existe, aucun chiffre de backtest
  n'est utilisable pour decider quoi que ce soit.
- **Succes**: rejouer 2010-2026 et retrouver, sur juin-aout 2026, un resultat
  proche du paper reel (-2%). Un backtest qui ne reproduit pas le passe connu
  ne vaut rien pour predire le futur.
- **Effort**: 1 a 2 jours. **C'est le chantier le plus important de la phase.**

### 1.2 Surveillance des facteurs visible

- **Quoi**: afficher `factor_performance` dans le dashboard (IC par pilier,
  courbe glissante) et alerter par Telegram si l'IC d'un pilier actif passe
  sous -0.05 sur 4 semaines.
- **Pourquoi**: la mesure tourne desormais chaque nuit
  (`atlas/pipelines/suivi_facteurs.py`) mais personne ne la regarde.
- **Succes**: une degradation de signal se voit dans la semaine, pas au bout
  de trois mois.
- **Effort**: 3 a 4 heures.

### 1.3 Bilan a 60 trades clotures

- **Quoi**: refaire tourner `scripts/pouvoir_predictif.py`,
  `scripts/simuler_regles_sortie.py` et l'analyse des trades, puis comparer
  au present audit.
- **Ou on en est**: 46 trades clotures au 27 aout.
- **Succes**: profit factor superieur a 1.0 et taux de reussite au-dessus de
  40%, ou une explication claire de pourquoi non.

### 1.4 Verifier l'effet de la prise partielle

- **Quoi**: comparer le resultat reel des positions passees par un TP1 a la
  simulation qui annoncait +865 USD et 44% de gagnants.
- **Premiere nuit d'application (26 aout)**: 5 prises, +868 USD encaisses
  (APA +295, CPAY +211, VLO +179, GEN +126, TTE.PA +57).

---

## Phase 2 - Le verrou: des donnees honnetes (decision budget)

C'est le vrai blocage du projet. Il etait deja identifie comme "P2"; l'audit
montre que ce n'est pas une amelioration optionnelle mais le prealable a
toute conclusion.

### 2.1 Fondamentaux point-in-time

- **Probleme**: les fondamentaux Yahoo sont un instantane d'aujourd'hui, pas
  ce qu'on savait a la date de decision. Impossible donc de valider le pilier
  fondamental sur l'historique, alors qu'il porterait 55% du score apres 0.1.
  On remplacerait un facteur mesure inutile par un facteur non mesurable.
- **Options**:
  - **FMP as-reported**: payant (environ 20 a 30 USD/mois), pret a l'emploi,
    API simple. Le plus rapide.
  - **EDGAR**: gratuit et officiel, mais il faut parser les depots XBRL et
    gerer les dates de publication. Plusieurs jours de travail.
  - **Ne rien faire**: possible, mais le pilier fondamental restera alors une
    hypothese non testee, indefiniment.
- **Bloque par**: decision utilisateur. Cela engage de l'argent, donc les
  parents ou Darius.

### 2.2 Constituants historiques des indices

- **Probleme**: l'univers est constitue des membres ACTUELS du S&P 500. Les
  societes sorties de l'indice, souvent apres avoir chute, sont absentes: tout
  backtest est mecaniquement flatte. C'est le biais du survivant.
- **Succes**: un backtest dont l'univers, a chaque date, correspond a ce qui
  etait reellement investissable a cette date.

### 2.3 Premier backtest honnete du score composite

- **Quoi**: 1.1 + 2.1 + 2.2 reunis. C'est seulement la qu'on saura si ce
  systeme a un avantage.

---

## Phase 3 - La decision qui compte

A poser explicitement une fois la phase 2 faite, avec des criteres fixes
D'AVANCE pour ne pas se raconter d'histoires apres coup.

**Le systeme a un avantage si, sur 12 mois glissants:**

- IC du composite superieur a +0.03 de facon stable, pas un mois positif isole;
- le top 5% du score bat l'univers de plus de 1 point a 21 seances;
- profit factor superieur a 1.2 sur au moins 60 trades;
- Sharpe du paper superieur a 0.5;
- et le backtest fidele (1.1) reproduit approximativement le paper.

**Si ces criteres ne sont pas atteints**, la conclusion honnete est que la
selection de titres par score composite ne fonctionne pas a cette echelle de
donnees, et il faut changer d'approche plutot que d'ajouter des couches.
Ecrire cette phrase maintenant, a froid, vaut mieux que d'y penser dans un an.

---

## Phase 4 - Reel progressif, seulement si la phase 3 est verte

- Tous les criteres de docs/GO_LIVE.md verts.
- Depart a 10% du capital prevu, compte tenu par Darius (majeur).
- Reconciliation quotidienne broker contre base
  (`atlas/pipelines/reconcile.py`, deja ecrit, jamais utilise en reel).
- Jamais de levier, jamais de futures.

---

## Dette technique (en parallele, par petits bouts)

| Sujet | Risque | Effort |
|---|---|---|
| `use_container_width` deprecie par Streamlit, retrait annonce apres le 2025-12-31 | **le dashboard cloud peut casser du jour au lendemain**; migrer vers `width="stretch"` | 30 min |
| `actions/checkout@v4` et `setup-python@v5` sur Node 20 deprecie | avertissement aujourd'hui, panne du workflow a terme | 15 min |
| Rate limiting Yahoo sur les fondamentaux | des centaines de "Too Many Requests" par run: une partie de l'univers a des scores fondamentaux degrades | 2 h |
| App Streamlit publique | n'importe qui avec l'URL voit le portefeuille; passer en prive (allowlist Icare et Darius) | 15 min |
| `docs/ATLAS_Documentation.pdf` anterieur a l'audit | la documentation affirme des choses fausses, dont un backtest "valide" | 30 min |

---

## Ce qu'on ne fait PAS pour l'instant

- **Migrer le cerveau dans le cloud**: ecarte le 2026-08-01, rien n'a change
  depuis (moteur SQLite, runners ephemeres, Yahoo bloque les IP cloud).
- **ML, multi-strategies, univers a 10 000 titres**: tout cela suppose une
  base qui fonctionne. Ajouter de la complexite sur une selection non validee
  ne ferait que rendre l'echec plus difficile a diagnostiquer.
- **Toucher aux stops et au trailing**: mesure faite sur les 59 entrees
  reelles, aucune des neuf regles de sortie testees ne rend la strategie
  profitable. Le probleme est ailleurs.

La feuille de route ambitieuse d'avant l'audit est conservee dans
docs/ROADMAP_avant_audit.md. Elle reste valable, mais seulement apres la
phase 3.
