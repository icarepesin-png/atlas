# -*- coding: utf-8 -*-
"""Genere l'audit ATLAS en PDF (docs/ATLAS_Audit.pdf).

Donnees reelles au 03/07/2026 (relevees depuis la base et la config).
Usage: python scripts/generate_audit_pdf.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

OUT = Path(__file__).resolve().parents[1] / "docs" / "ATLAS_Audit.pdf"

ss = getSampleStyleSheet()
BLUE = colors.HexColor("#1a3a5c")
GRAY = colors.HexColor("#555555")
GREEN = colors.HexColor("#2e7d32")
RED = colors.HexColor("#c0392b")
LIGHT = colors.HexColor("#eef2f6")

S_TITLE = ParagraphStyle("T", parent=ss["Title"], fontSize=28, textColor=BLUE, spaceAfter=4)
S_SUB = ParagraphStyle("S", parent=ss["Normal"], fontSize=12, textColor=GRAY, alignment=1, spaceAfter=4)
S_H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, textColor=BLUE, spaceBefore=16, spaceAfter=7)
S_H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, textColor=BLUE, spaceBefore=10, spaceAfter=4)
S_P = ParagraphStyle("P", parent=ss["Normal"], fontSize=10, leading=14.5, spaceAfter=6, alignment=4)
S_B = ParagraphStyle("B", parent=S_P, leftIndent=16, bulletIndent=6, spaceAfter=3)
S_NOTE = ParagraphStyle("N", parent=S_P, backColor=LIGHT, borderPadding=8, leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=10)
S_CODE = ParagraphStyle("C", parent=S_P, fontName="Courier", fontSize=9, backColor=LIGHT, borderPadding=8, leftIndent=6, rightIndent=6, leading=13)

TBL = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4d0")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
])


def T(data, widths):
    cell = ParagraphStyle("cell", parent=S_P, fontSize=9, leading=11.5, spaceAfter=0, alignment=0)
    head = ParagraphStyle("h", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    rows = [[Paragraph(str(c), head) for c in data[0]]]
    for r in data[1:]:
        rows.append([Paragraph(str(c), cell) for c in r])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TBL)
    return t


class Doc(BaseDocTemplate):
    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name == "H1":
            self.notify("TOCEntry", (0, f.getPlainText(), self.page))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(2 * cm, 1.2 * cm, "ATLAS - Audit du systeme")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


story = []
H1 = lambda t: story.append(Paragraph(t, S_H1))
H2 = lambda t: story.append(Paragraph(t, S_H2))
P = lambda t: story.append(Paragraph(t, S_P))
B = lambda t: story.append(Paragraph(t, S_B, bulletText="•"))
NOTE = lambda t: story.append(Paragraph(t, S_NOTE))
CODE = lambda t: story.append(Paragraph(t, S_CODE))
SP = lambda h=6: story.append(Spacer(1, h))

# -- Titre
story.append(Spacer(1, 4 * cm))
story.append(Paragraph("ATLAS", S_TITLE))
story.append(Paragraph("Audit du systeme", S_SUB))
story.append(Spacer(1, 0.8 * cm))
story.append(Paragraph("Plateforme quantitative de gestion d'un portefeuille d'actions", S_SUB))
story.append(Spacer(1, 2 * cm))
story.append(Paragraph("Periode couverte : 11 juin au 3 juillet 2026", S_SUB))
story.append(Paragraph(f"Document genere le {date.today():%d/%m/%Y}", S_SUB))
story.append(PageBreak())

# -- 1
H1("1. Vue d'ensemble")
P("ATLAS est une plateforme de trading quantitatif complete, construite de zero "
  "a un systeme autonome en 3,5 semaines. Elle analyse chaque nuit 555 actions, "
  "les note sur 5 piliers, genere des signaux, gere un portefeuille en paper "
  "trading (argent fictif), et se supervise seule via un dashboard web heberge "
  "et des notifications Telegram.")
NOTE("<b>Chiffres cles</b> : 18 versions publiees, 54 tests automatises verts, "
     "4 taches planifiees autonomes, dashboard cloud accessible 24/7, "
     "9 bugs identifies et corriges (chacun avec test de non-regression).")

# -- 2
H1("2. Ce qui a ete construit")
story.append(T([
    ["Periode", "Livraison"],
    ["11-12 juin", "Socle : scan 555 titres, scoring 5 piliers, signaux, portefeuille paper, backtest valide (walk-forward, Monte Carlo, stress tests), dashboard, API"],
    ["12-16 juin", "Autonomie : cle FRED (macro reelle), tache 23h, execution J+1, devises, sauvegardes, healthcheck, notifications Telegram (2 destinataires)"],
    ["16-17 juin", "Robustesse : audit interne, 5 bugs corriges, risk overlay dans le backtest, test de sensibilite, mode WAL"],
    ["17 juin", "Extensions : sentiment fantome (LLM local Ollama), connecteur Alpaca (dormant), reconciliation"],
    ["17 juin", "Cloud : base Neon Postgres + dashboard Streamlit Cloud, accessible PC eteint, code sur GitHub"],
    ["18-19 juin", "Dashboard : taux de reussite, PnL assure, noms de societes, valorisation live, bouton rafraichir, jours feries US"],
    ["19-23 juin", "Fiabilite : correctif crash NaN, notifications embellies, rattrapage au demarrage"],
], [2.6 * cm, 13.4 * cm]))
SP()
P("Reglages ajustes par l'utilisateur en cours de route : risque par position "
  "0,75% -> 0,5% ; plafond sectoriel 25% -> 30% ; trailing stop 3 -> 2,75 ATR.")

# -- 3
H1("3. Bugs rencontres et corriges")
P("Tous corriges avec un test de non-regression pour eviter leur retour :")
story.append(T([
    ["Bug", "Cause", "Correction"],
    ["Blocage Yahoo", "8 requetes paralleles", "2 workers + cache journalier"],
    ["Scores compresses vers 50", "moyenne de rangs", "re-percentilisation (rang de rang)"],
    ["Interblocage SQLite", "transaction imbriquee", "transaction unique"],
    ["Stop suiveur premature", "ancre avant l'entree", "ancre sur le plus-haut depuis l'entree"],
    ["Package atlas/data absent du cloud", "gitignore 'data/' trop large", "ancrage '/data/'"],
    ["'undefined' dans le dashboard", "NaN + titres de graphes vides", "placeholders 'n/d' + fix Plotly"],
    ["Crash jour ferie (Juneteenth)", "int(NaN) sur cours manquant", "sizing et valorisation NaN-safe"],
    ["Heure UTC au lieu de Paris", "horloge du serveur cloud", "fuseau Europe/Paris explicite"],
    ["Notification manquee (lundi)", "PC endormi a 23h", "rattrapage au demarrage de session"],
], [4.2 * cm, 5.0 * cm, 6.8 * cm]))

story.append(PageBreak())

# -- 4
H1("4. Etat actuel du systeme")
H2("4.1 Automatisation (4 taches Windows)")
story.append(T([
    ["Tache", "Declenchement", "Role"],
    ["ATLAS Daily Run", "lun-ven 23h00", "Scan + paper trading + notification"],
    ["ATLAS Catchup", "ouverture de session", "Rattrape un run manque (PC eteint a 23h)"],
    ["ATLAS Healthcheck", "mar-sam 9h00", "Alerte si aucun run n'a tourne"],
    ["ATLAS Dashboard", "ouverture de session", "Serveur du dashboard local (port 8501)"],
], [3.5 * cm, 4 * cm, 8.5 * cm]))
SP()
P("Dernier run reussi : <b>3 juillet, 23h</b>. Notifications Telegram "
  "operationnelles vers 2 destinataires, dans un format embelli.")
H2("4.2 Reglages en vigueur")
CODE("risque par position : 0,5%<br/>"
     "plafond par secteur : 30%<br/>"
     "poids max par position : 5%<br/>"
     "positions max : 25<br/>"
     "trailing stop : 2,75 ATR<br/>"
     "seuil d'entree (score composite) : 85")
H2("4.3 Infrastructure")
B("Dashboard cloud en ligne (Neon Postgres, Streamlit Cloud), accessible 24/7 "
  "meme PC eteint.")
B("Dashboard local relance (http://localhost:8501).")
B("Code sur GitHub, aucun secret expose.")

# -- 5
H1("5. Performance du paper trading")
P("La partie honnete de l'audit. Le systeme trade en argent fictif depuis le "
  "11 juin.")
story.append(T([
    ["Indicateur", "Valeur"],
    ["Capital de depart (11/06)", "100 000 USD"],
    ["Plus haut atteint (23/06)", "104 532 USD  (+4,5%)"],
    ["Valeur actuelle (03/07)", "98 006 USD  (-2,0%)"],
    ["Drawdown depuis le pic", "-6,2%"],
    ["Trades clotures", "14"],
    ["Trades gagnants", "3 (21%)"],
    ["PnL realise", "-1 788 USD"],
    ["Profit factor", "0,56 (< 1 = perte sur la periode)"],
], [8 * cm, 8 * cm]))
SP()
H2("Detail des trades")
story.append(T([
    ["Categorie", "Detail", "Total"],
    ["Gagnants", "WDC +1 437 · STX +610 · MU +241", "+2 288"],
    ["Perdants", "11 trades (APA, EOG, NEM, WDC, EME, SNDK, TER, STX...)", "-4 074"],
], [2.8 * cm, 9.8 * cm, 3.4 * cm]))

# -- 6
H1("6. Analyse : pourquoi -2% ?")
P("Ce resultat n'est <b>pas alarmant</b>, et il s'explique :")
B("<b>Marche en dents de scie</b> : apres une hausse (jusqu'au 23 juin), les "
  "titres se sont mis a osciller. Le trend-following deteste ce type de marche : "
  "le systeme entre, se fait ejecter au stop, re-rentre, se refait ejecter "
  "(effet 'whipsaw'). Exemple : WDC a rapporte +1 437 une fois, puis perdu -425 "
  "et -463 d'autres fois.")
B("<b>Le 3 juillet a ete rude</b> : 5 stops touches d'un coup (~-1 550), d'ou "
  "la chute de 101k a 98k en un jour.")
B("<b>Le taux de 21% est bas mais attendu par design</b> : le systeme gagne peu "
  "souvent avec de gros gains. Sur cette periode, les gros gains (2 288) n'ont "
  "pas suffi a couvrir la serie de petites pertes (4 074).")
NOTE("<b>Points rassurants</b> : le drawdown de 6,2% est bien sous la limite de "
     "15% (aucune reduction d'exposition declenchee) ; toutes les pertes sont "
     "petites et controlees (le risk management fonctionne) ; et 14 trades est "
     "un echantillon minuscule. Le backtest sur 18 ans reste positif malgre des "
     "periodes comme celle-ci.")

# -- 7
H1("7. Risques et points ouverts")
story.append(T([
    ["Point", "Gravite", "Commentaire"],
    ["Performance en baisse (-2%)", "Faible", "Normale en marche sans tendance. De-risking auto si drawdown > 8-12%."],
    ["Reglages modifies en cours de test", "Moyenne", "3 parametres changes : le 'test propre' a redemarre plusieurs fois, stats non comparables au backtest."],
    ["Fondamentaux non point-in-time", "Moyenne", "Biais du survivant, toujours ouvert. Necessite un abonnement (FMP/EDGAR)."],
    ["Sentiment inactif (poids 0)", "Faible", "Mode fantome tourne, validation par IC en cours."],
], [4.5 * cm, 1.8 * cm, 9.7 * cm]))

# -- 8
H1("8. Recommandations")
B("<b>Ne plus toucher aux reglages.</b> Laisser cette configuration tourner "
  "sans intervention ; chaque changement brouille la lecture des resultats.")
B("<b>Ne pas paniquer sur -2%.</b> C'est dans la marge normale. Le vrai jugement "
  "se fait sur des mois et des dizaines de trades, pas sur 3 semaines choppy.")
B("<b>Attendre le bilan a ~60 trades</b> (encore quelques semaines) pour juger "
  "la strategie objectivement.")
SP()
P("<b>Verdict global</b> : le systeme technique est solide et fiable (bugs "
  "corriges, autonome, resilient, bien teste). La performance est temporairement "
  "negative mais sous controle, dans un marche defavorable au style de la "
  "strategie. Rien d'anormal, rien de casse.")
SP(10)
story.append(Paragraph(
    "Avertissement : ce document decrit un outil de recherche en paper trading "
    "(argent fictif). Rien ici ne constitue un conseil en investissement. Les "
    "performances passees, simulees ou non, ne prejugent pas des performances "
    "futures.", S_NOTE))

doc = Doc(str(OUT), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
          topMargin=2 * cm, bottomMargin=2 * cm, title="ATLAS - Audit du systeme")
frame = Frame(2 * cm, 2 * cm, A4[0] - 4 * cm, A4[1] - 4 * cm, id="m")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])
doc.multiBuild(story)
print(f"PDF genere : {OUT}")
