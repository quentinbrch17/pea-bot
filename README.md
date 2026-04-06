# PEA Tracker Bot 🤖

Bot Telegram de suivi de patrimoine — ETF, Livret A et Cryptos.

## Fonctionnalités

- Suivi en temps réel de l'ETF Amundi PEA Monde (Yahoo Finance)
- Suivi des cryptos Coinbase (CoinGecko)
- Vue patrimoine complète : PEA + Livret A + Cryptos
- Alertes automatiques ETF si baisse ≥ seuil depuis le PRU
- Alertes Bitcoin si prix < 50 000€ ou < 40 000€
- Résumé hebdomadaire chaque lundi à 8h
- Historique des achats avec calcul PRU automatique

## Commandes

| Commande | Description |
|---|---|
| `/patrimoine` | Vue complète de tout ton patrimoine en temps réel |
| `/cours` | Prix ETF + signal opportunité |
| `/status` | Détail complet du PEA |
| `/historique` | Tous tes achats ETF avec PRU |
| `/achat <parts> <prix>` | Enregistrer un achat ETF (ex: `/achat 75 5.20`) |
| `/livreta <montant>` | Mettre à jour le solde Livret A (ex: `/livreta 10250`) |
| `/help` | Liste des commandes |

## Alertes automatiques

**ETF Amundi PEA Monde**
| Baisse depuis PRU | Signal |
|---|---|
| -5% | 📉 Légère baisse — surveiller |
| -10% | 🎯 Opportunité — envisager versement supplémentaire |
| -15% | ⚡ Bonne opportunité — versement recommandé |
| -20% | 🔥 Excellente opportunité — agir si liquidités disponibles |

**Bitcoin**
| Prix | Signal |
|---|---|
| < 50 000€ | 📉 Opportunité modérée — envisager 50€ |
| < 40 000€ | 🔥 Opportunité forte — envisager 100€ |

## Déploiement sur Railway

### 1. GitHub
Crée un repo `pea-bot` et upload les 4 fichiers : `bot.py`, `requirements.txt`, `Procfile`, `README.md`

### 2. Railway
1. railway.app → "New Project" → "Deploy from GitHub repo"
2. Sélectionne `pea-bot`
3. Variables → Raw Editor, colle :

```
BOT_TOKEN=ton_token_telegram
CHAT_ID=ton_chat_id
ENTRY_PRICE=5.359
ALERT_THRESHOLD=-10
JSONBIN_KEY=ta_master_key
JSONBIN_BIN_ID=ton_bin_id
```

4. Railway déploie automatiquement

### 3. JSONBin
1. Crée un compte sur jsonbin.io
2. Crée un Bin avec `{"achats": []}` comme contenu initial
3. Récupère le Bin ID et la Master Key

## Portefeuille suivi

**ETF PEA**
- Amundi PEA Monde MSCI World (FR001400U5Q4)
- Achat initial : 710 parts @ 5,359€

**Cryptos Coinbase**
- BTC, ETH, SOL, BCH, XLM, LTC, ADA

**Livret A**
- Solde initial : 10 000,11€
- Mise à jour manuelle via `/livreta`

## Sécurité
Après configuration, régénère :
- Token Telegram via BotFather → `/revoke`
- Master Key JSONBin via ton profil
