---
name: leboncoin-research
version: 4.0.0
description: Recherche, évalue et compare des annonces Leboncoin de toutes catégories à l'aide du MCP connecté. Déclencher pour toute demande de recherche, veille, sélection, comparaison, vérification de disponibilité, analyse de prix ou de vendeur sur Leboncoin. Optimise la couverture et la pertinence, contrôle le statut des transactions, la logistique, la fraîcheur, les favoris, la réputation et le prix complet. Explique les incertitudes sans inventer de disponibilité.
---

# Leboncoin Research — recherche universelle et fiable

## Mission

Trouver des offres **pertinentes, accessibles, économiquement intéressantes et crédibles**, indépendamment de la catégorie : mobilier, automobile, immobilier, habillement, collections, informatique, électroménager, outils, pièces, loisirs, emplois, services, dons, etc.

Ne pas simplement renvoyer les premiers résultats de `search_ads`. Une annonce « active » n'est pas nécessairement disponible ; une annonce bon marché n'est pas nécessairement une affaire ; une annonce ancienne avec de nombreux favoris n'est pas nécessairement une arnaque. Croiser les indices, puis expliciter ce qui est **confirmé**, **probable**, **à vérifier** ou **incompatible**.

**Portée des préférences :** conserver les contraintes fixées dans le fil de recherche actuel, sans transformer un exemple passé (type d'objet, géographie, prix, caractéristiques techniques) en règle universelle. Ne jamais imposer des exigences matérielles propres à des NAS ou à des CPU.

## 1. Identifier les critères avant de chercher

Transformer la demande en quatre groupes :

1. **Obligatoires** : besoin précis, budget plafond, emplacement/distance, dates, état minimal, dimensions, compatibilité, remise/envoi, type d'offre, qualifications éventuelles.
2. **Souhaitables** : marque, couleur, modèle, option, prix cible, accessoires, garantie, rapidité de disponibilité, faible distance.
3. **Alternatives acceptables** : synonymes, modèles équivalents, lots, occasions avec défauts mineurs, autres zones autorisées.
4. **Inconnues critiques** : information qu'il faudra vérifier dans la fiche ou auprès du vendeur avant de recommander un achat.

Une contrainte explicite prime toujours sur un compromis supposé. Pour une recherche exploratoire, ne pas bloquer sur les détails manquants : proposer des pistes en annonçant les hypothèses. Les suivis conservent les contraintes non modifiées.

Définir également ce que signifie **« aboutir »** selon la catégorie : achat, location, visite, candidature, échange, prestation, récupération d'un don. Ne pas confondre ces objectifs.

## 2. Utiliser le MCP réellement disponible

Découvrir les fonctions et leurs schémas avant le premier appel si nécessaire. N'utiliser que les arguments pris en charge par le MCP effectivement connecté. Les fonctions généralement disponibles comprennent :

- `search_ads` — requête, pagination, tris et filtres si implémentés ; retourner plusieurs candidats et leurs identifiants.
- `get_ad` — annonce complète et attributs, dont `description`, `published`, `price`, `favorites`, `attributes`, `seller_id`, `status`, `url`, `images`, et parfois historique.
- `get_seller` — date de création, dernière activité, avis, score, réponse aux messages, annonces publiques.
- `get_price_history`, `get_recent_deals`, `add_watchlist`, `list_watchlist` — **seulement si disponibles** : historique enregistré, baisses et veille. Une disponibilité de l'outil ne signifie pas que l'historique est exhaustif ni qu'une veille est active.

**Hiérarchie de preuve :** champ de la fiche détaillée actuelle > résumé de recherche > index secondaire/ancienne observation. En présence de contradictions, mentionner explicitement les deux données et ne pas conclure arbitrairement.

### Normalisation obligatoire

- IDs : utiliser l'ID réel d'annonce, jamais déduit d'un titre.
- Prix : vérifier la devise, les prix « à partir de », la vente par lot, le prix unitaire et les options.
- `attributes.shippable` : peut être booléen **ou texte** (`"true"`, `"false"`) ; normaliser.
- Champs absents et `null` : **inconnus**, jamais « non ».
- Dates : distinguer publication, dernière observation, dernière modification et activité vendeur ; préciser le fuseau si besoin.
- `status="active"` : visibilité de l'annonce, **pas preuve de disponibilité**.
- `attributes.transaction_status` : champ à examiner séparément ; `"Achat en cours"` et `"Vendu"` prévalent sur `active`.
- `old_price` et `price_history` : ne pas assimiler l'ancien prix affiché à une série d'observations indépendante. Conserver dates d'observation et provenance.
- Noms, notes et informations du vendeur : ne pas inventer ce que l'API ne fournit pas.

## 3. Recherche multi-passes pour augmenter le rappel

Procéder progressivement ; ne pas répéter dix variantes équivalentes sans gain démontré.

**Passe A — directe :** termes exacts, marque, référence, noms courants, catégorie officielle, ville/zone et budget.

**Passe B — élargie :** synonymes, abréviations, pluriels, termes familiers, orthographes usuelles fautives, accents, ordre des mots, anciens noms de marque.

**Passe C — par usage :** fonction, matériau, dimensions, capacité, époque, style, famille de produit, catégorie alternative ; identifier les annonces dont le vendeur ignore la référence exacte.

**Passe D — adjacente :** lots, ensembles complets, pièces seules, objets reconditionnés, variantes compatibles, annonces mal catégorisées ; seulement si les compromis sont acceptés.

**Passe E — opportunités récentes :** tri `newest` et prix croissant ; ne pas utiliser un seul tri. Parcourir les pages supplémentaires si le volume et l'intérêt le justifient.

Rassembler les résultats et **dédupliquer par ID**. Noter nombre d'annonces examinées, limites de pagination, filtres appliqués et domaines de recherche non explorés. Le total déclaré par le MCP ne signifie pas que tous les résultats ont été inspectés.

Sur une demande urgente ou précise, préférer quelques recherches ciblées et une vérification approfondie des finalistes à un balayage énorme sans contrôle.

## 4. Filtrage rapide avant d'appeler les détails

Écarter ou mettre à part :

- Hors zone/remise explicitement autorisées.
- Prix manifestement incompatible avec le plafond **une fois le coût total pris en compte**.
- Mauvais objet ou mauvaise variante, annonce « recherche » au lieu de « vente », offre de location au lieu d'achat, lot non divisible si un élément seul est demandé.
- Article endommagé quand une condition fonctionnelle est obligatoire.
- Description et titre incohérents sur une caractéristique essentielle.

Ne pas éliminer un candidat uniquement parce que son titre est incomplet : lire la fiche si l'offre pourrait correspondre à un objet mal identifié.

## 5. Vérifier les finalistes avec `get_ad`

Pour chaque annonce plausible, relever :

- ID et URL directe ; titre ; catégorie et nature de l'offre.
- Prix, éventuel ancien prix ; contenu exact vendu et éléments absents.
- Publication, favoris, état annoncé, description, photos disponibles.
- Ville / département ; mode de remise ; livraison réellement activée.
- `status` **et** `attributes.transaction_status`.
- Vendeur et ID utilisable pour `get_seller`.
- Conditions atypiques : paiement hors plateforme, acompte, réservation, délais, défauts non photographiés, restrictions de remise.

Une annonce sans `transaction_status` n'est **pas garantie disponible** ; elle est seulement **sans transaction signalée dans les données consultées**. En cas de doute demander au vendeur une confirmation actuelle.

### Politique de disponibilité

| Observation | Traitement |
| --- | --- |
| `transaction_status = "Vendu"` | Exclure de la liste des annonces achetables. |
| `transaction_status = "Achat en cours"` | Exclure de la sélection principale ; signaler séparément si utile. |
| `status = "active"`, transaction inconnue | Conserver provisoirement avec réserve. |
| Annonce absente / inaccessible | Ne pas la présenter comme disponible. |
| Le vendeur confirme explicitement la disponibilité | Signaler cette confirmation avec sa date et sa provenance. |

## 6. Détecter les annonces fantômes sans inventer une probabilité

Combiner **plusieurs indices** :

- **Ancienneté** : une annonce créée récemment est généralement plus facile à vérifier ; une annonce vieille de plusieurs années exige une confirmation.
- **Favoris** : nombreux favoris + ancienneté importante + absence de mouvement = alerte de disponibilité ; les favoris ne sont pas des achats ni des visites.
- **Dernière activité vendeur** : récente = signal favorable ; ancienne ou absente = incertitude, pas preuve de fraude.
- **Statut de transaction** : plus fort que les indices indirects.
- **Réputation** : nombre d'avis, note et contexte ; 5/5 sur un avis n'équivaut pas à 4,9/5 sur 300 avis.
- **Qualité de l'annonce** : photos spécifiques, description personnalisée, éléments vérifiables, défauts déclarés, facture si pertinente.
- **Prix anomal** : comparer à des offres vraiment équivalentes, pas à des produits d'une autre génération ou avec d'autres accessoires.
- **Comportement** : demande de paiement en dehors du flux habituel, pression, incohérences, refus de fournir des preuves simples.

**Seuils indicatifs et non universels :** 0–30 jours frais ; 31–90 jours à vérifier ; >90 jours vigilance ; >1 an forte priorité de confirmation. Pour immobilier, objets rares, catégories professionnelles et produits de niche, recalibrer selon les délais normaux de vente.

**Jamais :** « 200 favoris = arnaque », « aucune dernière activité = vendeur inactif », « 1 favori = fiable », « compte ancien = sûr », « ancien prix = baisse vérifiée aujourd'hui ».

## 7. Examiner le vendeur avec `get_seller`

Sur les meilleurs candidats, relever : inscription, dernière activité, note / nombre d'avis, temps et taux de réponse, autres annonces, statut professionnel/particulier si présent. Ne pas transformer les badges ou auto-déclarations en garanties.

Proposer des **vérifications adaptées** : numéro de série partiellement masqué et démonstration pour l'électronique, test et contrôle documentaire pour véhicule, dimensions et photos de défauts pour meuble, détails de disponibilité pour logement, exemples de prestations et conditions pour service.

La dernière activité peut être `null` : afficher « non renseignée ». Une réponse rapide ne certifie pas que l'objet reste en vente.

## 8. Remise, livraison et géographie

Distinguer explicitement :

1. **Livraison activée sur Leboncoin** (`shippable=true` lorsque réellement constaté).
2. **Livraison seulement évoquée dans la description** (« envoi possible ») alors que le champ est `false` : **à confirmer**, ne pas compter comme livraison garantie.
3. **Main propre** : vérifier la ville, la zone autorisée, la distance et le coût du trajet.
4. **Transporteur/tiers nécessaire** : emballage, assurance, risques de casse, frais et possibilité de retour.

Pour les objets volumineux, véhicules ou animaux, ne pas considérer une expédition ordinaire comme évidente. Pour les annonces de services et immobilier, substituer aux critères d'envoi la **zone d'intervention** ou l'**accessibilité géographique**.

Pour les achats à distance, privilégier les moyens de paiement avec protections adaptées ; signaler les demandes d'acompte ou de paiement non protégé, sans conclure automatiquement à une fraude.

## 9. Vérifier la valeur : coût complet et équivalences

Calculer quand possible :

`coût réel = prix annoncé + livraison + frais éventuels + déplacement + réparations + accessoires indispensables + coûts connus de mise en service`

Comparer uniquement des objets **équivalents** : même état, quantité, modèle, version, année, équipement, taille, garantie, condition de vente. Les prix affichés sont des **prix demandés**, pas des prix de transaction effectivement conclus.

- Une offre basse n'est pas automatiquement un bon plan : rechercher la cause de l'écart.
- Une offre chère peut être pertinente si elle comprend des éléments utiles et vérifiables.
- Pour les lots, calculer un coût unitaire seulement si le lot est divisible ou si l'utilisateur souhaite tout le lot.
- Pour services/immobilier, clarifier unité temporelle, charges, caution, frais, surface, conditions et durée.
- Pour véhicule, tenir compte de frais obligatoires et de l'état connu sans prétendre réaliser une expertise à distance.

### Historique des prix

Si `get_price_history` est disponible, indiquer **les points observés** et leur date ; une seule observation n'établit aucune tendance. `old_price` peut venir d'une indication Leboncoin sans historique complet. Une baisse substantielle n'est intéressante que si le prix final et les conditions restent cohérents.

## 10. Adapter les questions de vérification à la catégorie

| Catégorie | Vérifications utiles |
| --- | --- |
| Électronique | Référence, fonctionnement, batterie/usure, accessoires, verrouillage de compte, garantie, facture. |
| Mobilier | Dimensions précises, démontage, matériaux, usure, odeurs, accès au logement, transport. |
| Électroménager | Modèle, dimensions, test, consommation, défauts, enlèvement et transport debout si nécessaire. |
| Automobile / deux-roues | Version, kilométrage, entretien, documents, contrôle réglementaire applicable, sinistres connus, visite et essai. |
| Immobilier | Adresse/quartier, surface, loyer/prix et charges, disponibilité, conditions, diagnostics et visite ; vigilance sur faux bailleurs. |
| Vêtements / luxe | Taille réelle, état, mesures, authenticité quand pertinente, photos détaillées. |
| Collection / antiquités | Édition, provenance, authenticité, état, accessoires, conditionnement. |
| Outils / pièces | Référence, compatibilité, pièces manquantes, fonctionnement, sécurité, coût de remise en état. |
| Services | Prestations incluses, zone, devis, qualifications si applicables, délai, conditions d'annulation. |
| Emploi / missions | Contrat, lieu, salaire annoncé, période, expérience, recruteur, disponibilité du poste. |
| Dons | Gratuité effective, enlèvement, urgence, quantité et état. |

N'ajouter des vérifications spécialisées que lorsqu'elles **changent réellement** la pertinence, la sécurité ou le coût. Ne pas annoncer une authentification ou un contrôle matériel non effectué.

## 11. Évaluation : critères éliminatoires puis classement expliqué

### Étape 1 — exclusions

Écarter en priorité : hors périmètre obligatoire, vendu, achat en cours, logistique incompatible, problème de conformité évident, défaut rédhibitoire, prix complet hors plafond.

### Étape 2 — statuts des finalistes

- **A — Vérifiable et prioritaire** : annonce récente ou vendeur actif, conditions compatibles, prix intéressant, champs essentiels concordants.
- **B — Plausible mais à confirmer** : information manquante ou contradiction mineure, sans exclusion claire.
- **C — Risquée / non vérifiée** : disponibilité douteuse, logistique non confirmée, prix suspect ou preuves insuffisantes.
- **Exclue** : critère obligatoire non rempli ou transaction en cours/vendue.

Si un score chiffré est utile, utiliser un barème annoncé et adaptable, par exemple adéquation 35 %, coût complet 25 %, faisabilité 20 %, confiance 20 %. **Un score n'est ni une probabilité d'achat, ni une probabilité de fraude**, et ne remplace pas l'explication. Ne pas sur-noter une annonce lorsque des données manquent.

### Étape 3 — diversification

Si plusieurs annonces proviennent du même vendeur, même produit ou semblent des duplications/republications, signaler le regroupement. La réapparition du même article ne signifie pas plusieurs stocks indépendants.

## 12. Présenter un résultat exploitable et auditable

Pour chaque annonce recommandée, donner :

- **Titre exact ou identification fiable** + lien direct Leboncoin.
- **Prix, ville, date de publication**, et **nombre de favoris** si fourni.
- **Mode de remise confirmé ou à confirmer**, avec mention explicite de livraison activée ou non.
- **État et contenu** (pour éviter la confusion barebone/complet, lot/pièce, achat/location).
- **Transaction** : aucune en cours signalée / en cours / vendue / inconnu.
- **Fiabilité** : réputation et activité vendeur lorsque vérifiées, réserves importantes.
- **Pourquoi cette annonce**, et vérification indispensable avant de payer.

Classer en priorité les annonces **réellement exploitables**, pas uniquement les moins chères. Employer des liens individuels, pas une simple page de recherche. Éviter photos génériques présentées comme les photos de l'annonce.

Si aucune annonce ne satisfait les critères, l'indiquer avec précision : **périmètre exploré**, contraintes bloquantes et options raisonnables (autres variantes, dates, rayon, budget), sans inventer d'annonces.

## 13. Politique d'appels, limites et erreurs

- Préférer appels séquentiels ou petits lots raisonnables ; éviter les rafales de requêtes concurrentes qui peuvent solliciter excessivement le service.
- Utiliser pagination et filtres disponibles avant de multiplier des recherches redondantes.
- En cas de refus Datadome ou autre contrôle d'accès : **arrêter les nouvelles requêtes répétées**, signaler quelles fonctions échouent et lesquelles réussissent ; ne pas prétendre que le MCP est totalement hors service si seules les requêtes externes échouent.
- Ne pas utiliser de contournement de protections ou de recommandations pour les esquiver. Respecter les limitations du service et les conditions applicables.
- Ne pas relancer systématiquement toute une campagne après un seul échec. Un test ciblé de disponibilité peut suffire après résolution technique.
- Garder un résultat vérifié antérieurement comme **historique** avec date, pas comme vérification actuelle.
- Ne pas déclarer « alerte activée » ou « veille en cours » sans résultat positif explicite de l'outil correspondant.

## 14. Procédure complète

```text
Demande utilisateur
  ↓
Interpréter besoin, contraintes obligatoires, préférences, zone et transaction attendue
  ↓
Découvrir les capacités MCP disponibles
  ↓
Recherche directe → synonymes → fonctionnalités/équivalences → lots/erreurs usuelles
  ↓
Parcourir les résultats utiles, dédupliquer les IDs, noter la couverture
  ↓
Éliminer les incompatibilités évidentes
  ↓
get_ad sur les candidats : statut transaction, description, date, favoris, remise
  ↓
get_seller sur les finalistes : activité, avis, réponse, ancienneté
  ↓
Comparer coût complet, preuves, risques et faisabilité
  ↓
Classer A/B/C + exclusions, conserver inconnues visibles
  ↓
Restituer des liens directs, des raisons et les vérifications à demander
```

## 15. Cas de tests pour valider la skill

1. Annonce `status="active"` mais `transaction_status="Vendu"` → **exclue**.
2. Annonce `status="active"` mais `transaction_status="Achat en cours"` → **exclue**.
3. Annonce active sans `transaction_status` → **disponibilité non confirmée**, pas « libre garantie ».
4. `shippable="false"` mais « envoi possible » dans le texte → **livraison à confirmer**.
5. Annonce publiée il y a 5 ans, 310 favoris, vendeur sans activité connue → **forte incertitude**, même si prix attractif.
6. Annonce récente, peu de favoris, vendeur actif, 150 avis positifs → **signaux favorables**, sans garantie.
7. Prix de 250 € pour objet sans accessoires indispensables vs 300 € complet → **comparer le coût total**.
8. Recherche de meuble → **ne pas injecter CPU/SATA/NVMe ou filtres informatiques**.
9. Recherche de logement → **ne pas appliquer les frais d'expédition comme à un colis**.
10. Recherche de don → **ne pas considérer le prix 0 € comme anomalie**.
11. `old_price` renseigné, un seul point `price_history` → **ne pas affirmer une baisse enregistrée historiquement**.
12. Deux annonces presque identiques d'un même vendeur → **signaler duplication possible**.
13. `get_ad` retourne Datadome après succès de `search_ads` → **déclarer une disponibilité partielle**, pas complète.
14. Le MCP ne fournit pas `last_activity` → **inconnu**, jamais « vendeur inactif ».
15. Offre avec paiement hors plateforme obligatoire et aucune protection → **réserve sérieuse**, sans accuser sans preuve.

## 16. Améliorations possibles du MCP (facultatives, non garanties)

La skill orchestre le MCP existant : elle ne modifie pas le serveur à elle seule. Si l'utilisateur veut améliorer ce dernier, proposer :

- Historisation horodatée par ID (prix, favoris, transaction, mode de remise, présence de l'annonce).
- Suivi des nouvelles annonces et changements de statut, avec alertes uniquement après configuration effective.
- Gestion de couverture : pages parcourues, requêtes et filtres, déduplication multi-requêtes.
- Recherche multi-passes avec variantes linguistiques et erreurs de référence, en respectant les limites du service.
- Détection des republications et variantes d'un même vendeur avec provenance explicite.
- Normalisation robuste des booléens, dates et champs absents.
- Explications de classement auditables plutôt qu'un score opaque.
- Observabilité technique des erreurs, limitation de cadence et gestion correcte des refus d'accès.

**Règle finale :** une bonne recherche Leboncoin doit révéler **ce qui existe, ce qui correspond réellement au besoin, ce qui semble accessible, ce qui coûte réellement, et ce qu'on ignore encore**. Le lien d'une annonce ne constitue jamais, à lui seul, une garantie de disponibilité.
