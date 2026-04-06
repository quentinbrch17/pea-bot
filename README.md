# PEA Tracker Bot 🤖

Bot Telegram pour suivre l'ETF Amundi PEA Monde et recevoir des alertes d'opportunité.

## Fonctionnalités

- Vérification du cours toutes les heures
- Alertes automatiques si baisse ≥ seuil depuis ton prix d'entrée
- Résumé hebdomadaire chaque lundi à 8h
- Commandes : /cours, /status, /help

## Déploiement sur Railway

### 1. Prépare le repo GitHub

1. Va sur github.com → "New repository"
2. Nomme-le `pea-bot`
3. Upload les 3 fichiers : bot.py, requirements.txt, Procfile

### 2. Déploie sur Railway

1. Va sur railway.app
2. "New Project" → "Deploy from GitHub repo"
3. Sélectionne `pea-bot`
4. Clique sur "Variables" et ajoute :

```
BOT_TOKEN = ton_token_telegram
CHAT_ID = 7536394198
ENTRY_PRICE = 5.359
ALERT_THRESHOLD = -10
```

5. Railway déploie automatiquement

### 3. Commandes disponibles

- `/cours` — Prix actuel + signal opportunité
- `/status` — Résumé portefeuille complet
- `/help` — Aide

## Niveaux d'alerte

| Baisse depuis entrée | Niveau | Action |
|---|---|---|
| -5% | 📉 Légère baisse | Surveiller |
| -10% | 🎯 Opportunité | Envisager versement supplémentaire |
| -15% | ⚡ Bonne opportunité | Versement recommandé |
| -20% | 🔥 Excellente opportunité | Agir si liquidités disponibles |
