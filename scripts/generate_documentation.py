# -*- coding: utf-8 -*-
"""Genere la documentation complete du projet ATLAS en PDF.

Usage: python scripts/generate_documentation.py
Sortie: docs/ATLAS_Documentation.pdf
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

OUT = Path(__file__).resolve().parents[1] / "docs" / "ATLAS_Documentation.pdf"

# ----------------------------------------------------------------- styles ---

ss = getSampleStyleSheet()
BLUE = colors.HexColor("#1a3a5c")
GRAY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef2f6")

S_TITLE = ParagraphStyle("DocTitle", parent=ss["Title"], fontSize=30,
                         textColor=BLUE, spaceAfter=6)
S_SUB = ParagraphStyle("DocSub", parent=ss["Normal"], fontSize=13,
                       textColor=GRAY, alignment=1, spaceAfter=4)
S_H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, textColor=BLUE,
                      spaceBefore=18, spaceAfter=8)
S_H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, textColor=BLUE,
                      spaceBefore=12, spaceAfter=5)
S_P = ParagraphStyle("P", parent=ss["Normal"], fontSize=10, leading=14.5,
                     spaceAfter=7, alignment=4)  # justify
S_B = ParagraphStyle("B", parent=S_P, leftIndent=16, bulletIndent=6,
                     spaceAfter=4)
S_NOTE = ParagraphStyle("Note", parent=S_P, backColor=LIGHT, borderPadding=8,
                        leftIndent=6, rightIndent=6, spaceBefore=4,
                        spaceAfter=10)
S_CODE = ParagraphStyle("Code", parent=S_P, fontName="Courier", fontSize=8.5,
                        backColor=LIGHT, borderPadding=8, leftIndent=6,
                        rightIndent=6, leading=12)

TBL_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4d0")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
])


def T(data, widths=None):
    cell = ParagraphStyle("cell", parent=S_P, fontSize=9, leading=11.5,
                          spaceAfter=0, alignment=0)
    head = ParagraphStyle("cellh", parent=cell, textColor=colors.white,
                          fontName="Helvetica-Bold")
    rows = [[Paragraph(str(c), head) for c in data[0]]]
    for r in data[1:]:
        rows.append([Paragraph(str(c), cell) for c in r])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TBL_STYLE)
    return t


# ------------------------------------------------------------ doc template ---

class Doc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            if flowable.style.name == "H1":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
            elif flowable.style.name == "H2":
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(2 * cm, 1.2 * cm, "ATLAS - Documentation technique et audit")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------- content ---

story = []
H1 = lambda t: story.append(Paragraph(t, S_H1))
H2 = lambda t: story.append(Paragraph(t, S_H2))
P = lambda t: story.append(Paragraph(t, S_P))
B = lambda t: story.append(Paragraph(t, S_B, bulletText="•"))
NOTE = lambda t: story.append(Paragraph(t, S_NOTE))
CODE = lambda t: story.append(Paragraph(t, S_CODE))
SP = lambda h=6: story.append(Spacer(1, h))
PB = lambda: story.append(PageBreak())

# ---- page de titre
story.append(Spacer(1, 5 * cm))
story.append(Paragraph("ATLAS", S_TITLE))
story.append(Paragraph("Adaptive Trading and Learning Allocation System", S_SUB))
story.append(Spacer(1, 1 * cm))
story.append(Paragraph("Plateforme quantitative de gestion d'un portefeuille d'actions mondial", S_SUB))
story.append(Spacer(1, 2.5 * cm))
story.append(Paragraph("Documentation complete et audit du systeme", S_SUB))
story.append(Paragraph("Version 0.1.0 - 11 juin 2026", S_SUB))
story.append(Paragraph("Emplacement : C:\\bot trading\\atlas", S_SUB))
PB()

# ---- sommaire
toc = TableOfContents()
toc.levelStyles = [
    ParagraphStyle("toc1", parent=S_P, fontName="Helvetica-Bold", fontSize=11,
                   spaceBefore=6, spaceAfter=2),
    ParagraphStyle("toc2", parent=S_P, fontSize=9.5, leftIndent=18,
                   spaceAfter=1),
]
# Style distinct de H1 pour ne pas s'auto-referencer dans la table des matieres
S_TOC_TITLE = ParagraphStyle("TocTitle", parent=S_H1)
story.append(Paragraph("Sommaire", S_TOC_TITLE))
story.append(toc)
PB()

# =====================================================================
H1("1. Resume executif")
P("ATLAS est un systeme qui analyse chaque soir plusieurs centaines d'actions "
  "mondiales, les note de 0 a 100 selon cinq dimensions (qualite de l'entreprise, "
  "etat du graphique, contexte economique, force du secteur, sentiment), ne "
  "retient que les rares titres excellents partout, et les achete en simulation "
  "avec un plan de trade complet decide a l'avance : prix d'entree, stop de "
  "protection, objectifs de profit, taille de position limitee par le risque.")
P("Le systeme ne predit pas les marches. Il exploite des regularites "
  "statistiques documentees depuis des decennies : les entreprises de qualite "
  "surperforment, les tendances persistent (momentum), les secteurs forts le "
  "restent plusieurs mois, et couper vite les pertes en laissant courir les "
  "gains produit une esperance positive meme avec un taux de reussite moyen.")
P("Etat au 11 juin 2026 : le systeme est entierement operationnel en "
  "<b>paper trading</b> (argent fictif). Il a analyse 554 titres, genere 7 "
  "signaux et construit son premier portefeuille. Une tache automatique "
  "Windows le fait tourner chaque soir de semaine a 23h00. Aucun argent reel "
  "n'est engage et le passage en reel est verrouille par une procedure stricte.")
NOTE("<b>Chiffres cles du jour 0 (11/06/2026)</b> : 556 titres dans l'univers, "
     "554 scores, 7 positions ouvertes (MU, WDC, APA, STX, EOG, NTAP, SNDK), "
     "1 signal refuse par les contraintes de risque (ADI), capital simule "
     "99 984 sur 100 000 de depart, regime macro detecte : expansion.")

H1("2. La philosophie d'investissement")
H2("2.1 Ce que le systeme croit")
B("<b>On ne predit pas, on selectionne.</b> Personne ne sait ou sera le marche "
  "dans six mois. En revanche, on sait qu'un portefeuille d'entreprises tres "
  "rentables, en tendance haussiere, dans des secteurs porteurs, avec des "
  "pertes coupees mecaniquement, a historiquement une esperance positive.")
B("<b>La selectivite est la strategie.</b> Sur 554 titres analyses, 7 signaux. "
  "Le systeme prefere ne rien faire que faire un trade mediocre : chaque "
  "position doit etre excellente sur toutes les dimensions a la fois.")
B("<b>Le risque se decide avant le trade.</b> Chaque position connait sa perte "
  "maximale avant d'exister : 0,75 % du capital. Dix pertes consecutives "
  "coutent environ 7 % du compte, jamais la ruine.")
B("<b>Tout doit etre mesurable, explicable, reversible.</b> Chaque decision "
  "est journalisee avec les scores qui l'ont produite. Pas de boite noire.")
H2("2.2 Ce que le systeme refuse")
B("Pas d'effet de levier, pas de vente a decouvert en phase 1.")
B("Pas de trading intraday : une decision par jour, apres la cloture.")
B("Pas d'argent reel tant que la phase paper n'a pas prouve, sur 3 a 6 mois "
  "et 60 trades minimum, que le comportement reel correspond au backtest.")
B("Pas de modification automatique de ses propres regles : le module "
  "d'apprentissage propose, un humain valide.")

H1("3. Architecture generale")
H2("3.1 Les briques")
P("Le projet est un package Python 3.11 organise en modules independants. "
  "Chaque brique a une seule responsabilite et peut etre remplacee sans "
  "toucher aux autres :")
story.append(T([
    ["Module", "Role"],
    ["universe/", "Construit la liste des titres a analyser (indices, liquidite)"],
    ["data/", "Telecharge et met en cache prix, fondamentaux, macro (FRED)"],
    ["features/", "Calcule les indicateurs : technique, fondamental, momentum, regime macro, secteurs, sentiment"],
    ["scoring/", "Transforme les indicateurs en scores 0-100 et les combine"],
    ["signals/", "Applique les seuils d'entree et fabrique les plans de trade"],
    ["portfolio/", "Dimensionne les positions, construit le portefeuille, surveille le risque"],
    ["backtest/", "Rejoue la strategie sur le passe avec couts, et la valide"],
    ["execution/", "Passe les ordres (paper aujourd'hui, Alpaca/IBKR prevus)"],
    ["learning/", "Mesure ce qui marche et propose des ajustements"],
    ["api/ et dashboard/", "Exposition REST (FastAPI) et interface visuelle (Streamlit)"],
    ["pipelines/", "Orchestration : scan quotidien, execution paper, backtest"],
], widths=[3.5 * cm, 12.5 * cm]))
SP()
H2("3.2 Le cycle quotidien (23h00, lundi a vendredi)")
P("Une tache planifiee Windows nommee \"ATLAS Daily Run\" execute "
  "<i>python -m atlas.pipelines.daily_run</i>, qui enchaine deux etapes : "
  "le scan (analyse et scores) puis l'execution paper (gestion du "
  "portefeuille). Le deroule complet :")
B("1. Construction de l'univers : S&amp;P 500 (503 titres) + Nasdaq 100 (101) "
  "+ echantillon STOXX Europe (40), soit 556 titres uniques apres fusion.")
B("2. Telechargement des prix (25 ans d'historique, en cache local : seule "
  "la journee manquante est retelechargee) puis filtre de liquidite : "
  "prix minimum 3, volume quotidien moyen minimum 5 millions.")
B("3. Lecture des 8 series macro FRED et detection du regime economique.")
B("4. Notation des 13 secteurs via leurs ETFs (momentum, force relative).")
B("5. Pour chaque titre : score fondamental, technique, sectoriel.")
B("6. Combinaison en score composite, sauvegarde en base.")
B("7. Generation des signaux (seuils) avec plan de trade complet.")
B("8. Execution paper : verification des stops des positions ouvertes, "
  "remontee des stops suiveurs, achat des nouveaux signaux dans la limite "
  "des contraintes, enregistrement de l'equity du jour.")
B("9. Rapport de risque : drawdown, concentration, correlation.")
P("Toute la chaine est tolerante aux pannes : une donnee manquante degrade "
  "le score vers la neutralite (50) au lieu de faire echouer le run, et les "
  "telechargements interrompus reprennent ou ils se sont arretes.")

H1("4. Les donnees")
story.append(T([
    ["Donnee", "Source", "Frequence", "Remarque"],
    ["Prix OHLCV", "Yahoo Finance", "Quotidienne, 25 ans", "Gratuit, cache parquet local, telechargement par lots de 100"],
    ["Fondamentaux", "Yahoo Finance", "Instantane courant", "Ratios + bilans 4 ans ; 2 telechargements paralleles max (limite anti-blocage), cache journalier"],
    ["Macro", "FRED (Fed de St. Louis)", "Mensuelle/quotidienne", "8 series : CPI, PPI, chomage, PIB, taux Fed, courbe 10 ans-2 ans, M2, production industrielle"],
    ["Secteurs", "Yahoo (13 ETFs)", "Quotidienne", "XLK, XLV, XLE, XLF, XLI, XLY, XLP, XLU, XLB, XLRE, XLC, SMH, BOTZ"],
    ["Constituants", "Wikipedia", "Au demarrage", "Caches en CSV, rafraichissables"],
], widths=[2.6 * cm, 3.4 * cm, 3.2 * cm, 6.8 * cm]))
SP()
NOTE("<b>Limite importante :</b> Yahoo Finance est la source du prototype. "
     "Elle plafonne vers 1 500 titres par jour et ses fondamentaux sont un "
     "instantane du present (pas l'historique tel qu'il etait publie a "
     "l'epoque). Les interfaces pour brancher Polygon, Databento ou FMP "
     "existent deja dans le code (data/base.py). Voir l'audit, section 12.")

H1("5. Les cinq piliers du score")
P("Chaque titre recoit cinq notes de 0 a 100, combinees en un score composite "
  "selon des poids fixes dans config/config.yaml :")
story.append(T([
    ["Pilier", "Poids", "Ce qu'il mesure"],
    ["Fondamental", "35 %", "La qualite de l'entreprise"],
    ["Technique", "25 %", "L'etat du graphique"],
    ["Macro", "15 %", "Le contexte economique global"],
    ["Sectoriel", "15 %", "La force du secteur d'appartenance"],
    ["Sentiment", "10 %", "Le ton des publications (pas encore actif)"],
], widths=[3.5 * cm, 2 * cm, 10.5 * cm]))
SP()
H2("5.1 Pilier fondamental (35 %)")
P("Dix-sept ratios repartis en trois familles, chacun compare aux pairs du "
  "meme secteur (une marge de 30 % est banale dans le logiciel, exceptionnelle "
  "dans la distribution) :")
B("<b>Qualite (45 % du pilier)</b> : ROE, ROA, ROIC, marges brute/operationnelle/"
  "nette, et trois scores de solidite comptable : Piotroski F (9 criteres de "
  "sante financiere), Altman Z (risque de faillite), Beneish M (suspicion de "
  "manipulation comptable).")
B("<b>Croissance (25 %)</b> : croissance du chiffre d'affaires et des benefices.")
B("<b>Valorisation (30 %)</b> : PER, PER previsionnel, EV/EBITDA, prix/ventes, "
  "PEG, rendement de cash-flow libre. Plus c'est cher, plus la note baisse.")
P("Les valeurs extremes sont ecretees (winsorisation a 2 %), converties en "
  "rangs percentiles, moyennees, puis le resultat est lui-meme re-percentilise "
  "(rang du rang). Consequence directe : <b>un score fondamental de 80 "
  "signifie exactement top 20 % de l'univers du jour</b>. Sans cette derniere "
  "etape, la moyenne de 17 rangs comprimait tous les scores vers 50 et aucun "
  "titre ne pouvait franchir les seuils.")
H2("5.2 Pilier technique (25 %)")
P("Note construite a 70 % par des regles sur l'etat du graphique et a 30 % "
  "par un classement de momentum :")
B("Tendance : cours au-dessus de la moyenne 200 jours (20 pts), de la moyenne "
  "exponentielle 50 jours (15 pts), phase 2 de Weinstein en hebdomadaire (15 pts).")
B("Sante du mouvement : MACD positif (10 pts), force de tendance ADX (jusqu'a "
  "10 pts), RSI dans la zone saine 45-75 (10 pts).")
B("Configuration exploitable presente (10 pts) : cassure de canal Donchian, "
  "repli sur moyenne en tendance haussiere, ou compression de volatilite (VCP).")
B("Proximite du plus-haut annuel (jusqu'a 10 pts).")
B("Momentum cross-sectionnel (les 30 % restants) : rendements 3, 6 et 12 mois, "
  "momentum 12-1, faible volatilite, force relative face au S&amp;P 500.")
H2("5.3 Pilier macro (15 %)")
P("Les series FRED sont resumees en un regime parmi quatre, qui donne la meme "
  "note a tous les titres et module en plus la taille des nouvelles positions :")
story.append(T([
    ["Regime", "Diagnostic", "Note", "Taille des positions"],
    ["Reprise", "Croissance repart, inflation retombe", "90", "100 %"],
    ["Expansion", "Croissance positive (cas actuel)", "80", "100 %"],
    ["Ralentissement", "Production en baisse, chomage qui monte", "45", "70 %"],
    ["Recession", "Contraction + courbe des taux inversee", "20", "40 %"],
], widths=[2.8 * cm, 7.2 * cm, 1.6 * cm, 4.4 * cm]))
SP()
H2("5.4 Pilier sectoriel (15 %)")
P("Treize ETFs servent de thermometres. Pour chacun : momentum 1, 3 et 6 mois, "
  "force relative 6 mois contre le S&amp;P 500, bonus de 5 points au-dessus de "
  "sa moyenne 200 jours. Le tout en rangs percentiles donne un score par "
  "secteur, herite par chaque titre. C'est la heatmap du dashboard. Au "
  "11/06/2026 : semi-conducteurs 100, technologie 91,5, energie 80 en tete ; "
  "communication 11,5 en queue.")
H2("5.5 Pilier sentiment (10 %, inactif)")
P("Prevu : un LLM local (Ollama) lira rapports annuels, trimestriels et "
  "transcriptions de conferences pour noter tonalite, risques et opportunites. "
  "L'interface existe (features/sentiment.py) ; en attendant, le pilier est "
  "neutre et <b>son poids est redistribue au prorata</b> sur les piliers "
  "disponibles plutot que de diluer les scores.")

H1("6. Du score au signal d'achat")
H2("6.1 Les quatre seuils")
P("Un titre ne devient signal que si TOUTES les conditions sont reunies le "
  "meme jour : composite 85 ou plus, fondamental 80 ou plus, technique 80 ou "
  "plus, secteur 70 ou plus, et liquidite suffisante. Le 11/06/2026, "
  "7 titres sur 554 ont passe ce filtre.")
H2("6.2 Le plan de trade automatique")
P("Chaque signal arrive avec son mode d'emploi complet, calcule a partir de "
  "la volatilite du titre (ATR, l'amplitude moyenne de variation sur 14 jours) :")
B("<b>Stop de protection</b> : entree moins 2 ATR. C'est la definition du "
  "risque R du trade.")
B("<b>Trois objectifs de profit</b> : entree + 1,5 R, + 2,5 R, + 4 R.")
B("<b>Stop suiveur</b> : plus-haut atteint DEPUIS l'entree moins 3 ATR. Il "
  "monte avec le titre, ne descend jamais, et verrouille les gains.")
B("<b>Probabilite estimee et niveau de confiance</b>, calibres par "
  "l'historique des trades des qu'il y en aura assez (100 par tranche de score).")
CODE("Exemple reel (11/06/2026) - SIGNAL MU : entree 926,42 / stop 785,45 / "
     "TP 1137,87 - 1278,84 - 1490,30 / score 91 / confiance medium")
H2("6.3 La taille de position")
P("La quantite achetee est calculee pour que toucher le stop coute exactement "
  "0,75 % du capital, puis bornee par trois plafonds : 5 % du capital par "
  "titre, 25 % par secteur (verifie AVANT l'achat), 25 positions maximum. En "
  "regime macro defavorable, la taille est reduite (70 % en ralentissement, "
  "40 % en recession). Une fraction de Kelly plafonnee a 25 % ajustera "
  "l'agressivite quand l'historique de trades sera suffisant.")

H1("7. La gestion du risque")
P("Un module independant surveille le portefeuille apres chaque run et "
  "declenche des actions automatiques :")
story.append(T([
    ["Surveillance", "Seuil", "Action automatique"],
    ["Drawdown du portefeuille", "8 % / 12 % / 15 %", "Reduction de l'exposition brute a 75 % / 50 % / 25 %"],
    ["Perte d'une position", "20 %", "Cloture forcee (stop catastrophe)"],
    ["Correlation moyenne du book", "0,70", "Alerte couverture (hedge)"],
    ["Poids d'un secteur", "25 % du capital", "Blocage a l'entree + alerte rebalancement"],
    ["Poids d'un pays", "70 % du capital", "Alerte rebalancement"],
], widths=[5 * cm, 3.4 * cm, 7.6 * cm]))
SP()
P("Demonstration en conditions reelles le jour 0 : le 8e signal (ADI, "
  "semi-conducteurs) a ete refuse car le secteur technologie atteignait deja "
  "21,9 % du capital et l'achat l'aurait fait depasser 25 %.")

H1("8. Backtest et validation")
H2("8.1 La methodologie anti-biais")
B("<b>Pas de connaissance du futur (look-ahead)</b> : la decision se prend "
  "sur les donnees jusqu'au jour J, l'execution a lieu a J+1. Un test "
  "automatise verifie que la strategie ne voit jamais le futur.")
B("<b>Couts inclus</b> : 2 points de base de commission + 5 de slippage + "
  "1,5 de demi-spread sur chaque transaction. Le backtest 2008-2026 a paye "
  "45 493 dollars de frais simules.")
B("<b>Fondamentaux exclus du backtest</b> : les fondamentaux Yahoo decrivent "
  "le present, pas ce qui etait connu a l'epoque. Les utiliser dans le passe "
  "serait tricher. Seule la poche momentum/technique (prix purs, connus en "
  "temps reel par nature) est backtestee honnetement.")
B("<b>Biais du survivant documente</b> : l'univers actuel contient les "
  "survivants. Les chiffres ci-dessous sont donc optimistes ; le schema de "
  "base de donnees prevoit la table des constituants historiques pour "
  "l'eliminer (voir audit).")
H2("8.2 Resultats (strategie momentum, 40 titres, 2008-2026)")
P("Deux configurations sont presentees : la strategie brute, et le systeme "
  "complet avec son overlay de risque (les paliers de reduction d'exposition "
  "a 8/12/15 % de drawdown, simules comme en production). La comparaison "
  "montre le vrai prix de la protection :")
story.append(T([
    ["Metrique", "Sans overlay", "Avec overlay", "Lecture"],
    ["CAGR", "15,0 %", "9,1 %", "La protection coute ~6 points de rendement par an"],
    ["Drawdown maximal", "43,4 %", "23,2 %", "La pire perte est presque divisee par deux"],
    ["Volatilite", "18,2 %", "12,3 %", "Conforme a la cible configuree (12 %)"],
    ["Sharpe", "0,73", "0,59", "Rendement par unite de volatilite"],
    ["Calmar (CAGR / max DD)", "0,34", "0,39", "Meilleur rendement par unite de pire perte"],
    ["Beta vs S&amp;P 500", "0,75", "0,43", "Sensibilite au marche fortement reduite"],
    ["Crise 2008", "-35,6 %", "-20,3 %", "Perte contenue quand le marche perdait ~50 %"],
], widths=[4.2 * cm, 2.4 * cm, 2.4 * cm, 7.0 * cm]))
SP()
P("L'overlay a passe 43 % des seances en exposition reduite (minimum 25 %). "
  "C'est le compromis assume du systeme : on echange du rendement brut "
  "contre un parcours vivable, dont le drawdown reste une fois et demie "
  "moins profond. Note de calibration : meme a 25 % d'exposition, une "
  "baisse qui continue creuse encore ; le maximum simule (23 %) depasse la "
  "limite ideale de 15 %, qui reste un objectif de pilotage, pas une garantie.")
H2("8.3 Les quatre epreuves de robustesse (overlay actif)")
B("<b>Walk-forward</b> (19 fenetres annuelles hors echantillon, 2006-2025) : "
  "Sharpe moyen 0,76 ; 74 % des annees profitables.")
B("<b>Monte Carlo</b> (1 000 reordonnancements par blocs de 21 jours) : "
  "capital multiplie par 2 dans les 5 % pires scenarios, par 5 en mediane ; "
  "probabilite de perte a l'horizon complet 0,5 % ; drawdown au 95e "
  "centile 41 %.")
B("<b>Stress tests</b> : 2008 : -20,3 % (drawdown 24 %) ; COVID 2020 : "
  "-6,3 % (drawdown 19 %) ; 2022 : -5,8 % (drawdown 17 %). Le systeme perd "
  "dans les crises, mais des montants qui laissent continuer.")
B("<b>Sensibilite des parametres</b> (top_n a +/- 50 %, periode de momentum "
  "a +/- 2 mois, 9 combinaisons) : verdict STABLE ; tous les CAGR restent "
  "positifs (minimum 5,2 %), le Sharpe varie de 0,29 a 0,64 sans "
  "effondrement. Pas de signe d'overfitting des parametres.")
NOTE("Lecture honnete : ces resultats valident le MOTEUR (mecanique saine, "
     "pas de fuite du futur, couts realistes, overlay simule) et la poche "
     "momentum. Ils ne valident pas encore le score composite complet ni ses "
     "seuils 85/80/80/70, qui attendent des fondamentaux point-in-time pour "
     "etre backtestables (audit, points 4 et 5).")

H1("9. L'execution et le jour 0")
H2("9.1 Le broker paper")
P("Le broker simule execute au prix de reference avec le slippage configure, "
  "tient le cash, les positions, le journal des trades dans la base SQLite, "
  "et refuse les ordres impossibles (cash insuffisant, titre non detenu). "
  "Chaque trade cloture est relie au signal qui l'a cree : la boucle "
  "d'apprentissage saura quel score produisait quels resultats.")
H2("9.2 Chronologie reelle du 11 juin 2026")
story.append(T([
    ["Heure", "Evenement"],
    ["18h10", "Premier scan complet : 556 titres, prix 25 ans telecharges en 38 s (lots de 100)"],
    ["18h13", "Incident : Yahoo bloque les fondamentaux apres ~430 titres (trop de requetes). Correction : 2 telechargements paralleles au lieu de 8, reprise incrementale"],
    ["18h30", "Recalibration des scores (rang du rang) : 8 signaux franchissent les seuils"],
    ["18h33", "Bug SQLite corrige dans le broker (transaction imbriquee), 4 tests de regression ajoutes"],
    ["18h35", "Jour 0 propre : 7 achats, ADI refuse par le plafond sectoriel, equity 99 984"],
    ["22h15", "Cle FRED activee : regime expansion detecte, pilier macro reel dans les scores"],
    ["23h00", "La tache planifiee prend le relais pour tous les soirs de semaine"],
], widths=[1.8 * cm, 14.2 * cm]))
SP()
H2("9.3 Les garde-fous vers l'argent reel")
P("Trois verrous successifs : (1) le broker par defaut est paper et aucun "
  "autre ne demarre sans la variable d'environnement LIVE_TRADING_ACK "
  "explicitement remplie ; (2) la procedure GO_LIVE.md impose 3 a 6 mois de "
  "paper avec criteres chiffres (60 trades minimum, correlation backtest/reel "
  "superieure a 0,8, zero intervention manuelle non documentee) puis un "
  "compte demo broker avec reconciliation quotidienne ; (3) le reel demarre "
  "a 10 % du capital cible et monte par paliers mensuels.")

H1("10. Le dashboard et l'API")
P("L'interface Streamlit (http://localhost:8501) lit la base et offre six "
  "onglets : Watchlist (tous les scores du jour, filtrables), Signaux (les "
  "plans de trade), Portefeuille (positions, stops, courbe de capital), "
  "Secteurs (la heatmap), Backtests (metriques et courbes), Risque "
  "(expositions). Les donnees se rafraichissent toutes les 5 minutes.")
P("L'API FastAPI (http://localhost:8000/docs) expose les memes donnees en "
  "REST (scores, signaux, portefeuille, trades, backtests, propositions de "
  "poids) pour tout outil externe, plus un declencheur de scan.")

H1("11. L'auto-amelioration (boucle d'apprentissage)")
P("Tout est enregistre, donc tout est mesurable. Le module learning calcule :")
B("<b>L'IC de chaque pilier</b> (correlation de rang de Spearman entre le "
  "score du jour J et le rendement realise ensuite) : un pilier dont l'IC "
  "reste positif predit reellement ; un IC qui decline signale un facteur "
  "qui s'use.")
B("<b>Le taux de reussite par tranche de score</b>, qui calibrera les "
  "probabilites affichees sur les signaux.")
B("<b>Des propositions de reponderations</b>, bornees (chaque poids reste "
  "entre 50 % et 150 % de sa valeur courante), jamais appliquees seules : "
  "validation humaine + contre-verification en walk-forward obligatoires. "
  "L'automatisation complete n'est prevue qu'apres 6 propositions "
  "consecutives qui auraient ete acceptees telles quelles.")

PB()
H1("12. Audit complet du systeme")
H2("12.1 Ce qui est solide (verifie)")
B("Chaine complete operationnelle de bout en bout, automatisee, testee en "
  "conditions reelles le jour meme (donnees reelles, incidents reels, "
  "corrections reelles).")
B("30 tests automatises, dont des tests de non-regression sur chaque bug "
  "corrige et un test structurel anti look-ahead du moteur de backtest.")
B("Cinq bugs reels trouves et corriges des le premier jour, ce qui valide la "
  "demarche : blocage Yahoo (parallelisme reduit + cache incremental), "
  "compression des scores (rang du rang), interblocage SQLite du broker, "
  "stop suiveur ancre avant l'entree (vente immediate des achats en repli), "
  "contrainte sectorielle non appliquee a l'entree.")
B("Garde-fous en profondeur : verrou logiciel sur le reel, contraintes "
  "verifiees avant l'ordre, degradation gracieuse sur donnee manquante, "
  "journalisation complete signal-ordre-trade.")
B("Configuration centralisee (un seul YAML), zero nombre magique dans le code.")
H2("12.2 Faiblesses identifiees, par gravite, et leur statut")
story.append(T([
    ["#", "Faiblesse", "Gravite", "Statut au 11/06/2026"],
    ["1", "Devises non converties", "Haute", "CORRIGEE. Module fx.py : devise deduite du suffixe (pence/100 pour Londres), taux Yahoo caches, liquidite, sizing, equity et PnL en USD."],
    ["2", "Pas d'alerte en cas de panne", "Haute", "CORRIGEE. health.json ecrit a chaque run, healthcheck planifie chaque matin (popup Windows), synthese et alertes Telegram vers 2 destinataires."],
    ["3", "Risk overlay absent du backtest", "Haute", "CORRIGEE. Les paliers de reduction (8/12/15 % de drawdown) sont simules dans le moteur, decision a J applique a J+1, frais de transaction inclus. Test de regression sur krach synthetique."],
    ["4", "Biais du survivant", "Haute", "EN ATTENTE DE DONNEES. Necessite l'historique des constituants d'indices (abonnement). Le CAGR backteste reste une borne haute."],
    ["5", "Composite non backteste", "Moyenne", "EN ATTENTE DE DONNEES. Fondamentaux point-in-time requis (FMP as-reported ou EDGAR). Seule la poche momentum est validee sur 18 ans."],
    ["6", "Seuils et parametres non valides", "Moyenne", "OUTIL LIVRE. Test de sensibilite automatique (top_n +/-50 %, lookback +/-2 mois) integre a --validate avec verdict stable/fragile. Les seuils 85/80/80/70 attendent les donnees du point 5."],
    ["7", "Execution paper au cours du jour", "Moyenne", "CORRIGEE. Execution a l'ouverture J+1, identique au backtest. Signaux du jour en attente, expiration a 7 jours."],
    ["8", "SQLite mono-ecrivain", "Basse", "MITIGEE. Mode WAL active (lecteurs et ecrivain simultanes) + busy_timeout. Migration PostgreSQL prevue au passage a l'echelle."],
    ["9", "Pas de sauvegarde automatique", "Basse", "CORRIGEE. Copie quotidienne de la base dans data/backups/, 30 jours conserves."],
    ["10", "Pilier sentiment inactif", "Basse", "CHOIX ASSUME. Activation prevue en mode fantome d'abord (score journalise a poids nul, validation par IC), puis poids reel. Poids redistribue proprement en attendant."],
], widths=[0.8 * cm, 3.6 * cm, 1.7 * cm, 9.9 * cm]))
SP()
H2("12.3 Plan d'amelioration restant")
B("<b>Priorite 2, validite scientifique (1-3 mois)</b> : fondamentaux "
  "point-in-time (FMP as-reported ou SEC EDGAR avec dates de publication) et "
  "constituants historiques des indices, puis premier backtest honnete du "
  "composite complet et de ses seuils ; walk-forward automatique trimestriel.")
B("<b>Priorite 3, croissance (3-12 mois)</b> : Polygon ou Databento pour "
  "passer a 10 000 titres ; migration PostgreSQL ; pilier sentiment (LLM "
  "local + RAG sur les rapports, en mode fantome d'abord) ; connecteur "
  "Alpaca en compte demo ; analyse multi-horizon (hebdomadaire et 4h).")

H1("13. Feuille de route a 5 ans (resume)")
story.append(T([
    ["Periode", "Objectif principal"],
    ["Annee 1", "Fiabiliser : paper trading valide, donnees point-in-time, premier backtest complet du composite, demo broker, reel a 10 % si tous les criteres sont verts"],
    ["Annee 2", "Etendre : 10 000 titres (Polygon/Databento), Europe et Asie completes, gestion des devises, PostgreSQL, orchestration professionnelle"],
    ["Annee 3", "Diversifier : poches multi-strategies (tendance, retour a la moyenne, qualite long terme) allouees par regime macro, ETFs et REITs, couvertures systematiques"],
    ["Annee 4", "ML discipline : meta-labeling (le ML filtre les signaux au lieu de les creer), NLP v2, execution adaptative"],
    ["Annee 5", "Autonomie controlee : reponderation automatique sous bornes dures, multi-comptes, audit externe annuel"],
], widths=[2.2 * cm, 13.8 * cm]))
SP()
P("Principe directeur : une seule nouveaute majeure a la fois, validee par le "
  "meme protocole (walk-forward + Monte Carlo + paper) avant de toucher au "
  "capital. La complexite qui n'ameliore pas le Sharpe hors echantillon est "
  "retiree.")

H1("14. Guide pratique")
H2("14.1 Lancer les composants")
CODE("cd \"C:\\bot trading\\atlas\"<br/>"
     ".\\.venv\\Scripts\\Activate.ps1<br/><br/>"
     "python -m atlas.pipelines.daily_run        # scan + paper (manuel)<br/>"
     "python -m atlas.pipelines.run_backtest --limit 40 --validate<br/>"
     "streamlit run atlas/dashboard/app.py       # dashboard port 8501<br/>"
     "uvicorn atlas.api.main:app --port 8000     # API REST<br/>"
     "pytest                                     # 30 tests")
H2("14.2 La tache planifiee")
CODE("Get-ScheduledTask \"ATLAS Daily Run\"        # etat<br/>"
     "Start-ScheduledTask \"ATLAS Daily Run\"      # run immediat<br/>"
     "Unregister-ScheduledTask \"ATLAS Daily Run\" # suppression")
H2("14.3 Fichiers cles")
story.append(T([
    ["Fichier", "Role"],
    ["config/config.yaml", "Tous les reglages : poids, seuils, contraintes, couts"],
    [".env", "Secrets : cle FRED, cles broker, verrou du reel (jamais dans git)"],
    ["atlas.db", "La base : scores, signaux, positions, trades, backtests"],
    ["data/cache/", "Prix et fondamentaux en parquet"],
    ["data/daily_run.log", "Journal des runs nocturnes"],
    ["docs/", "Architecture, backtest, deploiement, go-live, roadmap"],
], widths=[4.5 * cm, 11.5 * cm]))

H1("15. Glossaire")
story.append(T([
    ["Terme", "Definition"],
    ["ATR", "Average True Range : amplitude moyenne de variation quotidienne d'un titre sur 14 jours. Sert d'unite de mesure pour les stops."],
    ["Backtest", "Simulation de la strategie sur les donnees passees, frais inclus."],
    ["Biais du survivant", "Erreur consistant a tester sur les entreprises qui existent encore, en oubliant les faillites et retraits de la cote."],
    ["CAGR", "Taux de croissance annuel compose du capital."],
    ["Composite", "Le score global 0-100, moyenne ponderee des cinq piliers."],
    ["Drawdown", "Baisse depuis le dernier sommet du capital, en pourcentage."],
    ["IC", "Information Coefficient : correlation entre un score et le rendement futur ; mesure si un facteur predit reellement."],
    ["Look-ahead", "Tricherie involontaire : utiliser dans le passe une information qui n'etait pas encore connue."],
    ["Momentum", "Tendance des titres qui ont monte a continuer de monter quelques mois ; l'anomalie de marche la plus documentee."],
    ["Paper trading", "Trading avec argent fictif mais donnees et regles reelles."],
    ["Percentile", "Position dans un classement : 80e percentile = mieux que 80 % des autres."],
    ["Point-in-time", "Donnee telle qu'elle etait connue a la date T, pas sa version corrigee ulterieure."],
    ["R (multiple)", "Unite de risque d'un trade : la distance entree-stop. Un gain de 2R rapporte deux fois le risque pris."],
    ["Sharpe", "Rendement excedentaire divise par la volatilite ; la note qualite-prix du risque."],
    ["Slippage", "Ecart entre le prix theorique et le prix reellement obtenu."],
    ["Stop suiveur", "Stop qui remonte avec le cours pour verrouiller les gains."],
    ["Walk-forward", "Validation par fenetres glissantes : on ne juge la strategie que sur des periodes qu'elle n'a jamais vues."],
], widths=[3.2 * cm, 12.8 * cm]))
SP(10)
story.append(Paragraph(
    "Avertissement : ce document decrit un outil de recherche. Rien ici ne "
    "constitue un conseil en investissement. Les performances passees, "
    "simulees ou non, ne prejugent pas des performances futures.", S_NOTE))

# ------------------------------------------------------------------ build ---

doc = Doc(str(OUT), pagesize=A4,
          leftMargin=2 * cm, rightMargin=2 * cm,
          topMargin=2 * cm, bottomMargin=2 * cm,
          title="ATLAS - Documentation complete et audit",
          author="ATLAS")
frame = Frame(2 * cm, 2 * cm, A4[0] - 4 * cm, A4[1] - 4 * cm, id="main")
doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])
doc.multiBuild(story)
print(f"PDF genere : {OUT}")
