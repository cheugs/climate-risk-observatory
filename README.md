# Observatoire du risque climatique et du développement humain

**Français** | [English](README.en.md)

Projet réalisé par **Chengho Fongang Marie Louise**

**Les régions au climat le plus extrême sont-elles aussi les régions où le développement humain est le plus faible ?**

Ce projet est une chaîne de traitement de données en Python. Il télécharge des données ouvertes
sur le climat, la population et le développement humain, construit un indice de risque climatique
pour chaque région, teste trois hypothèses et présente les résultats sous forme de cartes, d'un
rapport écrit (en français et en anglais) et d'un tableau de bord web.

Le pilote couvre **105 régions de niveau admin-1** (États, provinces, régions) en **France, Inde et
États-Unis**, soit environ 1,8 milliard d'habitants. Le même code peut tourner sur d'autres pays en
modifiant le fichier de configuration.

---

## Principaux résultats

| Hypothèse | Résultat |
|---|---|
| **H1.** Les régions les plus exposées aux aléas climatiques ont un SHDI plus faible | Oui sur l'ensemble des régions : rho de Spearman = **-0,59**, SHDI médian **0,786** contre **0,936**. Mais l'essentiel vient de l'écart entre l'Inde et les deux autres pays. À l'intérieur des pays : rho = -0,48 en Inde, -0,48 aux États-Unis, +0,18 en France (non significatif). |
| **H2.** C'est encore vrai à l'intérieur de chaque pays | Oui, mais l'effet est plus faible : le coefficient de l'aléa passe de **-0,39** à **-0,10** (IC à 95 % : -0,14 à -0,06) quand on ajoute un effet pays. Net en Inde et aux États-Unis, absent en France. |
| **H3.** Le classement est stable quand on change la formule de l'indice | Oui : les trois versions ont des corrélations de rang d'au moins **0,86**, et au moins **9 des 10** premières régions sont les mêmes. |

Les dix régions les plus à risque sont toutes en Inde (Bihar, Uttar Pradesh, Madhya Pradesh...).
Au sein de leur propre pays, les régions les plus à risque sont le Texas, l'Alabama et la Louisiane
(États-Unis) et l'Auvergne-Rhône-Alpes, l'Occitanie et la Nouvelle-Aquitaine (France).

Ces résultats sont des **associations, pas des causes**.

---

## Technologies

| Domaine | Outils |
|---|---|
| Langage | Python 3.10+ |
| Traitement des données | Pandas, NumPy, PyArrow (Parquet) |
| Géospatial | GeoPandas, Shapely, PyProj, Rasterio |
| Statistiques | SciPy (corrélation de Spearman), Statsmodels (régression MCO, erreurs robustes HC3) |
| Base de données | PostgreSQL + PostGIS (Docker), SQLAlchemy, GeoAlchemy2 |
| Cartes et graphiques | Plotly, Matplotlib, Kaleido |
| Tableau de bord | Plotly Dash, Dash Bootstrap Components |
| Rapport | Quarto (HTML + PDF, français et anglais), notebook Jupyter |
| Tests | pytest |
| Déploiement | Docker, Docker Compose, Render |

---

## Construction de l'indice

Chaque indicateur est transformé en **rang centile** entre 0 et 1, ce qui permet de combiner des
jours, des millimètres et des points d'indice.

```
Aléa           = moyenne(chaleur, sécheresse, humidité)
                 chaleur    = rang moyen de HD35 et TR25
                 sécheresse = rang moyen de CDD et -WBAL
                 humidité   = rang moyen de Rx1day et R50

Exposition     = rang(population)

Vulnérabilité  = 1 - rang(SHDI)

Risque         = Aléa x Exposition x Vulnérabilité
```

- Nous utilisons un **produit** car, suivant le GIEC, une région doit réunir les trois composantes
  pour être à risque : un désert brûlant où personne ne vit n'est pas une catastrophe.
