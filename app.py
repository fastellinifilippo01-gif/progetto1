import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import time

# --- CONFIGURAZIONE ---
SHEET_NAME = "Scacchi_DB"
K_FACTOR = 32
RATING_INIZIALE = 1500

st.set_page_config(page_title="FFchess", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
    try:
        secrets = st.secrets["google_credentials"]
        credentials_info = json.loads(secrets["json_content"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Errore connessione: {str(e)}")
        return None

def get_all_data(gc, sheet_name):
    try:
        spreadsheet = gc.open(sheet_name)
        data = {}
        for ws_name in ["Giocatori", "Tornei", "Partite", "Partecipanti"]:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data[ws_name] = (pd.DataFrame(worksheet.get_all_records()), worksheet)
            except gspread.exceptions.WorksheetNotFound:
                data[ws_name] = (pd.DataFrame(), None)
        return data
    except Exception as e:
        st.error(f"❌ Errore lettura: {str(e)}")
        return {}

def safe_api_call(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    st.error("❌ Troppe richieste. Riprova tra 1 minuto.")
                    return None
            raise
    return None

# --- FUNZIONI LOGICHE ---
def calculate_elo(rating_a, rating_b, score_a):
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    new_a = rating_a + K_FACTOR * (score_a - expected_a)
    new_b = rating_b + K_FACTOR * ((1 - score_a) - (1 - expected_a))
    return round(new_a), round(new_b)

def swiss_pairing(players, past_matches):
    players_sorted = sorted(players, key=lambda x: x['Rating'], reverse=True)
    pairings = []
    paired = set()
    
    # Gestione bye (numero dispari)
    bye_player = None
    if len(players_sorted) % 2 == 1:
        for p in reversed(players_sorted):
            if p['Nome'] not in paired:
                bye_player = p
                paired.add(p['Nome'])
                break
    
    for i, p1 in enumerate(players_sorted):
        if p1['Nome'] in paired:
            continue
        for p2 in players_sorted[i+1:]:
            if p2['Nome'] in paired:
                continue
            history = [(m['Giocatore1'], m['Giocatore2']) for m in past_matches if m.get('Giocatore2')]
            if (p1['Nome'], p2['Nome']) in history or (p2['Nome'], p1['Nome']) in history:
                continue
            pairings.append((p1, p2))
            paired.add(p1['Nome'])
            paired.add(p2['Nome'])
            break
    
    return pairings, bye_player

# --- GESTIONE SESSIONE ---
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

def check_admin():
    if not st.session_state.admin_logged_in:
        st.warning("🔒 Accesso admin richiesto.")
        return False
    return True

def logout():
    st.session_state.admin_logged_in = False
    st.rerun()

# --- INTERFACCIA ---
st.title("♟️ FFchess")

gc = get_gc()
if not gc:
    st.stop()

data = get_all_data(gc, SHEET_NAME)
df_giocatori, ws_giocatori = data.get("Giocatori", (pd.DataFrame(), None))
df_tornei, ws_tornei = data.get("Tornei", (pd.DataFrame(), None))
df_partite, ws_partite = data.get("Partite", (pd.DataFrame(), None))
df_partecipanti, ws_partecipanti = data.get("Partecipanti", (pd.DataFrame(), None))

# Sidebar Menu
menu = st.sidebar.selectbox(
    "Menu", 
    ["🏠 Home", "🏆 Classifica FIDE", "📅 Tornei", "🔐 Login Admin"] if not st.session_state.admin_logged_in 
    else ["🏠 Home", "🏆 Classifica FIDE", "📅 Tornei", "🛡️ Admin", "🚪 Logout"]
)

if menu == "🚪 Logout":
    logout()

# --- HOME ---
if menu == "🏠 Home":
    st.header("Benvenuto su FFchess")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Giocatori", len(df_giocatori) if not df_giocatori.empty else 0)
    with col2: st.metric("Tornei", len(df_tornei) if not df_tornei.empty else 0)
    with col3: st.metric("Partite", len(df_partite) if not df_partite.empty else 0)
    
    st.divider()
    st.markdown("### 🏆 Ultimi Tornei")
    if not df_tornei.empty:
        st.dataframe(df_tornei.tail(5), use_container_width=True)
    else:
        st.info("Nessun torneo creato.")

# --- CLASSIFICA FIDE ---
elif menu == "🏆 Classifica FIDE":
    st.header("🏆 Classifica Generale FIDE")
    st.info("📊 Rating Elo aggiornato dopo ogni partita ufficiale")
    
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca giocatore")
        df_show = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)] if search else df_giocatori
        st.dataframe(df_show.sort_values("Rating", ascending=False).reset_index(drop=True), use_container_width=True)
    else:
        st.warning("Nessun giocatore registrato.")

# --- TORNEI ---
elif menu == "📅 Tornei":
    st.header("📅 Tornei")
    
    if not df_tornei.empty:
        # Seleziona torneo
        sel = st.selectbox("Seleziona Torneo", df_tornei['Nome'].tolist())
        t = df_tornei[df_tornei['Nome']==sel].iloc[0]
        tid = t['ID_Torneo']
        
        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Formato", t['Tipo'])
        with col2: st.metric("Stato", t['Stato'])
        with col3: st.metric("Data", t['Data'])
        
        st.divider()
        
        # Classifica del torneo (punti torneo, non FIDE)
        st.subheader("🏅 Classifica Torneo")
        if not df_partite.empty and not df_partecipanti.empty:
            partecipanti = df_partecipanti[df_partecipanti['ID_Torneo']==tid]['Nome'].tolist()
            
            # Calcola punti torneo per ogni partecipante
            punti_torneo = {}
            for nome in partecipanti:
                punti = 0
                partite = df_partite[(df_partite['ID_Torneo']==tid) & 
                                    ((df_partite['Giocatore1']==nome) | (df_partite['Giocatore2']==nome))]
                for _, p in partite.iterrows():
                    if p['Giocatore2'] is None or pd.isna(p['Giocatore2']):
                        # Bye
                        punti += 1.0  # o 0.5, dipende da come è stato configurato
                    elif p['Giocatore1'] == nome:
                        if p['Risultato'] == "1-0": punti += 1
                        elif p['Risultato'] == "0.5-0.5": punti += 0.5
                    else:
                        if p['Risultato'] == "0-1": punti += 1
                        elif p['Risultato'] == "0.5-0.5": punti += 0.5
                punti_torneo[nome] = punti
            
            # Crea classifica torneo
            df_classifica_torneo = pd.DataFrame([
                {"Nome": nome, "Punti Torneo": punti, "Rating FIDE": df_giocatori[df_giocatori['Nome']==nome]['Rating'].values[0] if not df_giocatori[df_giocatori['Nome']==nome].empty else 0}
                for nome, punti in punti_torneo.items()
            ]).sort_values("Punti Torneo", ascending=False).reset_index(drop=True)
            
            st.dataframe(df_classifica_torneo, use_container_width=True)
        else:
            st.info("Nessuna partita registrata per questo torneo.")
        
        st.divider()
        
        # Risultati partite
        st.subheader("♟️ Partite")
        if not df_partite.empty:
            partite_torneo = df_partite[df_partite['ID_Torneo']==tid]
            if not partite_torneo.empty:
                st.dataframe(partite_torneo, use_container_width=True)
            else:
                st.info("Nessuna partita giocata.")
    else:
        st.info("Nessun torneo disponibile.")

# --- LOGIN ADMIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Accesso Amministratore")
    pwd = st.text_input("Password", type="password")
    if st.button("Accedi"):
        try:
            if pwd == st.secrets["admin"]["password"]:
                st.session_state.admin_logged_in = True
                st.success("✅ Accesso effettuato!")
                st.rerun()
            else:
                st.error("❌ Password errata")
        except:
            st.error("Errore configurazione Secrets")

# --- ADMIN PANEL ---
elif menu == "🛡️ Admin":
    if not check_admin():
        st.stop()
    
    tab1, tab2, tab3 = st.tabs(["📝 Nuovo Torneo", "🎮 Gestisci Partite", "👤 Giocatori"])
    
    # --- TAB 1: CREA TORNEO ---
    with tab1:
        st.subheader("📝 Crea Nuovo Torneo")
        
        col1, col2 = st.columns(2)
        with col1:
            nome_torneo = st.text_input("Nome Torneo")
            tipo_torneo = st.selectbox("Formato", ["Svizzero", "Girone All'Italiana"])
        with col2:
            data_torneo = st.date_input("Data", datetime.now())
        
        st.divider()
        st.subheader("⚖️ Configurazione")
        bye_points = st.selectbox("Punti per Bye", [1.0, 0.5], help="Se un giocatore ha il bye, riceve questi punti torneo (non cambia il rating FIDE)")
        
        st.divider()
        st.subheader("👥 Partecipanti")
        if not df_giocatori.empty:
            partecipanti = st.multiselect(
                "Seleziona i giocatori per questo torneo",
                df_giocatori['Nome'].tolist(),
                help="Puoi selezionare solo alcuni giocatori per questo torneo"
            )
        else:
            st.warning("Nessun giocatore registrato. Aggiungine prima dalla tab 'Giocatori'.")
            partecipanti = []
        
        if st.button("📌 Crea Torneo", type="primary"):
            if nome_torneo and partecipanti and ws_tornei is not None:
                def _create():
                    id_t = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    ws_tornei.append_row([id_t, nome_torneo, str(data_torneo), tipo_torneo, "In Corso", bye_points])
                    # Salva partecipanti
                    if ws_partecipanti is not None:
                        for nome in partecipanti:
                            ws_partecipanti.append_row([id_t, nome])
                    return id_t
                result = safe_api_call(_create)
                if result:
                    st.success(f"✅ Torneo creato! {len(partecipanti)} partecipanti")
                    st.rerun()
    
    # --- TAB 2: GESTISCI PARTITE ---
    with tab2:
        st.subheader("🎮 Gestione Partite")
        
        if not df_tornei.empty and ws_partite is not None:
            sel = st.selectbox("Seleziona Torneo", df_tornei['Nome'].tolist(), key="admin_torneo")
            t_data = df_tornei[df_tornei['Nome']==sel].iloc[0]
            tid = t_data['ID_Torneo']
            bye_val = t_data.get('Bye', 1.0)
            
            # Ottieni partecipanti di questo torneo
            if not df_partecipanti.empty:
                partecipanti_nomi = df_partecipanti[df_partecipanti['ID_Torneo']==tid]['Nome'].tolist()
                partecipanti_data = df_giocatori[df_giocatori['Nome'].isin(partecipanti_nomi)].to_dict('records') if not df_giocatori.empty else []
            else:
                partecipanti_data = []
            
            if not partecipanti_data:
                st.warning("Nessun partecipante per questo torneo.")
            else:
                # Mostra round esistenti
                if not df_partite.empty:
                    partite_torneo = df_partite[df_partite['ID_Torneo']==tid]
                    if not partite_torneo.empty:
                        max_round = partite_torneo['Round'].max()
                        st.markdown(f"##### Ultimo Round: {max_round}")
                        
                        # Elimina round
                        st.markdown("##### 🗑️ Elimina Round")
                        round_da_eliminare = st.number_input("Numero round da eliminare", min_value=1, max_value=int(max_round) if max_round else 1)
                        if st.button("Elimina Round"):
                            def _delete():
                                # Elimina partite del round
                                partite_del = df_partite[(df_partite['ID_Torneo']==tid) & (df_partite['Round']==round_da_eliminare)]
                                for idx in sorted(partite_del.index, reverse=True):
                                    ws_partite.delete_rows(idx + 2)
                                
                                # Ricalcola rating
                                # (per semplicità, qui si potrebbe implementare il ricalcolo completo)
                            safe_api_call(_delete)
                            st.success(f"✅ Round {round_da_eliminare} eliminato")
                            st.rerun()
                        
                        st.divider()
                
                # Genera nuovo round
                if not df_partite.empty:
                    max_round = df_partite[df_partite['ID_Torneo']==tid]['Round'].max()
                    next_round = int(max_round) + 1
                else:
                    next_round = 1
                
                st.markdown(f"##### 🔄 Round #{next_round}")
                
                if st.button("Genera Abbinamenti", type="primary"):
                    past = df_partite[df_partite['ID_Torneo']==tid].to_dict('records') if not df_partite.empty else []
                    pairings, bye_player = swiss_pairing(partecipanti_data, past)
                    st.session_state['pairings'] = pairings
                    st.session_state['bye_player'] = bye_player
                    st.session_state['current_round'] = next_round
                    st.success(f"✅ Generati {len(pairings)} incontri" + (f" | Bye: {bye_player['Nome']}" if bye_player else ""))
                
                if 'pairings' in st.session_state and st.session_state.get('current_round') == next_round:
                    for i, (p1, p2) in enumerate(st.session_state['pairings']):
                        col1, col2, col3 = st.columns([2, 2, 1])
                        with col1:
                            if p2 is None:
                                st.write(f"🤍 {p1['Nome']} ({p1['Rating']}) - **BYE**")
                            else:
                                st.write(f"🤍 {p1['Nome']} ({p1['Rating']})")
                        with col2:
                            if p2 is None:
                                st.write(f"⚪ +{bye_val} punti torneo")
                            else:
                                st.write(f"🖤 {p2['Nome']} ({p2['Rating']})")
                        with col3:
                            if p2 is None:
                                st.selectbox("Ris.", ["Bye"], key=f"m{i}", disabled=True)
                                st.session_state[f'res_{i}'] = "Bye"
                            else:
                                res = st.selectbox("Ris.", ["1-0", "0.5-0.5", "0-1"], key=f"m{i}")
                                st.session_state[f'res_{i}'] = res
                    
                    if st.button("💾 Salva Risultati", type="primary"):
                        def _save():
                            for i, (p1, p2) in enumerate(st.session_state['pairings']):
                                res = st.session_state[f'res_{i}']
                                if p2 is None:
                                    # Bye - nessun cambio rating FIDE
                                    ws_partite.append_row([tid, next_round, p1['Nome'], None, f"Bye"])
                                else:
                                    # Partita normale - aggiorna rating FIDE
                                    ws_partite.append_row([tid, next_round, p1['Nome'], p2['Nome'], res])
                                    score = 1.0 if res=="1-0" else 0.5 if res=="0.5-0.5" else 0.0
                                    r1, r2 = p1['Rating'], p2['Rating']
                                    n1, n2 = calculate_elo(r1, r2, score)
                                    if ws_giocatori is not None:
                                        idx1 = df_giocatori[df_giocatori['Nome']==p1['Nome']].index[0] + 2
                                        idx2 = df_giocatori[df_giocatori['Nome']==p2['Nome']].index[0] + 2
                                        ws_giocatori.update_cell(idx1, 3, n1)
                                        ws_giocatori.update_cell(idx2, 3, n2)
                        
                        safe_api_call(_save)
                        st.success("✅ Risultati salvati!")
                        st.session_state['pairings'] = None
                        st.session_state['current_round'] = None
                        st.rerun()
    
    # --- TAB 3: GIOCATORI ---
    with tab3:
        st.subheader("👤 Gestione Giocatori")
        
        if not df_giocatori.empty:
            st.dataframe(df_giocatori.sort_values("Rating", ascending=False), use_container_width=True)
        
        st.divider()
        st.subheader("➕ Aggiungi Giocatore")
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome")
        with col2:
            rating = st.number_input("Rating Iniziale", value=RATING_INIZIALE)
        
        if st.button("Aggiungi") and ws_giocatori is not None:
            def _add():
                ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d%H%M%S')}", nome, rating, ""])
            safe_api_call(_add)
            st.success("✅ Aggiunto!")
            st.rerun()

st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ FFchess - App Amatoriale Non Ufficiale FIDE</div>", unsafe_allow_html=True)
