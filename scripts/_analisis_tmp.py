"""Diagnostica por que la prueba E2E no localiza el quiz en MongoDB."""
import sys

sys.path.insert(0, ".")
from pymongo import MongoClient

from app.config import settings

print("MONGODB_URI       :", settings.MONGODB_URI)
print("MONGODB_DB        :", settings.MONGODB_DB)
print("ALTERNATIVAS      :", settings.MONGODB_URI_ALTERNATIVAS)
print()

for uri in [settings.MONGODB_URI, *settings.MONGODB_URI_ALTERNATIVAS]:
    etiqueta = uri.replace("admin123", "***")
    try:
        cliente = MongoClient(uri, serverSelectionTimeoutMS=2500)
        base = cliente[settings.MONGODB_DB]
        colecciones = base.list_collection_names()
        total = base.quizzes_verificacion.count_documents({})
        print(f"OK    {etiqueta}")
        print(f"      colecciones: {colecciones}")
        print(f"      quizzes_verificacion: {total} documento(s)")
        if total:
            doc = base.quizzes_verificacion.find_one()
            print(f"      claves de un documento: {sorted(doc.keys())}")
    except Exception as exc:
        print(f"FALLA {etiqueta}")
        print(f"      {type(exc).__name__}: {str(exc)[:200]}")
    print()
