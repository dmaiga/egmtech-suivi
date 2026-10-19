# egmtech-suivi-terrain

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Base de données

```bash
python manage.py migrate
python manage.py createsuperuser
```

## Lancer le serveur

```bash
python manage.py runserver
```

Application accessible sur http://127.0.0.1:8000/, admin sur http://127.0.0.1:8000/admin/.
