# Procedure de passage paper -> demo -> reel

Chaque phase a des criteres d'entree ET de sortie chiffres. On ne saute
jamais une phase, on peut toujours retrograder.

## Phase 0 - Recherche (etat actuel)

Sortie autorisee si le protocole de validation BACKTEST.md est entierement
verifie (walk-forward, Monte Carlo, stress tests, stabilite des parametres).

## Phase 1 - Paper trading (3 a 6 mois minimum)

- Broker: `paper` (defaut). Scan + signaux + execution simulee quotidiens.
- Criteres de sortie (TOUS requis):
  1. >= 60 trades clotures;
  2. correlation > 0.8 entre performance papier et performance backtestee
     sur la meme periode (sinon: bug d'implementation ou regime hostile);
  3. slippage simule vs prix reels d'ouverture < 10 bps d'ecart moyen;
  4. zero intervention manuelle non documentee;
  5. drawdown papier reste sous la limite config (15%).

## Phase 2 - Compte demo broker (2 a 3 mois)

- Alpaca paper (ALPACA_PAPER=true) ou IBKR port 7497.
- Implementer le connecteur (stubs fournis), puis verifier:
  1. reconciliation quotidienne positions broker == table positions (zero ecart);
  2. tous les ordres ont un statut terminal en < 1 jour (pas d'orphelins);
  3. comportement correct sur demi-seance, jour ferie, ticker suspendu;
  4. kill switch teste: couper l'API broker en pleine session, verifier
     que le systeme s'arrete proprement et alerte.

## Phase 3 - Reel progressif

- Pre-requis: `LIVE_TRADING_ACK=I_UNDERSTAND_THE_RISKS` dans l'environnement
  de la SEULE machine d'execution.
- Montee en charge: 10% du capital cible pendant 1 mois -> 25% -> 50% -> 100%,
  chaque palier exige un mois sans incident technique.
- Regles d'arret immediat (retour Phase 2):
  - drawdown reel > limite config,
  - ecart de reconciliation non explique,
  - 2 incidents techniques sur un mois.

## Auto-amelioration en production

- Phase 1-2: `propose_weight_update()` genere des propositions; un humain
  les examine, exige un walk-forward de confirmation, puis edite config.yaml.
- Phase 3 (autonomie totale): l'application automatique n'est activee que si
  6 propositions consecutives validees a la main auraient ete acceptees
  telles quelles. Meme alors: bornes dures (chaque poids dans [50%, 150%] de
  sa valeur courante, somme = 1, journalisation complete, rollback en 1 clic).
