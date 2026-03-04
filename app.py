# Updated FFchess Application Code

class Classifica:
    def __init__(self):
        self.torneo = []  # List to hold tournament participants

    def aggiungi_partecipante(self, partecipante):
        self.torneo.append(partecipante)

    def rimuovi_partecipante(self, partecipante):
        self.torneo.remove(partecipante)

    def ordina_classifica(self):
        sorted_torneo = sorted(self.torneo, key=lambda p: p.punti, reverse=True)
        return sorted_torneo

    def mostra_classifica(self):
        for partecipante in self.ordina_classifica():
            print(partecipante.nome, partecipante.punti)