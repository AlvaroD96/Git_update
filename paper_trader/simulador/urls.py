from django.urls import path

from . import views

urlpatterns = [
    path("", views.panel, name="panel"),
    path("nueva/", views.nueva, name="nueva"),
    path("operacion/<int:pk>/", views.detalle, name="detalle"),
    path("operacion/<int:pk>/decidir/", views.decidir, name="decidir"),
    path("operacion/<int:pk>/resolver/", views.resolver, name="resolver"),
    path("escaner/", views.escaner, name="escaner"),
    path("reiniciar/", views.reiniciar, name="reiniciar"),
    path("reglas/", views.reglas, name="reglas"),
    path("exportar/diario.csv", views.exportar_csv, name="exportar_csv"),
    path("exportar/ordenes.json", views.exportar_ordenes, name="exportar_ordenes"),
]
