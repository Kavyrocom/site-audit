# Exemple : l'agent applique un plan d'action

Test réel sur un petit site fictif servi en local (Studio Zorbul, photographe), avec des défauts volontaires. Le site n'existe pas en ligne.

- `action-plan.md` : le plan après les corrections. Les cases cochées sont les actions que l'agent a appliquées et vérifiées.
- `fix-log.md` : le journal horodaté. On y voit les accès fournis, chaque **GO** et ce qui a été **vérifié** avant de cocher.

Ce qui s'est passé, en quatre échanges :

1. L'agent a monté le suivi (12 actions, par priorité), a vu que 3 actions étaient prêtes, et a demandé **en un seul message** tout ce qui manquait pour les autres (décisions, textes, photos réelles, accès).
2. La personne a répondu et donné un GO groupé pour 4 actions. L'agent les a appliquées dans l'ordre de priorité, sans toucher à celles qui attendaient un élément, et a vérifié chacune.
3. La personne a répondu à une question de décision sans donner de GO. L'agent n'a **rien modifié** et a redemandé le GO, en rappelant le risque et le retour arrière.
4. GO pour les deux actions suivantes : appliquées et vérifiées.

Résultat : 6 actions sur 12 appliquées, 5 en attente d'un élément que seule la personne peut fournir, 1 confiée à un humain (en-têtes du serveur). Voir le README principal pour la mesure avant et après.

**À lire avec ce recul.** Cette session date d'avant la règle « un seul GO à la fois » : le journal montre des GO groupés (« GO pour P1, P2, P4 et P8 », « GO pour P5 puis P6 »), dont une action à risque élevé approuvée avec une autre. Depuis, la règle est qu'un GO couvre une action : l'agent demande P5, attend la réponse, l'applique, puis demande P6. Le suivi (`fix_tracker.py`) n'empêche que d'ouvrir une seconde action tant qu'une autre est approuvée et pas terminée ; il ne peut pas savoir si la personne a vraiment été interrogée deux fois, cette partie reste à l'agent. Les durées et le coût du journal sont ceux de la session d'origine ; elle n'a pas été rejouée.