- **L'exposition ne repose que sur la population.** La chaleur est déjà dans le score d'aléa ; si
  nous utilisions aussi « population x jours de chaleur » ici, la chaleur serait comptée deux fois.
- Deux autres versions servent à vérifier le classement (H3) : `additive` (moyenne des trois
  scores) et `per_person` (aléa x vulnérabilité, sans la population, pour vérifier que le classement
  n'est pas seulement un effet de taille).
- `rank_in_country` donne le rang de risque de chaque région au sein de son propre pays.

## Tests statistiques

| Hypothèse | Méthode | Code |
|---|---|---|
| H1 | Corrélation de Spearman aléa / SHDI, sur toutes les régions et par pays ; SHDI médian de la moitié la plus exposée et de la moitié la moins exposée | `src/cro/analysis/tests.py` |
| H2 | Régression linéaire (MCO, erreurs robustes HC3) : M1 `shdi ~ hazard`, M2 `shdi ~ hazard + indicatrices pays` ; la même droite ajustée dans chaque pays | `src/cro/analysis/regression.py` |
| H3 | Corrélation de Spearman entre les classements des trois versions + nombre de régions communes dans le top 10 | `src/cro/analysis/tests.py` |

---

## Notebook de présentation

`notebooks/exploration.fr.ipynb` raconte le projet étape par étape : les données, la construction
de l'indice, les cartes et les trois hypothèses. Il importe les mêmes fonctions que la chaîne de
traitement (`src/cro/`) et n'a besoin que de `data/processed/dashboard_regions.parquet`, qui est
dans le dépôt : il fonctionne donc juste après `git clone`. GitHub l'affiche avec tous ses tableaux
et graphiques. La version anglaise est `notebooks/exploration.ipynb`.

---

## Démarrage rapide

```bash
# 1. Environnement
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e .

# 2. Vérifier que les sources de données sont accessibles
cro probe

# 3. Lancer la chaîne de traitement (télécharge ~500 Mo une fois, puis utilise un cache)
cro all

# 4. Contrôles, sorties, rapport
cro validate
cro export
cro report

# 5. Tableau de bord
cro app            # http://127.0.0.1:8050
```

Chaque étape peut aussi être lancée seule :

| Commande | Rôle |
|---|---|
| `cro boundaries` | Télécharge les polygones admin-1 depuis geoBoundaries |
| `cro climate-points` | Choisit les points d'échantillonnage climatique dans chaque région |
| `cro population` | Population par région et par point d'échantillonnage (GHS-POP) |
| `cro climate` | Télécharge les données journalières NASA POWER et calcule les indicateurs annuels |
| `cro development` | SHDI de Global Data Lab + WDI de la Banque mondiale |
| `cro build` | Construit l'aléa, l'exposition, la vulnérabilité et les trois versions du risque |
| `cro analyze` | Tableaux descriptifs, tests H1 et H3, régressions H2 |
| `cro export` | 11 cartes statiques, 6 figures, 4 cartes interactives |
| `cro report` | Construit les tableaux du rapport et génère le rapport (FR + EN) avec Quarto |
| `cro validate` | 8 contrôles de données (code de sortie 1 si l'un échoue) |
| `cro load` | Charge les tables dans PostGIS |
| `cro app` | Lance le tableau de bord Plotly Dash |
| `cro all` | Enchaîne ingestion -> construction -> analyse -> export |

---

## Tableau de bord

`cro app` ouvre une page unique à faire défiler sur <http://127.0.0.1:8050> :

- **la carte** - un panneau par pays. Choisissez *tous* pour comparer les trois pays sur une même
  échelle de couleurs, ou un seul pays pour voir ses différences internes.
- **le classement** - les dix régions ayant la valeur la plus élevée pour la mesure choisie.
- **la relation** - l'aléa en fonction du SHDI, avec une droite de tendance par pays et les
  résultats H1/H2/H3 à côté (lus dans les tables de résultats, jamais saisis à la main).
- **un lieu** - les chiffres d'une région et sa position par rapport aux autres.
- **méthodes et données** - la construction de l'indice et ses limites.

Autres pages sur le même serveur :

- `/summary` - un résumé du rapport en deux minutes (`/summary?lang=fr` en français)
- `/report` et `/report.pdf` - le rapport complet (`/report/fr` et `/report/fr.pdf` en français)
- `/maps/map_web_risk.html` (et `hazard`, `exposure`, `shdi`) - cartes interactives

Chaque page a un bouton **EN / FR**. Le tableau de bord lit PostGIS quand il est lancé, et les
fichiers Parquet sinon : il fonctionne donc sans Docker.

## Déploiement

L'application est en ligne sur l'offre gratuite de Render :
**<https://climate-risk-observatory.onrender.com>**. L'instance gratuite se met en veille après
15 minutes sans visite, la première requête peut donc prendre environ une minute.

`render.yaml` est le plan de déploiement Render et `requirements-deploy.txt` ne liste que les
paquets nécessaires à l'application. Les étapes sont décrites dans
**[docs/deploy.md](docs/deploy.md)**.

---

## Organisation du dépôt

```
config/config.yaml              tous les paramètres (pays, seuils, années)
src/cro/ingest/                 téléchargement des limites, du climat, de la population, du développement
src/cro/features/build.py       aléa, exposition, vulnérabilité, versions du risque
src/cro/analysis/               tableaux descriptifs, tests H1/H3, régression H2
src/cro/viz/                    thème commun, cartes statiques, graphiques, cartes interactives
src/cro/app/                    tableau de bord Dash + pages résumé et rapport
src/cro/app/i18n.py             tous les textes français/anglais du tableau de bord
src/cro/db/                     schéma PostGIS et chargement
src/cro/report/                 tableaux du rapport + génération Quarto
report/                         report.qmd / report.fr.qmd
notebooks/exploration.fr.ipynb  présentation pas à pas des résultats (en français)
notebooks/exploration.ipynb     la même présentation en anglais
tests/                          tests unitaires, contrôles de données, tests du tableau de bord
data/processed/                 tables intermédiaires (Parquet)
outputs/maps|figures|tables/    résultats
outputs/report/                 report(.fr).html/.pdf, validation.md, key_results.md
```

`data/processed/region_master.parquet` est l'unique table lue par toutes les sorties : les cartes,
les tableaux et le tableau de bord sont donc toujours cohérents.

### Tables de sortie

| Fichier | Contenu |
|---|---|
| `t01_summary_by_country.csv` | moyennes par pays |
| `t02_climate_by_country.csv` | indicateurs climatiques par pays |
| `t03_top_bottom_regions.csv` | régions au risque le plus élevé et le plus faible |
| `t05_hypothesis_tests.csv` | H1 : corrélation de Spearman, toutes régions et par pays |
| `t06_rank_stability.csv` | H3 : concordance entre les trois versions de l'indice |
| `t07_regression_coefficients.csv` | H2 : modèles M1 et M2 |
| `t08_country_slopes.csv` | H2 : pente dans chaque pays |

---

## Sources de données et licences

| Couche | Source | Résolution | Année | Licence |
|---|---|---|---|---|
| Limites administratives | [geoBoundaries](https://www.geoboundaries.org/) (gbOpen) | polygones admin-1 | version 2024 | CC-BY 4.0 |
| Climat | [NASA POWER](https://power.larc.nasa.gov/) (MERRA-2) | séries journalières ponctuelles | 1991-2023 | Libre, sans clé |
| Population | [GHS-POP R2023A](https://ghsl.jrc.ec.europa.eu/) | ~1 km | 2020 | CC-BY 4.0 |
| Développement | [Global Data Lab SHDI](https://globaldatalab.org/shdi/) | admin-1 | dernière année disponible | Libre pour la recherche |
| Contexte national | [Banque mondiale WDI](https://databank.worldbank.org/source/world-development-indicators) | pays | 2010-2023 | CC-BY 4.0 |

NASA POWER ne fournit pas l'évapotranspiration ; nous l'estimons avec la formule de Hargreaves
(Hargreaves et Samani, 1985) à partir des températures minimale et maximale journalières et de la
latitude.

---

## Qualité et tests

- `cro validate` exécute 8 contrôles de données : unicité des régions, validité des géométries,
  totaux de population, plages physiques, scores entre 0 et 1, couverture du SHDI, table
  principale et tables de sortie.
- `pytest -q` lance les tests :
  - `tests/test_indicators.py` - les calculs de l'indice et les fonctions statistiques sur de
    petits exemples ;
  - `tests/test_data_contract.py` - contrôles sur les fichiers réels (ignorés avant l'exécution de
    la chaîne) ;
  - `tests/test_presentation.py` - cartes, callbacks et pages du tableau de bord.
- Le rapport et le tableau de bord lisent leurs chiffres dans les mêmes tables CSV.

## PostGIS (facultatif)

```bash
docker compose up -d
cro load
```

Cela crée `dim_region`, `dim_country`, `fact_climate`, `fact_population`, `fact_exposure`,
`fact_development`, `fact_risk` (une ligne par région et par version de l'indice) et la vue
`vw_region_profile` sur le port **5433**.

---

## Limites

1. **Association, pas causalité.** L'histoire, la géographie et l'économie peuvent expliquer à la
   fois le climat et le développement.
2. **Les régions voisines se ressemblent.** Les tests traitent les régions comme indépendantes : les
   p-valeurs sont donc probablement trop petites. Un modèle de régression spatiale serait l'étape
   suivante.
3. **Petit échantillon.** 99 régions ont un SHDI ; la France n'en compte que 13, ses résultats sont
   donc incertains.
4. **Un seul indicateur de développement.** Le SHDI ne montre pas les inégalités à l'intérieur
   d'une région.
5. **Seuils fixes.** 35 °C et 50 mm sont des choix ; la France n'a presque aucun jour au-dessus de
   35 °C.
6. **Population statique.** La population est celle de 2020 ; la moyenne climatique porte sur
   2004-2023.
7. **Échantillonnage grossier.** Au plus 8 points climatiques par région.
8. **Pays pilotes.** La France, l'Inde et les États-Unis ont été choisis parce qu'ils sont
   différents, pas parce qu'ils représentent le monde.

## Prochaines étapes

- Ajouter des pays : modifier `project.pilot_iso3` dans `config/config.yaml` (par exemple `["ALL"]`).
- Utiliser un modèle de régression spatiale.
- Ajouter un indicateur de revenu des ménages pour voir les inégalités à l'intérieur des régions.
- Tester d'autres seuils de chaleur (30 °C, 40 °C).

## Références principales

La liste complète figure dans le rapport. Les principaux choix de méthode s'appuient sur :

- **Risque = aléa x exposition x vulnérabilité :** Cardona et al. (2012), GIEC SREX chapitre 2 ; GIEC (2014), AR5 GT II.
- **Indice de risque multiplicatif :** Marin-Ferrer, Vernaccini et Poljansek (2017), méthodologie INFORM (Centre commun de recherche de la Commission européenne).
- **Normalisation par les rangs et tests de robustesse :** Nardo et al. (2008), OCDE/CCR *Handbook on Constructing Composite Indicators* ; Saisana, Saltelli et Tarantola (2005), *JRSS A* 168(2).
- **Indicateurs d'extrêmes climatiques :** Zhang et al. (2011), *WIREs Climate Change* 2(6).
- **Climat et revenu à l'intérieur des pays :** Dell, Jones et Olken (2009), *American Economic Review* 99(2) ; Nordhaus (2006), *PNAS* 103(10).
- **IDH infranational :** Smits et Permanyer (2019), *Scientific Data* 6.
