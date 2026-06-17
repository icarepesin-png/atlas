# -*- coding: utf-8 -*-
"""Genere un guide PDF simple pour acceder au dashboard ATLAS (pour Darius).

Usage: python scripts/generate_guide_darius.py
Sortie: docs/ATLAS_Guide_Acces.pdf
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

OUT = Path(__file__).resolve().parents[1] / "docs" / "ATLAS_Guide_Acces.pdf"
URL = "https://bfuunx3imesbnlybietd72.streamlit.app"

ss = getSampleStyleSheet()
NAVY = colors.HexColor("#0b1220")
BLUE = colors.HexColor("#1a3a5c")
AMBER = colors.HexColor("#b8843a")
GRAY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#eef2f6")

S_TITLE = ParagraphStyle("T", parent=ss["Title"], fontSize=26, textColor=BLUE,
                         spaceAfter=2)
S_SUB = ParagraphStyle("S", parent=ss["Normal"], fontSize=12, textColor=GRAY,
                       spaceAfter=14)
S_H = ParagraphStyle("H", parent=ss["Heading2"], fontSize=14, textColor=BLUE,
                     spaceBefore=14, spaceAfter=6)
S_P = ParagraphStyle("P", parent=ss["Normal"], fontSize=11, leading=16,
                     spaceAfter=6)
S_URL = ParagraphStyle("U", parent=ss["Normal"], fontSize=13, leading=18,
                       textColor=AMBER, fontName="Courier-Bold",
                       backColor=LIGHT, borderPadding=10, spaceAfter=6)
S_LI = ParagraphStyle("LI", parent=S_P, spaceAfter=4)

story = []
story.append(Paragraph("ATLAS", S_TITLE))
story.append(Paragraph("Comment consulter le dashboard - guide pour Darius", S_SUB))

story.append(Paragraph("Le lien du site", S_H))
story.append(Paragraph(URL, S_URL))
story.append(Paragraph("Accessible depuis n'importe quel appareil (telephone, "
                       "PC, tablette), de partout, a toute heure.", S_P))

story.append(Paragraph("Etape 1 - Premiere connexion (une seule fois)", S_H))
story.append(ListFlowable([
    ListItem(Paragraph("Ouvre le lien ci-dessus dans ton navigateur.", S_LI)),
    ListItem(Paragraph("Une page te demande de te connecter (le site est prive).", S_LI)),
    ListItem(Paragraph("Clique sur <b>\"Continue with Google\"</b> et connecte-toi "
                       "avec l'email qu'Icare a ajoute a la liste des autorises "
                       "(utilise bien le meme email, sinon l'acces est refuse).", S_LI)),
    ListItem(Paragraph("Le dashboard ATLAS s'affiche.", S_LI)),
], bulletType="1", leftIndent=14))

story.append(Paragraph("Etape 2 - Garder l'acces facile", S_H))
story.append(ListFlowable([
    ListItem(Paragraph("Mets le lien en favori, ou ajoute-le a l'ecran "
                       "d'accueil de ton telephone.", S_LI)),
    ListItem(Paragraph("Tu n'auras plus a te reconnecter ensuite.", S_LI)),
], bulletType="bullet", leftIndent=14))

story.append(Paragraph("Ce que tu peux consulter", S_H))
tbl = Table([
    ["Onglet", "Ce que tu y vois"],
    ["Watchlist", "Les 554 actions analysees et leurs notes"],
    ["Signaux", "Les ordres d'achat detectes"],
    ["Portefeuille", "Les positions, la valeur en direct, les gains/pertes"],
    ["Secteurs", "La carte des secteurs forts / faibles"],
    ["Backtests", "Les tests de performance historiques"],
    ["Risque", "La repartition du portefeuille"],
], colWidths=[3.5 * cm, 11.5 * cm])
tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4d0")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (-1, -1), 8),
]))
story.append(tbl)

story.append(Paragraph("Bon a savoir", S_H))
story.append(ListFlowable([
    ListItem(Paragraph("Accessible 24h/24, de partout: plus besoin que le PC "
                       "d'Icare soit allume.", S_LI)),
    ListItem(Paragraph("Les chiffres se mettent a jour une fois par jour, apres "
                       "le scan du soir (vers 23h).", S_LI)),
    ListItem(Paragraph("En journee, l'onglet Portefeuille montre l'evolution des "
                       "prix en direct (heures de bourse US: 15h30-22h, Paris).", S_LI)),
    ListItem(Paragraph("Tu recois deja les notifications Telegram; le site, c'est "
                       "pour voir le detail visuel quand tu veux.", S_LI)),
], bulletType="bullet", leftIndent=14))

story.append(Paragraph("Si ca ne marche pas", S_H))
story.append(ListFlowable([
    ListItem(Paragraph("<b>\"Vous n'avez pas acces\"</b> : l'email utilise n'est "
                       "pas autorise. Demande a Icare d'ajouter ton email dans les "
                       "reglages de partage de l'app.", S_LI)),
    ListItem(Paragraph("<b>Page blanche ou erreur</b> : attends une minute et "
                       "rafraichis (le site se reveille apres une periode sans visite).", S_LI)),
], bulletType="bullet", leftIndent=14))

story.append(Spacer(1, 12))
story.append(Paragraph("ATLAS - plateforme de recherche, paper trading (argent "
                       "fictif). Rien ici n'est un conseil en investissement.",
                       ParagraphStyle("F", parent=S_P, fontSize=8.5,
                                      textColor=GRAY, backColor=LIGHT,
                                      borderPadding=8)))

SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                  topMargin=2 * cm, bottomMargin=2 * cm,
                  title="ATLAS - Guide d'acces").build(story)
print(f"PDF genere : {OUT}")
